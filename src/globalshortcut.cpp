// Wayland 全局快捷键：xdg-desktop-portal GlobalShortcuts（跨合成器标准接口）。
//
// 背景：Wayland 无统一全局快捷键协议（zwp_global_shortcuts_v1 标准里有但
// KDE/GNOME 均未实现），合成器各自为政。唯一跨合成器的标准入口是 portal 的
// org.freedesktop.portal.GlobalShortcuts：KDE Plasma 6+、GNOME 48+、Hyprland
// 都有后端实现（Electron/Chromium/OBS 均走它）。故热键不再只靠合成器绑
// `snaptext --ocr/--img` 命令，而是应用侧直接经 portal 绑定，触发即 Activated。
//
// 流程（踩坑见 AGENTS.md「Wayland 通用架构」节）：
//  1. Registry.Register(app_id)：portal>=1.20 要求 host 应用先声明身份，且
//     app_id 必须由同名 .desktop 文件（~/.local/share/applications 或
//     /usr/share/applications/<app_id>.desktop）支撑，否则报
//     "App info not found" / 后端 kglobalaccel NoSuchComponent。
//  2. CreateSession：Request 路径 = /org/freedesktop/portal/desktop/request/
//     {bus名去前导冒号、:/.→_}/{token}；Response 信号不带显式 D-Bus 签名
//     connect（带 "uav" 签名会静默失效）。
//  3. BindShortcuts：同步返回实际 request_handle，订阅它收 Response；
//     preferred_trigger 必须是 XDG 格式（大写修饰键，如 "ALT+X"），`<Alt>X`
//     或小写解析失败 → current=none → 快捷键绑了但不触发。
//  4. Activated(session_handle, shortcut_id, timestamp, options) 触发。

#include "hotkey.h"

#include <QDBusConnection>
#include <QDBusMessage>
#include <QDBusMetaType>
#include <QDBusObjectPath>
#include <QDebug>
#include <QPair>
#include <QRandomGenerator>
#include <QStringList>
#include <QVariantMap>

typedef QPair<QString, QVariantMap> ShortcutEntry;
Q_DECLARE_METATYPE(ShortcutEntry)
Q_DECLARE_METATYPE(QList<ShortcutEntry>)

namespace {

constexpr const char* kService = "org.freedesktop.portal.Desktop";
constexpr const char* kPath = "/org/freedesktop/portal/desktop";
constexpr const char* kIface = "org.freedesktop.portal.GlobalShortcuts";
constexpr const char* kReqIface = "org.freedesktop.portal.Request";
constexpr const char* kAppId = "io.github.a2heng.snaptext";

// portal 端 Response 信号路径 = {bus 唯一名去前导 ':'、':.'→'_'}/{token}
QString requestPath(const QString& bus, const QString& token) {
    QString s = bus;
    s.remove(0, 1);  // 去掉前导 ':'
    s.replace(QLatin1Char(':'), QLatin1Char('_'))
        .replace(QLatin1Char('.'), QLatin1Char('_'));
    return QStringLiteral("/org/freedesktop/portal/desktop/request/%1/%2").arg(s, token);
}

class GlobalShortcutsBackend : public QObject, public Hotkey {
    Q_OBJECT
public:
    GlobalShortcutsBackend(std::string triggerImg, std::string triggerOcr,
                           std::function<void()> onImgPress,
                           std::function<void()> onOcrPress)
        : onImgPress_(std::move(onImgPress)),
          onOcrPress_(std::move(onOcrPress)),
          triggerImg_(QString::fromStdString(triggerImg)),
          triggerOcr_(QString::fromStdString(triggerOcr)) {
        if (triggerImg_.isEmpty() && triggerOcr_.isEmpty()) return;
        qDBusRegisterMetaType<ShortcutEntry>();
        qDBusRegisterMetaType<QList<ShortcutEntry>>();
        // 触发信号由 portal 服务在 GlobalShortcuts 接口发出，用不带签名的
        // connect 订阅（带签名同样会静默失效，见 AGENTS.md）
        QDBusConnection::sessionBus().connect(
            QString::fromLatin1(kService), QString::fromLatin1(kPath),
            QString::fromLatin1(kIface), QStringLiteral("Activated"),
            this, SLOT(onActivated(QDBusObjectPath, QString, qulonglong, QVariantMap)));
        registerApp();
    }

    ~GlobalShortcutsBackend() override {
        QDBusConnection::sessionBus().disconnect(
            QString::fromLatin1(kService), QString::fromLatin1(kPath),
            QString::fromLatin1(kIface), QStringLiteral("Activated"),
            this, SLOT(onActivated(QDBusObjectPath, QString, qulonglong, QVariantMap)));
    }

    bool ok() const override { return ok_; }

    // 会话随进程退出由 portal 自动回收，无需显式关闭
    void release() override {}

private Q_SLOTS:
    void onResponse(uint code, const QVariantMap& results) {
        if (done_) return;
        if (code != 0) {
            done_ = true;  // 拒绝授权 / 后端错误：不启用热键
            return;
        }
        if (cur_ == kCreate) {
            QVariant v = results.value(QStringLiteral("session_handle"));
            if (!v.isValid()) {
                done_ = true;
                return;
            }
            sessionHandle_ = v.toString();
            bindShortcuts();
        } else if (cur_ == kBind) {
            done_ = true;
            ok_ = true;
        }
    }

