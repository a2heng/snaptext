#include "hotkey.h"

// X11 头文件先包含，再清掉与 Qt 冲突的宏（Bool/Status/None/CursorShape 等）
#include <X11/Xlib.h>
#include <X11/keysym.h>

// 清掉与 Qt 头文件冲突的 X11 宏（Xlib.h/X.h 定义，Qt 的 qcoreevent/qnamespace 同名枚举）
#undef Bool
#undef Status
#undef None
#undef CursorShape
#undef Success
#undef TrueColor
#undef KeyPress
#undef KeyRelease
#undef FocusIn
#undef FocusOut
#undef Expose
#undef FontChange
#undef ClientMessage

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <thread>

namespace session {

Type type() {
    const char* t = std::getenv("XDG_SESSION_TYPE");
    if (t && std::strcmp(t, "wayland") == 0) {
        return Wayland;
    }
    const char* wl = std::getenv("WAYLAND_DISPLAY");
    const char* dis = std::getenv("DISPLAY");
    if (wl && wl[0] && (!dis || !dis[0])) {
        return Wayland;
    }
    return X11;
}

bool isGnome() {
    const char* d = std::getenv("XDG_CURRENT_DESKTOP");
    if (!d) return false;
    std::string s = d;
    return s.find("GNOME") != std::string::npos || s.find("Unity") != std::string::npos;
}

}  // namespace session

namespace {

class NoopHotkey : public Hotkey {
public:
    bool ok() const override { return false; }
    void release() override {}
};

// ── X11 后端（移植自旧 hotkey.py，坑见 AGENTS.md「Xlib 热键踩过的坑」）───────
class GlobalHotkeyX11 : public Hotkey {
public:
    GlobalHotkeyX11(const std::string& key, unsigned mods, std::function<void()> onPress)
        : onPress_(std::move(onPress)), mods_(mods), run_(true), armed_(true) {
        if (!XInitThreads()) return;
        d_ = XOpenDisplay(nullptr);
        if (!d_) return;
        KeySym ks = XStringToKeysym(key.c_str());
        keycode_ = XKeysymToKeycode(d_, ks);
        root_ = DefaultRootWindow(d_);
        ok_ = grabOk();
        if (!ok_) return;
        th_ = std::thread(&GlobalHotkeyX11::loop, this);
    }

    ~GlobalHotkeyX11() override {
        release();
        if (d_) {
            XCloseDisplay(d_);
            d_ = nullptr;
        }
    }

    bool ok() const override { return ok_; }

    void release() override {
        run_.store(false);
        if (th_.joinable()) {
            th_.join();
        }
        if (d_ && ok_) {
            for (unsigned m : lockVariants(mods_)) {
                XUngrabKey(d_, keycode_, m, root_);
            }
            XFlush(d_);
        }
        ok_ = false;
    }

private:
    static constexpr unsigned LockMask_ = 2;   // CapsLock
    static constexpr unsigned Mod2Mask_ = 16;  // NumLock
    static constexpr int KeyPress_ = 2;
    static constexpr int KeyRelease_ = 3;

    // XGrabKey 恒返回 1，注册成败经 error handler + XSync 判断（见 AGENTS.md）
    bool grabOk() {
        grabErr_.store(false);
        int (*oldErr)(Display*, XErrorEvent*) = XSetErrorHandler(&GlobalHotkeyX11::errHandler);
        XSync(d_, False);  // 先排空连接上旧的 pending 错误
        grabErr_.store(false);
        for (unsigned m : lockVariants(mods_)) {
            XGrabKey(d_, keycode_, m, root_, True, GrabModeAsync, GrabModeAsync);
        }
        XSync(d_, False);  // 同步等待 grab 结果
        XSetErrorHandler(oldErr);
        return !grabErr_.load();
    }

    static int errHandler(Display*, XErrorEvent*) {
        grabErr_.store(true);
        return 0;
    }

    static std::vector<unsigned> lockVariants(unsigned mods) {
        std::vector<unsigned> v{mods, mods | 2, mods | 16, mods | 18};
        std::sort(v.begin(), v.end());
        v.erase(std::unique(v.begin(), v.end()), v.end());
        return v;
    }

    void loop() {
        while (run_.load() && d_) {
            if (XPending(d_)) {
                XEvent ev;
                XNextEvent(d_, &ev);
                if (ev.xkey.keycode == keycode_) {
                    if (ev.type == KeyRelease_) {
                        // 只凭 keycode 重新武装，不查 state：先松 Alt 再松 X 时
                        // KeyRelease(X) 的 state 已无 Mod1，按 mods 过滤会永久失效
                        armed_.store(true);
                    } else if (ev.type == KeyPress_ && armed_.load()) {
                        // 只认指定 mods，忽略 NumLock/CapsLock
                        if ((ev.xkey.state & ~(LockMask_ | Mod2Mask_)) == mods_) {
                            armed_.store(false);  // 防抖：auto-repeat 只触发一次
                            onPress_();
                        }
                    }
                }
            } else {
                std::this_thread::sleep_for(std::chrono::milliseconds(20));
            }
        }
    }

    Display* d_ = nullptr;
    KeyCode keycode_ = 0;
    Window root_ = 0;
    std::thread th_;
    std::function<void()> onPress_;
    unsigned mods_ = 0;
    std::atomic<bool> run_;
    std::atomic<bool> armed_;
    bool ok_ = false;
    static std::atomic<bool> grabErr_;
};

std::atomic<bool> GlobalHotkeyX11::grabErr_{false};

}  // namespace

std::unique_ptr<Hotkey> makeHotkey(const std::string& key, unsigned mods,
                                   std::function<void()> onPress) {
    // Wayland：无统一全局热键协议（KDE/GNOME 均未实现 zwp_global_shortcuts_v1），
    // 一律 NoopHotkey。热键由合成器绑定 `snaptext --ocr/--img` 命令触发
    // （GNOME 由 gsettings 自动注册，其余桌面用户自绑）。
    if (session::type() == session::Wayland) {
        return std::make_unique<NoopHotkey>();
    }
    return std::make_unique<GlobalHotkeyX11>(key, mods, std::move(onPress));
}
