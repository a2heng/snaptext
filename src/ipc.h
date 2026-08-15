#pragma once
/** IPC：单实例 unix socket 服务器 + 客户端（对应旧 _IpcServer/CLI 触发）。
 *
 * 常驻实例监听 ~/.snaptext.sock，收到 "ocr"/"img" 经信号 marshal 到 GUI 线程；
 * 无常驻时客户端 connect 失败即返回 false，调用方自行启动新实例。
 */
#include <QObject>
#include <QString>

class QLocalServer;

class IpcServer : public QObject {
    Q_OBJECT
public:
    explicit IpcServer(QString socketPath, QObject* parent = nullptr);
    ~IpcServer() override;

    bool isListening() const;

signals:
    // 收到一行命令（"ocr" / "img"），在 GUI 线程发出
    void commandReceived(const QString& cmd);

private:
    void onNewConnection();

    QLocalServer* server_ = nullptr;
    QString socketPath_;
};

/** 向常驻实例发一条命令；无实例监听返回 false。 */
bool ipcSend(const QString& socketPath, const QString& cmd);