#include "app.h"

#include <QClipboard>
#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QGuiApplication>
#include <QImage>
#include <QMetaObject>
#include <QMimeData>
#include <QPixmap>
#include <QScreen>
#include <QStringList>
#include <QTimer>
#include <QtGlobal>

#include <chrono>
#include <cctype>
#include <cstdio>
#include <exception>

#include <opencv2/imgproc.hpp>

#include "config.h"
#include "hotkey.h"
#include "ipc.h"
#include "ocr.h"
#include "portal.h"
#include "tray.h"
#include "ui.h"

namespace {

QString expandHome(const QString& p) {
    if (p.startsWith(QLatin1String("~/"))) {
        return QDir::homePath() + p.mid(1);
    }
    return p;
}

cv::Mat qpixmapToBgr(const QPixmap& pix) {
    const QImage img = pix.toImage().convertToFormat(QImage::Format_RGB888);
    cv::Mat rgb(img.height(), img.width(), CV_8UC3,
                const_cast<uchar*>(img.constBits()), img.bytesPerLine());
    cv::Mat bgr;
    cv::cvtColor(rgb, bgr, cv::COLOR_RGB2BGR);
    return bgr.clone();  // 拷贝脱离 QImage 生命周期
}

// config 热键（"alt+x" → key+mods）→ XDG shortcut 串（"ALT+X"）。
// portal GlobalShortcuts 的 preferred_trigger 用 XDG 格式（大写修饰键 + xkb
// keysym），`<Alt>X`/小写均解析失败 → current=none → 绑了但不触发。
std::string xdgShortcut(const cfg::Hotkey& hk) {
    if (!hk.valid) return {};
    std::string out;
    if (hk.mods & 1) out += "SHIFT+";
    if (hk.mods & 4) out += "CTRL+";
    if (hk.mods & 8) out += "ALT+";
    if (hk.mods & 64) out += "LOGO+";
    std::string key = hk.key;
    if (!key.empty()) key[0] = static_cast<char>(std::toupper(static_cast<unsigned char>(key[0])));
    return out + key;
}

}  // namespace

App::App(QObject* parent) : QObject(parent) {
    dataDir_ = expandHome(QString::fromStdString(cfg::str("data_dir")));
    imgDir_ = dataDir_ + QStringLiteral("/img");
    textDir_ = dataDir_ + QStringLiteral("/text");
}

App::~App() {
    for (auto& t : workers_) {
        if (t.joinable()) t.join();
    }
}

QString App::socketPath() const {
    return expandHome(QString::fromStdString(cfg::str("lock_path"))).replace(
               QStringLiteral(".lock"), QStringLiteral(".sock"));
}

void App::init(const QString& modelsDir) {
    modelsDir_ = modelsDir;

    // 数据目录（SAVE_IMAGES=false 时也不创建，与旧行为一致）
    const bool saveImgs = cfg::bool_("save_images");
    if (saveImgs) {
        QDir().mkpath(imgDir_);
        QDir().mkpath(textDir_);
    }

    const QString hint =
        QStringLiteral("Alt+X 截图并复制图片\nAlt+C 截图并 OCR");
    tray_ = std::make_unique<TrayIcon>(
        QDir(modelsDir).filePath(QStringLiteral("../icons/snaptext-64.png")), hint, this);
    QObject::connect(tray_.get(), &TrayIcon::quitRequested, this, [this]() {
        QCoreApplication::quit();
    });

    // 热键
    const cfg::Hotkey hkImg = cfg::parseHotkey(cfg::str("hotkey_image"));
    const cfg::Hotkey hkOcr = cfg::parseHotkey(cfg::str("hotkey_ocr"));
    if (session::type() == session::Wayland) {
        // Wayland：全局快捷键走 xdg-desktop-portal GlobalShortcuts（跨合成器标准，
        // 不再依赖用户在自己合成器里绑 `snaptext --ocr/--img` 命令）。一次会话
        // 绑定 img/ocr 两条；后端不可用（ok=false）时回退 CLI+IPC 触发。
        hotkeys_.push_back(makeWaylandHotkeys(
            xdgShortcut(hkImg), xdgShortcut(hkOcr),
            [this]() { onHotkey(Mode::Image); },
            [this]() { onHotkey(Mode::Ocr); }));
    } else {
        if (hkImg.valid) {
            hotkeys_.push_back(makeHotkey(hkImg.key, hkImg.mods,
                                          [this]() { onHotkey(Mode::Image); }));
        }
        if (hkOcr.valid) {
            hotkeys_.push_back(makeHotkey(hkOcr.key, hkOcr.mods,
                                          [this]() { onHotkey(Mode::Ocr); }));
        }
    }

    // IPC（CLI 触发兜底）
    ipc_ = std::make_unique<IpcServer>(socketPath(), this);
    QObject::connect(ipc_.get(), &IpcServer::commandReceived, this,
                     [this](const QString& cmd) {
                         if (cmd == QLatin1String("ocr")) trigger(Mode::Ocr);
                         else if (cmd == QLatin1String("img")) trigger(Mode::Image);
                     });

    if (cfg::bool_("prewarm_ocr")) {
        prewarmEngine(modelsDir_);
    }
}

