#include "tray.h"

#include <QAction>
#include <QApplication>
#include <QIcon>
#include <QMenu>
#include <QSystemTrayIcon>
#include <QTimer>

#include "config.h"

TrayIcon::TrayIcon(const QString& iconPath, const QString& hintText, QObject* parent)
    : QObject(parent) {
    tray_ = new QSystemTrayIcon(QIcon(iconPath), this);
    tray_->setToolTip(hintText);

    QMenu* menu = new QMenu();
    QAction* quit = menu->addAction(QStringLiteral("退出"));
    QObject::connect(quit, &QAction::triggered, this, [this]() {
        emit quitRequested();
    });
    tray_->setContextMenu(menu);

    // 左键提示热键（非阻塞）
    QObject::connect(tray_, &QSystemTrayIcon::activated, this,
                     [this, hintText](QSystemTrayIcon::ActivationReason reason) {
                         if (reason == QSystemTrayIcon::Trigger ||
                             reason == QSystemTrayIcon::DoubleClick) {
                             notify(QStringLiteral("拾字 SnapText"), hintText);
                         }
                     });
    tray_->show();
}

void TrayIcon::notify(const QString& title, const QString& msg) {
    if (!tray_) return;
    // QSystemTrayIcon::showMessage 本身非阻塞
    tray_->showMessage(title, msg, QSystemTrayIcon::Information,
                       cfg::int_("notify_ms") > 0 ? cfg::int_("notify_ms") : 2000);
}