#!/usr/bin/env python3
"""拾字 SnapText —— Wayland 全局热键后端（KDE Plasma KGlobalAccel）。

Wayland 没有统一的全局快捷键协议，各桌面只有自己的机制：
  - KDE Plasma Wayland：KWin 接管 `org.kde.kglobalaccel` dbus，是唯一有成熟
    第三方全局热键 dbus 接口的桌面。本项目在此会话下用它。
  - GNOME / 其它 Wayland：无第三方全局热键 API，本模块会初始化但 ok=False，
    由入口侧降级（GNOME 用 gsettings 自定义快捷键绑命令，见 snaptext.py）。

实现：
  - 注册：`org.kde.kglobalaccel.setShortcutKeys(as, a(ai), u)`。PySide6 的
    QtDBus 对 `a(ai)`/`uint` 这类 typed 参数封送有已知限制（PYSIDE-1904，
    发出去会变成 `av`/`i`），故**发送**改用系统自带 `gdbus` 子进程（glib 工具，
    KDE 桌面必然存在；原生支持 a(ai)/uint，零新增依赖）。
  - 接收：`org.kde.kglobalaccel.Component.globalShortcutPressed` 信号用
    QtDBus 的 QDBusConnection.connect 订阅（解封方向 PySide6 可靠支持）。
    on_press 在 Qt 事件循环线程（dbus 回调）被调用，无需再 marshal。

接口与 hotkey.py 的 GlobalHotkey 对齐：`__init__(key, mods, on_press)`、
`.ok`、`.release()`。
"""
import shutil
import subprocess

from PySide6.QtCore import QObject, Qt
from PySide6.QtDBus import QDBusConnection

SERVICE = "org.kde.kglobalaccel"
PATH = "/kglobalaccel"
COMPONENT = "snaptext"
COMPONENT_FRIENDLY = "拾字 SnapText"
_IFACE_MAIN = "org.kde.KGlobalAccel"
_IFACE_COMP = "org.kde.kglobalaccel.Component"

# X11 modifier mask → Qt::KeyboardModifier 数值（QKeySequence 编码 = key | mod，bits≥25）。
# 直接写死数值：PySide6 的 Qt.KeyboardModifier 是枚举/Flag，int() 转不了。
_MOD_X11_TO_QT = {
    1: 0x02000000,     # Shift
    4: 0x04000000,     # Ctrl
    8: 0x08000000,     # Alt
    64: 0x10000000,    # Super/Meta
}

_KEY_NAME_ATTR = {
    "space": "Key_Space", "tab": "Key_Tab", "return": "Key_Return", "enter": "Key_Enter",
    "escape": "Key_Escape", "backspace": "Key_Backspace", "delete": "Key_Delete",
    "insert": "Key_Insert", "home": "Key_Home", "end": "Key_End",
    "pageup": "Key_PageUp", "pagedown": "Key_PageDown",
    "up": "Key_Up", "down": "Key_Down", "left": "Key_Left", "right": "Key_Right",
    "pause": "Key_Pause", "print": "Key_Print", "scrolllock": "Key_ScrollLock",
}


def _qt_key(name: str) -> int:
    """X11 keysym 名 → Qt::Key 数值；无法识别返回 0。"""
    n = name.lower()
    if len(n) == 1 and n.isalnum():
        return ord(n.upper()) if n.isalpha() else ord(n)
    attr = _KEY_NAME_ATTR.get(n)
    if attr:
        return int(getattr(Qt, attr))
    if len(n) > 1 and n[0] == "f" and n[1:].isdigit():
        return int(getattr(Qt, f"Key_F{n[1:]}"))
    return 0


def _seqint(key: str, mods: int) -> int:
    """X11 keysym + X11 modifier mask → Qt QKeySequence 编码 int。"""
    v = _qt_key(key)
    if not v:
        return 0
    for mask, qmod in _MOD_X11_TO_QT.items():
        if mods & mask:
            v |= qmod
    return v


def _gdbus(*args, timeout=8):
    """调 gdbus，失败/非零返回 None。"""
    g = shutil.which("gdbus")
    if not g:
        return None
    try:
        return subprocess.run([g, *args], capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


class WaylandHotkey(QObject):
    """KDE Plasma Wayland 全局热键（org.kde.kglobalaccel）。"""

    def __init__(self, key: str, mods: int, on_press) -> None:
        super().__init__(None)
        self._on_press = on_press
        self._action = None
        self._ok = False
        self._comp_path = "/component/" + COMPONENT
        if not QDBusConnection.sessionBus().isConnected():
            return
        seqint = _seqint(key, mods)
        if not seqint:
            return
        self._action = f"action_{key}_{mods}"
        self._action_id = [COMPONENT, self._action, COMPONENT_FRIENDLY, f"{COMPONENT} {key}"]
        if not self._register(seqint):
            self._action = None
            return
        # 订阅组件 dbus 对象上的按键信号（接收方向 QtDBus 可靠）
        if not QDBusConnection.sessionBus().connect(
            SERVICE, self._comp_path, _IFACE_COMP,
            "globalShortcutPressed", self._on_shortcut,
        ):
            self._release_registration()
            self._action = None
            return
        self._ok = True

    def _register(self, seqint: int) -> bool:
        # doRegister：让 kglobalacceld 创建组件并登记 action
        r = _gdbus("call", "--session", "--dest", SERVICE, "--object-path", PATH,
                   "--method", f"{_IFACE_MAIN}.doRegister",
                   _gdbus_strlist(self._action_id))
        if r is None or r.returncode != 0:
            return False
        # setShortcutKeys(actionId, [seq,0,0,0], 4)：4=SetPresent，立即激活
        r = _gdbus("call", "--session", "--dest", SERVICE, "--object-path", PATH,
                   "--method", f"{_IFACE_MAIN}.setShortcutKeys",
                   _gdbus_strlist(self._action_id),
                   f"[([{seqint}, 0, 0, 0],)]",
                   "4")
        return r is not None and r.returncode == 0

    def _release_registration(self):
        if self._action:
            _gdbus("call", "--session", "--dest", SERVICE, "--object-path", PATH,
                   "--method", f"{_IFACE_MAIN}.unRegister",
                   _gdbus_strlist([COMPONENT, self._action, "", ""]))

    @property
    def ok(self) -> bool:
        return self._ok

    def _on_shortcut(self, component, action, timestamp):
        if component == COMPONENT and action == self._action:
            self._on_press()

    def release(self) -> None:
        """注销热键并断开信号。可重复安全调用。"""
        if self._ok:
            try:
                QDBusConnection.sessionBus().disconnect(
                    SERVICE, self._comp_path, _IFACE_COMP,
                    "globalShortcutPressed", self._on_shortcut)
            except Exception:
                pass
            self._release_registration()
        self._ok = False


def _gdbus_strlist(strings) -> str:
    """['a','b'] → gdbus 可解析的 as 字面量。"""
    return "[" + ", ".join(repr(s) for s in strings) + "]"