    void onActivated(const QDBusObjectPath& sessionHandle, const QString& shortcutId,
                     qulonglong timestamp, const QVariantMap& options) {
        Q_UNUSED(sessionHandle);
        Q_UNUSED(timestamp);
        Q_UNUSED(options);
        if (shortcutId == QLatin1String("img") && onImgPress_) {
            onImgPress_();
        } else if (shortcutId == QLatin1String("ocr") && onOcrPress_) {
            onOcrPress_();
        }
    }

private:
    void registerApp() {
        QDBusMessage call = QDBusMessage::createMethodCall(
            QString::fromLatin1(kService), QString::fromLatin1(kPath),
            QStringLiteral("org.freedesktop.host.portal.Registry"), QStringLiteral("Register"));
        QVariantMap opts;
        call.setArguments({ QVariant(QString::fromLatin1(kAppId)), QVariant(opts) });
        QDBusMessage reply = QDBusConnection::sessionBus().call(call, QDBus::BlockWithGui, 10000);
        if (reply.type() == QDBusMessage::ErrorMessage) {
            qWarning("portal Registry.Register 失败: %s", qPrintable(reply.errorMessage()));
            return;
        }
        createSession();
    }

    void createSession() {
        cur_ = kCreate;
        const QString token = QStringLiteral("sess_%1")
                                  .arg(QRandomGenerator::global()->generate(), 8, 16, QLatin1Char('0'));
        const QString handle = requestPath(QDBusConnection::sessionBus().baseService(), token);
        if (!QDBusConnection::sessionBus().connect(
                QString::fromLatin1(kService), handle, QString::fromLatin1(kReqIface),
                QStringLiteral("Response"), this, SLOT(onResponse(uint, QVariantMap)))) {
            qWarning("portal CreateSession connect 失败");
            return;
        }
        QVariantMap opts;
        opts.insert(QStringLiteral("handle_token"), token);
        opts.insert(QStringLiteral("session_handle_token"),
                    QStringLiteral("sh_%1")
                        .arg(QRandomGenerator::global()->generate(), 8, 16, QLatin1Char('0')));
        QDBusMessage call = QDBusMessage::createMethodCall(
            QString::fromLatin1(kService), QString::fromLatin1(kPath),
            QString::fromLatin1(kIface), QStringLiteral("CreateSession"));
        call.setArguments({ QVariant(opts) });
        QDBusMessage reply = QDBusConnection::sessionBus().call(call, QDBus::BlockWithGui, 10000);
        if (reply.type() == QDBusMessage::ErrorMessage) {
            qWarning("CreateSession 失败: %s", qPrintable(reply.errorMessage()));
            return;
        }
    }

    void bindShortcuts() {
        cur_ = kBind;
        QList<ShortcutEntry> scs;
        if (!triggerImg_.isEmpty()) {
            scs << ShortcutEntry(
                QStringLiteral("img"),
                QVariantMap{{QStringLiteral("description"), QStringLiteral("截图并复制图片")},
                            {QStringLiteral("preferred_trigger"), triggerImg_}});
        }
        if (!triggerOcr_.isEmpty()) {
            scs << ShortcutEntry(
                QStringLiteral("ocr"),
                QVariantMap{{QStringLiteral("description"), QStringLiteral("截图并 OCR")},
                            {QStringLiteral("preferred_trigger"), triggerOcr_}});
        }
        QVariantMap opts;
        opts.insert(QStringLiteral("handle_token"),
                    QStringLiteral("bind_%1")
                        .arg(QRandomGenerator::global()->generate(), 8, 16, QLatin1Char('0')));
        QDBusMessage call = QDBusMessage::createMethodCall(
            QString::fromLatin1(kService), QString::fromLatin1(kPath),
            QString::fromLatin1(kIface), QStringLiteral("BindShortcuts"));
        call.setArguments({ QVariant::fromValue(QDBusObjectPath(sessionHandle_)),
                            QVariant::fromValue(scs), QVariant(QString()), QVariant(opts) });
        QDBusMessage reply = QDBusConnection::sessionBus().call(call, QDBus::BlockWithGui, 10000);
        if (reply.type() == QDBusMessage::ErrorMessage) {
            qWarning("BindShortcuts 失败: %s", qPrintable(reply.errorMessage()));
            return;
        }
        // portal 同步返回实际 request_handle，订阅它收 Response（勿用自拼路径）
        if (!reply.arguments().isEmpty()) {
            const QString actual = reply.arguments().first().value<QDBusObjectPath>().path();
            if (!actual.isEmpty()) {
                QDBusConnection::sessionBus().connect(
                    QString::fromLatin1(kService), actual, QString::fromLatin1(kReqIface),
                    QStringLiteral("Response"), this, SLOT(onResponse(uint, QVariantMap)));
            }
        }
    }

    std::function<void()> onImgPress_, onOcrPress_;
    QString triggerImg_, triggerOcr_;
    QString sessionHandle_;
    enum Step { kCreate, kBind };
    Step cur_ = kCreate;
    bool ok_ = false;
    bool done_ = false;
};

}  // namespace

std::unique_ptr<Hotkey> makeWaylandHotkeys(const std::string& triggerImg,
                                           const std::string& triggerOcr,
                                           std::function<void()> onImgPress,
                                           std::function<void()> onOcrPress) {
    return std::make_unique<GlobalShortcutsBackend>(triggerImg, triggerOcr,
                                                    std::move(onImgPress), std::move(onOcrPress));
}

#include "globalshortcut.moc"