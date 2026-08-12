#!/usr/bin/env python3
"""拾字 SnapText —— 独立全局热键模块（X11 XGrabKey，Qt-free）

仅用标准库 + ctypes 直调 libX11，不依赖 PySide6/Qt。
X11 专属：Wayland 下不工作。

用法：
    def on_press():
        pass

    hk = GlobalHotkey("x", 8, on_press)   # Alt+X（Alt = Mod1Mask = 8）
    if hk.ok:
        ...
    hk.release()

注意：on_press 会在 X 轮询线程里被调用（不是主线程），
调用方需要自行 marshal 到 GUI 线程（如 Qt 的 QTimer.singleShot 或
signal 的 queued connection）。
"""
import ctypes
import ctypes.util
import threading
import time


class XKeyEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("root", ctypes.c_ulong),
        ("subwindow", ctypes.c_ulong), ("time", ctypes.c_ulong),
        ("x", ctypes.c_int), ("y", ctypes.c_int), ("x_root", ctypes.c_int), ("y_root", ctypes.c_int),
        ("state", ctypes.c_uint), ("keycode", ctypes.c_uint), ("same_screen", ctypes.c_int),
    ]


class XEventBuf(ctypes.Structure):
    """union XEvent 占位（本机 sizeof(XEvent)=192 > XKeyEvent=96）。

    XNextEvent 按整个 union 拷贝 192 字节；若只给它 XKeyEvent（96B）
    的缓冲，会越界写坏相邻堆块（表现为退出 GC 时 free(): invalid size 崩溃）。
    字段从缓冲起始处读即可（XKeyEvent 是 union 的第一个成员）。
    """

    _fields_ = [
        ("xkey", XKeyEvent),
        ("_pad", ctypes.c_ubyte * (192 - ctypes.sizeof(XKeyEvent))),
    ]


_LIBX = ctypes.CDLL(ctypes.util.find_library("X11"))
# 轮询线程与主线程并发访问同一个 Display，必须先启用 Xlib 内部线程安全，
# 否则 Xlib 内部状态被并发读写、堆损坏（表现为退出 GC 时 free(): invalid size 崩溃）
_LIBX.XInitThreads.restype = ctypes.c_int
_LIBX.XInitThreads()
_ERRH = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


def _null_errh(*a):
    return 0


# 必须持有引用：Xlib 注册的是回调 trampoline，若 Python 侧把它 GC 掉，
# X 后续触发错误时就会踩悬空指针（解释器收尾 GC 时崩）。
_SILENT_ERRH = _ERRH(_null_errh)
_LIBX.XSetErrorHandler(_SILENT_ERRH)
_LIBX.XOpenDisplay.restype = ctypes.c_void_p
_LIBX.XOpenDisplay.argtypes = [ctypes.c_char_p]
_LIBX.XStringToKeysym.restype = ctypes.c_ulong
_LIBX.XStringToKeysym.argtypes = [ctypes.c_char_p]
_LIBX.XKeysymToKeycode.restype = ctypes.c_uint
_LIBX.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_LIBX.XDefaultRootWindow.restype = ctypes.c_ulong
_LIBX.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
_LIBX.XGrabKey.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong,
                           ctypes.c_int, ctypes.c_int, ctypes.c_int]
_LIBX.XUngrabKey.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong]
_LIBX.XPending.argtypes = [ctypes.c_void_p]
_LIBX.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(XEventBuf)]
_LIBX.XFlush.argtypes = [ctypes.c_void_p]
_LIBX.XFlush.restype = ctypes.c_int
_LIBX.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
_LIBX.XSync.restype = ctypes.c_int


def _x_grab_ok(d, keycode, mods, root) -> bool:
    """XGrabKey 恒返回 1，无法当状态码用；改走 error handler 同步判断。

    Xlib 的 XGrabKey 是异步请求，成功/失败（BadAccess 等）经 X error
    handler 回报。这里临时换 handler → XGrabKey → XSync 同步排空错误，
    没收到错误即视为注册成功。
    """
    err_flag = []

    @ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    def _err(display, ev):
        err_flag.append(True)
        return 0

    old = _LIBX.XSetErrorHandler(_err)
    try:
        _LIBX.XSync(d, 0)      # 先排空连接上旧的 pending 错误
        del err_flag[:]
        for m in _lock_variants(mods):
            _LIBX.XGrabKey(d, keycode, m, root, True, 1, 1)
        _LIBX.XSync(d, 0)      # 同步等待 grab 结果
        return not err_flag
    finally:
        _LIBX.XSetErrorHandler(old)


