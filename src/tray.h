#pragma once
/** 托盘：图标 + 右键退出 + 左键提示 + 非阻塞气泡（对应旧 tray.py）。 */
#include <QObject>
#include <QString>

class QSystemTrayIcon;

class TrayIcon : public QObject {
    Q_OBJECT
public:
    explicit TrayIcon(const QString& iconPath, const QString& hintText,
                      QObject* parent = nullptr);

    void notify(const QString& title, const QString& msg);  // 非阻塞气泡

signals:
    void quitRequested();

private:
    QSystemTrayIcon* tray_ = nullptr;
};
