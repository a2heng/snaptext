#include <QApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QProcess>
#include <QTimer>

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cstdio>
#include <cstring>
#include <string>

#include "app.h"
#include "config.h"
#include "hotkey.h"
#include "ipc.h"

namespace {

constexpr const char* kLockToken = "61714529-f194-4e05-9b24-8f16b52d699f_SnapText";

QString expandHome(const QString& p) {
    if (p.startsWith(QLatin1String("~/"))) return QDir::homePath() + p.mid(1);
    return p;
}

bool pidAlive(int pid) {
    if (pid <= 0) return false;
    return ::kill(pid, 0) == 0 || errno == EPERM;
}

int acquireSingleInstance(const QString& lockPath) {
    // flock 排它锁 + 固定 token + PID 存活校验（见 AGENTS.md 单实例锁）
    int fd = ::open(lockPath.toLocal8Bit().constData(),
                    O_CREAT | O_RDWR, 0644);
    if (fd < 0) return -1;
    if (::flock(fd, LOCK_EX | LOCK_NB) != 0) {
        // 锁被占：校验旧 token 里的 PID 是否还活着
        char buf[128];
        ssize_t n = ::read(fd, buf, sizeof(buf) - 1);
        buf[n > 0 ? n : 0] = 0;
        int oldPid = 0;
        if (std::sscanf(buf, "%*s %d", &oldPid) >= 1 && pidAlive(oldPid)) {
            ::close(fd);
            return 1;  // 已有存活实例
        }
        // 旧实例已死：重新拿锁
        ::flock(fd, LOCK_EX);
    }
    ::ftruncate(fd, 0);
    char line[128];
    std::snprintf(line, sizeof(line), "%s %d\n", kLockToken, (int)::getpid());
    if (::write(fd, line, std::strlen(line)) < 0) {
        /* 忽略 */
    }
    ::fsync(fd);
    return 0;
}

QString findConfigFile(const QString& exeDir) {
    for (const QString& cand : {exeDir + QLatin1String("/config.conf"),
                                QDir::currentPath() + QLatin1String("/config.conf")}) {
        if (QFileInfo::exists(cand)) return cand;
    }
    return QString();
}

QString findModelsDir(const QString& exeDir) {
    const QByteArray env = qgetenv("SNAPTEXT_MODELS_DIR");
    if (!env.isEmpty() && QDir(QString::fromLocal8Bit(env)).exists()) {
        return QString::fromLocal8Bit(env);
    }
    for (const QString& cand : {exeDir + QLatin1String("/models"),
                                QDir::currentPath() + QLatin1String("/models")}) {
        if (QDir(cand).exists()) return cand;
    }
    return QString();
}

void registerGnomeShortcuts(const QString& exePath) {
    if (!(session::type() == session::Wayland && session::isGnome())) return;
    // GNOME Wayland 无全局热键 API，自动注册 gsettings 自定义快捷键绑 --ocr/--img
    // 尽力而为：任何一步失败即整体放弃
    const QString schema = QStringLiteral("org.gnome.settings-daemon.plugins.media-keys");
    const QString base = QStringLiteral("/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings");
    const QString cmd = exePath;
    auto gset = [&](const QStringList& args) {
        QProcess p;
        p.start(QStringLiteral("gsettings"), args);
        p.waitForFinished(8000);
    };
    gset({QStringLiteral("set"), schema, QStringLiteral("custom-keybindings"),
          QStringLiteral("['%1/snaptext-ocr/', '%1/snaptext-img/']").arg(base)});
    const std::string ocrSpec = cfg::str("hotkey_ocr");
    const std::string imgSpec = cfg::str("hotkey_image");
    gset({QStringLiteral("set"), schema,
          QStringLiteral("custom-keybindings/snaptext-ocr/"),
          QStringLiteral("name"), QStringLiteral("snaptext-ocr")});
    gset({QStringLiteral("set"), schema,
          QStringLiteral("custom-keybindings/snaptext-ocr/"),
          QStringLiteral("command"), cmd + QLatin1String(" --ocr")});
    gset({QStringLiteral("set"), schema,
          QStringLiteral("custom-keybindings/snaptext-ocr/"),
          QStringLiteral("binding"), QString::fromStdString(cfg::hotkeyDisplay(ocrSpec))});
    gset({QStringLiteral("set"), schema,
          QStringLiteral("custom-keybindings/snaptext-img/"),
          QStringLiteral("name"), QStringLiteral("snaptext-img")});
    gset({QStringLiteral("set"), schema,
          QStringLiteral("custom-keybindings/snaptext-img/"),
          QStringLiteral("command"), cmd + QLatin1String(" --img")});
    gset({QStringLiteral("set"), schema,
          QStringLiteral("custom-keybindings/snaptext-img/"),
          QStringLiteral("binding"), QString::fromStdString(cfg::hotkeyDisplay(imgSpec))});
}

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    QCoreApplication::setApplicationName(QStringLiteral("snaptext"));
    QCoreApplication::setOrganizationName(QStringLiteral("snaptext"));
    app.setQuitOnLastWindowClosed(false);  // 托盘模式，选区关闭不误退

    // 命令行参数：--ocr / --img 触发一次
    const QStringList args = app.arguments();
    const bool doOcr = args.contains(QStringLiteral("--ocr"));
    const bool doImg = args.contains(QStringLiteral("--img"));

    const QString exeDir = QCoreApplication::applicationDirPath();
    cfg::load(findConfigFile(exeDir).toStdString());

    const QString lockPath = expandHome(QString::fromStdString(cfg::str("lock_path")));
    const QString sockPath = lockPath;
    QString sock = sockPath;
    sock.replace(QStringLiteral(".lock"), QStringLiteral(".sock"));

    // 已有常驻实例 → 把命令派发给它，本进程退出
    if (doOcr || doImg) {
        const QString cmd = doOcr ? QStringLiteral("ocr") : QStringLiteral("img");
        if (ipcSend(sock, cmd)) return 0;
    }

    const int lockRet = acquireSingleInstance(lockPath);
    if (lockRet == 1) {
        // 已有存活实例（IPC 恰未连上，如刚启动）：重试一次后退出
        if (doOcr || doImg) {
            const QString cmd = doOcr ? QStringLiteral("ocr") : QStringLiteral("img");
            ipcSend(sock, cmd);
        }
        return 1;
    }
    if (lockRet < 0) {
        return 1;
    }

    const QString modelsDir = findModelsDir(exeDir);
    if (modelsDir.isEmpty()) {
        std::fprintf(stderr, "未找到 models/ 目录\n");
        return 1;
    }

    App appObj;
    appObj.init(modelsDir);

    // GNOME Wayland：自动注册 gsettings 快捷键（尽力而为）
    registerGnomeShortcuts(QCoreApplication::applicationFilePath());

    if (doOcr) appObj.trigger(App::Mode::Ocr);
    else if (doImg) appObj.trigger(App::Mode::Image);

    return app.exec();
}