#pragma once
/** 全局热键后端：X11 XGrabKey，接口统一（ok()/release()）。
 *
 * X11：独立线程轮询 KeyPress，onPress 在轮询线程调用（调用方 marshal 到 GUI 线程）。
 * Wayland：无统一全局热键协议（KDE/GNOME 均未实现 zwp_global_shortcuts_v1），
 *   一律返回 NoopHotkey（ok=false）。热键由合成器绑定 `snaptext --ocr/--img`
 *   命令触发（GNOME 由 gsettings 自动注册，其余桌面用户自绑）。
 */
#include <functional>
#include <memory>
#include <string>

class Hotkey {
public:
    virtual ~Hotkey() = default;
    virtual bool ok() const = 0;
    virtual void release() = 0;
};

/** 按会话选后端；返回对象具备 ok()/release() 接口。 */
std::unique_ptr<Hotkey> makeHotkey(const std::string& key, unsigned mods,
                                   std::function<void()> onPress);

/** Wayland：xdg-desktop-portal GlobalShortcuts 全局热键（跨合成器标准接口）。
 *  一次会话绑定 img/ocr 两条快捷键（triggerX 为空则不绑）；任一触发时在 GUI
 *  线程回调对应 onPress。ok()=false 表示后端不可用（非 Wayland / portal 缺失 /
 *  用户拒绝授权），调用方回退到 CLI+IPC 触发。X11 会话也返回 NoopHotkey（
 *  走 XGrabKey 的 makeHotkey）。 */
std::unique_ptr<Hotkey> makeWaylandHotkeys(const std::string& triggerImg,
                                           const std::string& triggerOcr,
                                           std::function<void()> onImgPress,
                                           std::function<void()> onOcrPress);

// 会话/桌面检测（供 makeHotkey 与其它模块共用）
namespace session {
enum Type { X11, Wayland };
Type type();
bool isGnome();
}  // namespace session
