#include "ui.h"

#include <QApplication>
#include <QColor>
#include <QGuiApplication>
#include <QKeyEvent>
#include <QMouseEvent>
#include <QPainter>
#include <QScreen>
#include <QWidget>
#include <QtGlobal>

#include "config.h"
#include "hotkey.h"

QPixmap grabScreen() {
    return QGuiApplication::primaryScreen()->grabWindow(0);
}

class Selector::Impl : public QWidget {
public:
    Impl(Selector* owner, const QPixmap& pix)
        : QWidget(nullptr, selectorFlags()),
          owner_(owner),
          pix_(pix) {
        const QScreen* s = QGuiApplication::primaryScreen();
        setGeometry(s->geometry());
        setCursor(Qt::CrossCursor);
        setMouseTracking(true);
        setFocusPolicy(Qt::StrongFocus);
    }

    // X11：override-redirect 绕过 WM 盖住系统面板；Wayland：普通窗口即可
    // （无法绕过合成器，全屏窗口即覆盖主屏），X11BypassWindowManagerHint 在
    // Wayland 被忽略、Qt::Tool 可能被部分合成器特殊处理，故按平台区分
    static Qt::WindowFlags selectorFlags() {
        Qt::WindowFlags f = Qt::FramelessWindowHint | Qt::WindowStaysOnTopHint;
        if (session::type() == session::X11) {
            f |= Qt::X11BypassWindowManagerHint | Qt::Tool;
        }
        return f;
    }

protected:
    void paintEvent(QPaintEvent*) override {
        QPainter p(this);
        // 高分屏：pix 是设备像素，窗口/鼠标坐标是逻辑，source 矩形要乘 dpr
        const qreal dpr = pix_.devicePixelRatio();
        p.drawPixmap(rect(), pix_, QRectF(0, 0, pix_.width(), pix_.height()));
        const int alpha = cfg::int_("select_mask_alpha");
        p.fillRect(rect(), QColor(0, 0, 0, alpha));
        const QRect r = selRect();
        if (selecting_ && !r.isNull()) {
            p.drawPixmap(r, pix_,
                         QRectF(r.x() * dpr, r.y() * dpr,
                                r.width() * dpr, r.height() * dpr));
            p.setPen(QPen(QColor(QString::fromStdString(cfg::str("select_border_color"))), 2));
            p.drawRect(r);
            const QString label = QStringLiteral("%1 × %2")
                                      .arg(r.width()).arg(r.height());
            const QFontMetrics fm = p.fontMetrics();
            const int tw = fm.horizontalAdvance(label) + 8;
            const int th = fm.height();
            int tx = r.left();
            int ty = r.top() - th - 4;
            if (ty < 0) ty = r.bottom() + 4;
            p.fillRect(tx, ty, tw, th, QColor(0, 0, 0, 160));
            p.drawText(QRect(tx, ty, tw, th), Qt::AlignCenter, label);
        }
    }

    void mousePressEvent(QMouseEvent* ev) override {
        if (ev->button() == Qt::LeftButton) {
            start_ = ev->position().toPoint();
            cur_ = start_;
            selecting_ = true;
            update();
        }
    }

    void mouseMoveEvent(QMouseEvent* ev) override {
        if (selecting_) {
            cur_ = ev->position().toPoint();
            update();
        }
    }

    void mouseReleaseEvent(QMouseEvent* ev) override {
        if (ev->button() == Qt::LeftButton && selecting_) {
            selecting_ = false;
            const QRect r = selRect();
            const int min = cfg::int_("select_min_size");
            if (r.width() >= min && r.height() >= min) {
                emit owner_->selected(r);
            } else {
                emit owner_->cancelled();  // 太小视为取消
            }
            close();
        }
    }

    void keyPressEvent(QKeyEvent* ev) override {
        if (ev->key() == Qt::Key_Escape) {
            emit owner_->cancelled();
            close();
        }
    }

private:
    QRect selRect() const {
        return QRect(start_, cur_).normalized();
    }

    Selector* owner_;
    QPixmap pix_;
    QPoint start_;
    QPoint cur_;
    bool selecting_ = false;
};

Selector::Selector(const QPixmap& pix, QObject* parent)
    : QObject(parent) {
    impl_ = new Impl(this, pix);
}

void Selector::show() {
    impl_->showFullScreen();
    // Wayland 键盘焦点由合成器分配：主动抢焦点让 Esc 原生可用（X11 由入口侧
    // 临时全局热键兜底，这里无害）
    impl_->raise();
    impl_->activateWindow();
    impl_->setFocus();
}

void Selector::close() {
    impl_->close();
}
