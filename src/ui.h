#pragma once
/** UI 模块：全屏抓图 + X11 拉框选区（对应旧 ui.py）。
 *
 * Wayland 下抓图/选区走 portal（见 portal.h），本模块仅在 X11 使用。
 */
#include <QObject>
#include <QRect>
#include <QPixmap>

class QPaintEvent;
class QMouseEvent;
class QKeyEvent;

QPixmap grabScreen();  // 主屏全屏（含系统面板），返回设备像素图

class Selector : public QObject {
    Q_OBJECT
public:
    explicit Selector(const QPixmap& pix, QObject* parent = nullptr);

    void show();
    void close();

signals:
    void selected(const QRect& rect);  // 松手且选区 >= minSize
    void cancelled();

private:
    QRect selRect() const;

    class Impl;
    Impl* impl_ = nullptr;
};
