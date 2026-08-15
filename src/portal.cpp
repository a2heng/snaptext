#include "portal.h"

#include <QRandomGenerator>
#include <QUrl>
#include <QDBusConnection>
#include <QDBusMessage>

namespace {

constexpr const char* kPortalService = "org.freedesktop.portal.Desktop";
constexpr const char* kScreenshotPath = "/org/freedesktop/portal/desktop";
constexpr const char* kScreenshotIface = "org.freedesktop.portal.Screenshot";
constexpr const char* kRequestIface = "org.freedesktop.portal.Request";

}  // namespace

PortalSession::PortalSession(std::function<void(QString, bool)> cb, QString handle)
    : cb_(std::move(cb)), handle_(std::move(handle)) {}

void PortalSession::start() {
    token_ = handle_.section(QLatin1Char('/'), -1);
    // 订阅 Request 对象的 Response 信号（结果经此回传）。
    // 注意：**不能传显式 D-Bus 签名 "uav"**——QtDBus 带 signature 的 connect 重载
    // 注册的 match rule 与实际信号对不上，Response 信号永远到不了槽（connect 却
    // 返回成功，静默失效）。用不带签名的重载即可正常触发。
    if (!QDBusConnection::sessionBus().connect(
            QString::fromLatin1(kPortalService), handle_,
            QString::fromLatin1(kRequestIface), QStringLiteral("Response"),
            this, SLOT(onResponse(uint, QVariantMap)))) {
        qWarning("portal connect 失败 %s", qPrintable(handle_));
        finish(QString(), true);
        return;
    }
    // 非交互：静默抓全屏，返回临时文件；不传 interactive=true（合成器对话框/选区
    // 会因桌面而异且无统一区域模式，选区由应用侧自绘完成）
    QDBusMessage call = QDBusMessage::createMethodCall(
        QString::fromLatin1(kPortalService), QString::fromLatin1(kScreenshotPath),
        QString::fromLatin1(kScreenshotIface), QStringLiteral("Screenshot"));
    QVariantMap opts;
    opts.insert(QStringLiteral("modal"), false);
    opts.insert(QStringLiteral("background"), true);  // 后台应用（热键触发）也可抓图
    opts.insert(QStringLiteral("handle_token"), token_);
    QList<QVariant> args;
    args << QVariant(QString())  // parent_window：无 Qt 主窗，留空
         << QVariant(opts);
    call.setArguments(args);
    QDBusMessage reply = QDBusConnection::sessionBus().call(call, QDBus::BlockWithGui, 10000);
    if (reply.type() == QDBusMessage::ErrorMessage) {
        finish(QString(), true);
        return;
    }
}

void PortalSession::onResponse(uint code, const QVariantMap& results) {
    if (done_) return;
    if (code == 0) {
        QVariant uri = results.value(QStringLiteral("uri"));
        if (!uri.isValid()) {
            finish(QString(), false);  // 缺 uri 属后端错误，非用户取消
            return;
        }
        finish(QUrl::fromUserInput(uri.toString()).toLocalFile(), false);
        return;
    }
    // 1=用户取消 → cancelled=true（调用方静默）；2=其它错误 → cancelled=false（调用方提示）
    finish(QString(), code == 1);
}

void PortalSession::finish(const QString& path, bool cancelled) {
    if (done_) return;
    done_ = true;
    if (cb_) cb_(path, cancelled);
    cb_ = nullptr;
    QDBusConnection::sessionBus().disconnect(
        QString::fromLatin1(kPortalService), handle_,
        QString::fromLatin1(kRequestIface), QStringLiteral("Response"),
        QStringLiteral("uav"),
        this, SLOT(onResponse(uint, QVariantMap)));
    deleteLater();
}

void portalScreenshotFullscreen(QObject* ctx, std::function<void(QString, bool)> cb) {
    // Request 路径 = /org/freedesktop/portal/desktop/request/{bus名}/handle_token。
    // bus 唯一名 :1.42 → 1_42：portal 端构造路径时「去掉前导 ':'」再替换其余
    // ':'、'.' 为 '_'（带下划线的 _1_42 与 portal 实际发出的信号路径不匹配，
    // 会导致 Response 信号永远到不了槽，connect 却返回成功）
    QString sender = QDBusConnection::sessionBus().baseService();
    sender.remove(0, 1);  // 去掉前导 ':'
    sender.replace(QLatin1Char(':'), QLatin1Char('_'))
          .replace(QLatin1Char('.'), QLatin1Char('_'));
    quint32 rnd = QRandomGenerator::global()->generate();
    QString token = QStringLiteral("snaptext_%1").arg(rnd, 8, 16, QLatin1Char('0'));
    QString handle = QStringLiteral("/org/freedesktop/portal/desktop/request/%1/%2")
                         .arg(sender, token);

    auto* s = new PortalSession(std::move(cb), handle);
    s->setParent(ctx);
    s->start();
}