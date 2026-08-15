#pragma once
/** 主接线模块：热键/IPC 触发 → 选区 → 存图/OCR/剪贴板 → 托盘气泡。
 *
 * 忙时热键入队（FIFO）：选区/OCR 进行中再触发不丢弃，收尾统一走 finish()。
 * 热键回调线程不定（X11 轮询线程 / Wayland D-Bus 线程），统一经
 * QMetaObject::invokeMethod(QueuedConnection) 派发到 GUI 线程。
 */
#include <QObject>
#include <QString>

#include <deque>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

class QPixmap;
class Selector;
class TrayIcon;
class IpcServer;
class Hotkey;
class OcrEngine;

class App : public QObject {
    Q_OBJECT
public:
    enum class Mode { Image, Ocr };

    explicit App(QObject* parent = nullptr);
    ~App() override;

    void init(const QString& modelsDir);  // 注册热键/托盘/IPC
    void trigger(Mode m);                 // 命令行/IPC 触发（GUI 线程调用）

    QString socketPath() const;

private:
    void onHotkey(Mode m);                // 任意线程调用：marshal 到 GUI 线程
    void startSelect(Mode m);
    void showSelector(Mode m);            // 全屏图 + 自绘拉框（X11/Wayland 共用）
    void handleRegion(const QPixmap& region, Mode m);
    void finish();                        // 收尾：busy=false + 执行下一个

    void onOcrDone(const QString& text, const QString& err, const QString& base,
                   bool saveImgs);
    void copyPixmap(const QPixmap& pix);
    void copyText(const QString& text);

    std::shared_ptr<OcrEngine> ensureEngine();
    void prewarmEngine(const QString& modelsDir);

    QString mkTimestampBase() const;
    void savePng(const QPixmap& pix, const QString& base);
    void saveTxt(const QString& text, const QString& base);

    // ── 成员 ──
    QString modelsDir_;
    QString dataDir_;
    QString imgDir_;
    QString textDir_;
    bool busy_ = false;
    std::deque<Mode> pending_;

    std::unique_ptr<TrayIcon> tray_;
    std::vector<std::unique_ptr<Hotkey>> hotkeys_;
    std::unique_ptr<Hotkey> escHk_;       // X11 选区期间临时 Esc
    std::unique_ptr<Selector> selector_;  // 选区 overlay（X11 实时 / Wayland 截图）
    std::unique_ptr<IpcServer> ipc_;
    QPixmap* fullPix_ = nullptr;          // 当前选区的全屏图

    // OCR 引擎（惰性 + 后台预热，跨线程共享）
    std::mutex engineMtx_;
    std::shared_ptr<OcrEngine> engine_;
    std::vector<std::thread> workers_;
    bool prewarmed_ = false;
};