void App::trigger(Mode m) {
    onHotkey(m);
}

void App::onHotkey(Mode m) {
    // 热键回调可能在轮询线程；marshal 到 GUI 线程再处理
    QMetaObject::invokeMethod(this, [this, m]() { startSelect(m); },
                              Qt::QueuedConnection);
}

void App::startSelect(Mode m) {
    if (busy_) {
        pending_.push_back(m);  // 忙时入队，不丢弃
        return;
    }
    busy_ = true;

    if (session::type() == session::Wayland) {
        // portal 非交互抓全屏（跨合成器通用）→ 自绘 Selector 选区
        portalScreenshotFullscreen(this, [this, m](QString path, bool cancelled) {
            if (cancelled) {
                finish();  // 用户取消，静默
                return;
            }
            if (path.isEmpty()) {
                tray_->notify(QStringLiteral("拾字 SnapText"), QStringLiteral("截图失败"));
                finish();
                return;
            }
            QPixmap pix(path);
            if (pix.isNull()) {
                qWarning("portal 图加载失败: %s", qPrintable(path));
                finish();
                return;
            }
            // 高分屏：portal 返回合成器输出的物理分辨率图，选区/裁剪的 dpr 换算依赖
            // 有效 dpr = 图物理尺寸 / 屏逻辑几何。**不能直接用
            // QScreen::devicePixelRatio()**——KWin 分数缩放（如 150%，Qt 可能上报
            // 整数 2）时二者不一致（图 3840×2160 / 逻辑 2560×1440 = 1.5），
            // 选区会错位。用尺寸比推导保证图逻辑尺寸 == 屏逻辑几何。
            const QScreen* s = QGuiApplication::primaryScreen();
            const qreal dpr = s ? double(pix.width()) / double(s->geometry().width()) : 1.0;
            pix.setDevicePixelRatio(dpr);
            fullPix_ = new QPixmap(pix);
            showSelector(m);
        });
        return;
    }

    // X11：抓全屏 + 自绘拉框 overlay
    fullPix_ = new QPixmap(grabScreen());
    if (fullPix_->isNull()) {
        finish();
        return;
    }
    showSelector(m);

    // X11 override-redirect 收不到键盘，Esc 用临时全局热键兜底；
    // Wayland 的 Selector 是普通窗口能拿键盘焦点，Esc 原生可用
    escHk_ = makeHotkey(cfg::str("esc_key"), 0, [this]() {
        QMetaObject::invokeMethod(this, [this]() {
            if (selector_) selector_->close();
        }, Qt::QueuedConnection);
    });
}

void App::showSelector(Mode m) {
    selector_ = std::make_unique<Selector>(*fullPix_, this);
    QObject::connect(selector_.get(), &Selector::selected, this,
                     [this, m](const QRect& r) {
                         const qreal dpr = fullPix_->devicePixelRatio();
                         const QRect src(qRound(r.x() * dpr), qRound(r.y() * dpr),
                                         qRound(r.width() * dpr), qRound(r.height() * dpr));
                         QPixmap region = fullPix_->copy(src);
                         selector_.reset();
                         handleRegion(region, m);
                     });
    QObject::connect(selector_.get(), &Selector::cancelled, this, [this]() {
        selector_.reset();
        finish();
    });
    selector_->show();
}

