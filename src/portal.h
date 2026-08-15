#pragma once
/** Wayland 截图：经 xdg-desktop-portal 的 org.freedesktop.portal.Screenshot
 * （非交互模式，静默抓全屏返回临时 png 文件路径，无合成器对话框）。
 *
 * 这是 Linux 唯一跨合成器的抓图接口（KDE/GNOME/wlroots 各有后端实现）。
 * portal Screenshot 没有「区域」参数，选区由应用侧自绘（见 ui.h Selector）。
 *
 * 异步流程：构造 Request 句柄 → 订阅 Response 信号 → 调 Screenshot() →
 * 完成时触发 Response。回调统一在 Qt 事件循环线程执行。
 */
#include <QObject>
#include <QString>
#include <QVariantMap>

#include <functional>

class QDBusConnection;

class PortalSession : public QObject {
    Q_OBJECT
public:
    PortalSession(std::function<void(QString, bool)> cb, QString handle);

    void start();

private Q_SLOTS:
    void onResponse(uint code, const QVariantMap& results);

private:
    void finish(const QString& path, bool cancelled);

    std::function<void(QString, bool)> cb_;
    QString handle_;
    QString token_;
    bool done_ = false;
};

/** 异步发起一次非交互全屏截图。cb(path, cancelled) 在主线程回调：
 *  - cancelled=true：请求失败/被取消
 *  - 否则 path 是临时文件（QUrl file:// 转的本地路径）
 */
void portalScreenshotFullscreen(QObject* ctx, std::function<void(QString, bool)> cb);