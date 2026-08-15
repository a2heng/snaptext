#include "ipc.h"

#include <QLocalServer>
#include <QLocalSocket>
#include <QFile>

IpcServer::IpcServer(QString socketPath, QObject* parent)
    : QObject(parent), socketPath_(std::move(socketPath)) {
    server_ = new QLocalServer(this);
    // 上次残留的 socket 文件（无常驻崩溃留下）先清掉
    QFile::remove(socketPath_);
    if (!server_->listen(socketPath_)) {
        return;
    }
    QObject::connect(server_, &QLocalServer::newConnection,
                     this, &IpcServer::onNewConnection);
}

IpcServer::~IpcServer() {
    QFile::remove(socketPath_);
}

bool IpcServer::isListening() const {
    return server_ && server_->isListening();
}

void IpcServer::onNewConnection() {
    while (QLocalSocket* sock = server_->nextPendingConnection()) {
        QObject::connect(sock, &QLocalSocket::readyRead, this, [this, sock]() {
            const QByteArray data = sock->readAll();
            const QString cmd = QString::fromUtf8(data).trimmed();
            if (!cmd.isEmpty()) {
                // 信号在 GUI 线程（本对象所在线程）发出
                emit commandReceived(cmd);
            }
        });
        QObject::connect(sock, &QLocalSocket::disconnected, sock, &QObject::deleteLater);
    }
}

bool ipcSend(const QString& socketPath, const QString& cmd) {
    QLocalSocket sock;
    sock.connectToServer(socketPath);
    if (!sock.waitForConnected(500)) {
        return false;
    }
    sock.write(cmd.toUtf8() + "\n");
    sock.flush();
    sock.waitForBytesWritten(500);
    return true;
}