void App::handleRegion(const QPixmap& region, Mode m) {
    const bool saveImgs = cfg::bool_("save_images");
    QString base = saveImgs ? mkTimestampBase() : QString();
    if (m == Mode::Image) {
        if (saveImgs) savePng(region, base);
        copyPixmap(region);
        QString msg = saveImgs
            ? QStringLiteral("已复制图片  %1/%2.png").arg(imgDir_, base)
            : QStringLiteral("已复制图片");
        tray_->notify(QStringLiteral("拾字 SnapText"), msg);
        finish();
        return;
    }

    // OCR：后台线程推理，BGR 进内存（saveImgs=false 也不落盘）
    if (saveImgs) savePng(region, base);
    std::shared_ptr<cv::Mat> bgr = std::make_shared<cv::Mat>(qpixmapToBgr(region));
    std::shared_ptr<OcrEngine> engine = ensureEngine();
    workers_.push_back(std::thread([this, engine, bgr, base, saveImgs]() {
        QString text, err;
        try {
            text = QString::fromUtf8(engine->recognize(*bgr).c_str());
        } catch (const std::exception& e) {
            err = QString::fromLocal8Bit(e.what());
        }
        QMetaObject::invokeMethod(this,
                                  [this, text, err, base, saveImgs]() {
                                      onOcrDone(text, err, base, saveImgs);
                                  },
                                  Qt::QueuedConnection);
    }));
}

void App::onOcrDone(const QString& text, const QString& err, const QString& base,
                    bool saveImgs) {
    if (!err.isEmpty()) {
        tray_->notify(QStringLiteral("OCR 失败"), err);
        finish();
        return;
    }
    copyText(text);
    if (saveImgs && !base.isEmpty()) saveTxt(text, base);
    const int lines = text.count(QLatin1Char('\n')) + (text.isEmpty() ? 0 : 1);
    const QString msg = QStringLiteral("已复制文字（%1 行）").arg(lines);
    tray_->notify(QStringLiteral("拾字 SnapText"), msg);
    finish();
}

void App::finish() {
    busy_ = false;
    if (!pending_.empty()) {
        const Mode m = pending_.front();
        pending_.pop_front();
        QTimer::singleShot(0, this, [this, m]() { startSelect(m); });
    }
}

void App::copyPixmap(const QPixmap& pix) {
    auto* mime = new QMimeData;
    mime->setImageData(pix.toImage());
    QGuiApplication::clipboard()->setMimeData(mime, QClipboard::Clipboard);
}

void App::copyText(const QString& text) {
    QGuiApplication::clipboard()->setText(text, QClipboard::Clipboard);
}

QString App::mkTimestampBase() const {
    return QDateTime::currentDateTime().toString(QStringLiteral("yyyyMMdd_HHmmss_zzz"));
}

void App::savePng(const QPixmap& pix, const QString& base) {
    pix.save(imgDir_ + QLatin1Char('/') + base + QStringLiteral(".png"));
}

void App::saveTxt(const QString& text, const QString& base) {
    QFile f(textDir_ + QLatin1Char('/') + base + QStringLiteral(".txt"));
    if (f.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        f.write(text.toUtf8());
    }
}

std::shared_ptr<OcrEngine> App::ensureEngine() {
    std::lock_guard<std::mutex> lk(engineMtx_);
    if (!engine_) {
        const QString d = modelsDir_ + QLatin1Char('/');
        engine_ = std::make_shared<OcrEngine>(
            (d + QStringLiteral("PP-OCRv6_det_small.onnx")).toStdString(),
            (d + QStringLiteral("ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx")).toStdString(),
            (d + QStringLiteral("PP-OCRv6_rec_small.onnx")).toStdString());
    }
    return engine_;
}

void App::prewarmEngine(const QString& modelsDir) {
    if (prewarmed_) return;
    prewarmed_ = true;
    std::thread([this, modelsDir]() {
        // 后台线程提前建引擎（~0.8s），与后续 OCR 线程共享进程级单例
        std::lock_guard<std::mutex> lk(engineMtx_);
        if (engine_) return;
        const QString d = modelsDir + QLatin1Char('/');
        engine_ = std::make_shared<OcrEngine>(
            (d + QStringLiteral("PP-OCRv6_det_small.onnx")).toStdString(),
            (d + QStringLiteral("ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx")).toStdString(),
            (d + QStringLiteral("PP-OCRv6_rec_small.onnx")).toStdString());
    }).detach();
}