def _lock_variants(mods: int) -> list:
    """XGrabKey 的被动 grab 只精确匹配注册的 modifiers 组合。

    坑（本机实测）：NumLock/CapsLock 开启时，按键事件的 state 会带上
    MOD2/LOCK 位。X server 默认不会自动为被动 grab 注册 lock 变体——
    只注册 mods 本身的话，NumLock 开时按 Alt+X（state=0x18）永远匹配不上
    mods=8（Alt）的 grab，热键静默失效。因此需显式注册全部 4 个 lock
    变体：mods、mods|CapsLock、mods|NumLock、mods|CapsLock|NumLock。
    事件侧 _loop 里用 `state & ~(LOCK|MOD2) == mods` 过滤，忽略 lock 位，
    兼容任意 CapsLock/NumLock 状态。
    """
    return sorted({mods, mods | 2, mods | 16, mods | 18})


class GlobalHotkey:
    """X11 全局热键（XGrabKey），注册后独立线程轮询 KeyPress 事件。

    on_press 无参回调，在 X 轮询线程里被调用（不是主线程），
    调用方需自行 marshal 到 GUI 线程。
    """

    KeyPress = 2
    KeyRelease = 3
    LOCK = 2    # CapsLock
    MOD2 = 16   # NumLock

    def __init__(self, key: str, mods: int, on_press) -> None:
        self._key = key
        self._mods = mods
        self._on_press = on_press
        self._run = True
        self._armed = True
        self._d = _LIBX.XOpenDisplay(None)
        self._ok = bool(self._d)
        self._keycode = 0
        self._root = 0
        self._th = None
        if not self._ok:
            return
        ks = _LIBX.XStringToKeysym(key.encode())
        self._keycode = _LIBX.XKeysymToKeycode(self._d, ks)
        root = _LIBX.XDefaultRootWindow(self._d)
        self._root = root
        self._ok = _x_grab_ok(self._d, self._keycode, mods, root)
        if not self._ok:
            return
        self._th = threading.Thread(target=self._loop, daemon=True)
        self._th.start()

    @property
    def ok(self) -> bool:
        return self._ok

    def _loop(self):
        while self._run and self._d:
            if _LIBX.XPending(self._d):
                ev = XEventBuf()
                _LIBX.XNextEvent(self._d, ctypes.byref(ev))
                if ev.xkey.keycode == self._keycode:
                    if ev.xkey.type == self.KeyRelease:
                        # 只凭 keycode 重新武装，不检查 state：若先松 Alt 再松 X，
                        # KeyRelease(X) 到达时 Alt 已释放（state=0），按 mods 过滤
                        # 会永远 re-arm 失败，热键只触发一次就永久失效
                        self._armed = True
                    elif ev.xkey.type == self.KeyPress and self._armed:
                        # 只认"指定 mods"，忽略 NumLock/CapsLock 状态
                        if (ev.xkey.state & ~(self.LOCK | self.MOD2)) == self._mods:
                            # 防抖：按住时 X11 auto-repeat 会连续发 KeyPress，
                            # 一次按键只触发一次，直到该键释放才重新 arm
                            self._armed = False
                            self._on_press()
                del ev  # 避免帧残留事件缓冲，杜绝收尾 GC 时其 dealloc 崩溃
            else:
                time.sleep(0.02)

    def release(self) -> None:
        """注销热键并停止轮询线程。可重复安全调用。"""
        self._run = False
        if self._th is not None:
            # 必须等线程退出，否则解释器关停时 daemon 线程访问已清理的
            # 模块全局（_LIBX/self._d）会段错误
            self._th.join(timeout=1.0)
            self._th = None
        if self._d:
            for m in _lock_variants(self._mods):
                _LIBX.XUngrabKey(self._d, self._keycode, m, self._root)
            _LIBX.XFlush(self._d)
