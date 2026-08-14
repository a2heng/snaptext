#!/usr/bin/env python3
"""拾字 SnapText —— 极简屏幕 OCR（入口：接线 ocr/hotkey/ui/tray 独立模块）

全局快捷键（可改，见 config.py）：
  Alt+X（默认）截图 → 保存选区图片 → 复制图片到剪贴板
  Alt+C（默认）截图 → 保存图片 → OCR → 保存文本 → 复制文字到剪贴板

按会话选择热键后端：
  X11        hotkey.py  XGrabKey（全 X11 桌面通用）
  KDE Wayland hotkey_wayland.py  KGlobalAccel（唯一有第三方全局热键 dbus 的 wayland）
  GNOME/其它 Wayland  无原生全局热键 → 用 CLI 触发模式（--ocr/--img，经单实例
                     socket 派发给常驻进程）；GNOME 下自动注册 gsettings 自定义
                     快捷键绑命令，其它 wayland 由用户自行绑命令或手动触发。

命令行触发（任何桌面通用，GNOME 自定义快捷键绑这些）：
  snaptext --ocr    触发"截图+OCR+复制文字"（已有常驻则派发给它，否则本次启动并触发）
  snaptext --img    触发"截图+复制图片"

模块：
  ocr.py           图片 → 文本（纯 onnx，Qt-free，可命令行单跑）
  hotkey.py        全局热键 XGrabKey（X11，Qt-free）
  hotkey_wayland.py KDE Wayland 全局热键（KGlobalAccel，gdbus+QtDBus）
  ui.py            选区 Selector + grab_screen
  tray.py          常驻托盘图标

保存位置（可改，见 config.py）：
  ~/.snaptext/img/    图片  YYYYMMDD_HHMMSS_XXX.png
  ~/.snaptext/text/   文本  YYYYMMDD_HHMMSS_XXX.txt
"""
import os
import socket
import sys
import threading
import time

import _config as cfg

from PySide6.QtCore import QObject, QRect, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QWidget

from ocr import OcrEngine
from tray import TrayIcon
from ui import Selector, grab_screen

# ── 会话 / 桌面检测（决定热键后端）──
def _detect_session() -> str:
    t = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if t == "wayland":
        return "wayland"
    if t == "x11":
        return "x11"
    if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        return "wayland"
    return "x11"

_SESSION = _detect_session()
_DESKTOP = os.environ.get("XDG_CURRENT_DESKTOP", "")
_IS_KDE = "KDE" in _DESKTOP or "Plasma" in _DESKTOP
_IS_GNOME = "GNOME" in _DESKTOP or "Unity" in _DESKTOP

APP_NAME = "拾字 SnapText"
DATA_DIR = os.path.expanduser(cfg.get("DATA_DIR"))
IMG_DIR = os.path.join(DATA_DIR, "img")
TXT_DIR = os.path.join(DATA_DIR, "text")
# 锁文件放数据目录外：清空/删除 ~/.snaptext 不影响单例锁（flock 依赖文件持续存在）
LOCK_PATH = os.path.expanduser(cfg.get("LOCK_PATH"))

# (keysym, modifiers, mode) —— 来自 config.py，默认 alt+x / alt+c（现状）
MODES = [
    (*cfg.parse_hotkey(cfg.get("HOTKEY_IMAGE")), "img"),
    (*cfg.parse_hotkey(cfg.get("HOTKEY_OCR")), "ocr"),
]

_SAVE_IMAGES = cfg.get("SAVE_IMAGES")

# 外部触发用 unix socket（GNOME/其它 wayland 绑命令 → 派发给常驻进程）。
# 放数据目录旁（与锁文件一致，清空数据目录不影响）。
IPC_SOCK = os.path.expanduser(cfg.get("DATA_DIR")) + ".sock"


class _NoopHotkey:
    """占位热键：wayland 非 KDE 时无原生全局热键，保持接口一致（ok=False）。"""

    ok = False

    def release(self):
        pass


def _make_hotkey(key, mods, on_press):
    """按会话选热键后端；返回对象具备 `.ok` / `.release()` 接口。"""
    if _SESSION == "wayland":
        if _IS_KDE:
            from hotkey_wayland import WaylandHotkey
            return WaylandHotkey(key, mods, on_press)
        return _NoopHotkey()   # GNOME/其它 wayland：无原生热键，走 CLI/socket 触发
    from hotkey import GlobalHotkey   # x11（懒加载，纯 wayland 无 libX11 也不崩）
    return GlobalHotkey(key, mods, on_press)


def _ipc_send(path, cmd):
    """CLI 进程向常驻实例投递一条触发命令；失败返回 False。"""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(path)
        s.sendall(cmd.encode())
        s.close()
        return True
    except OSError:
        return False


class _IpcServer:
    """常驻实例监听的 unix socket 服务：外部 `snaptext --ocr/--img` 派发。"""

    def __init__(self, path, emit):
        self._path = path
        self._emit = emit
        self._sock = None
        self._run = True

    def start(self) -> bool:
        try:
            if os.path.exists(self._path):
                os.unlink(self._path)
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.bind(self._path)
            s.listen(4)
            self._sock = s
        except OSError:
            return False
        threading.Thread(target=self._loop, daemon=True).start()
        return True

    def _loop(self):
        while self._run and self._sock:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            try:
                data = conn.recv(64).decode("utf-8", "ignore").strip()
            except Exception:
                data = ""
            finally:
                conn.close()
            if data in ("ocr", "img"):
                self._emit(data)   # 后台线程 emit Signal → queued 到 GUI 线程

    def stop(self):
        self._run = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass


def _register_gnome_shortcuts():
    """GNOME（Wayland 无全局热键 API）自动注册 gsettings 自定义快捷键绑命令。

    走 `org.gnome.settings-daemon.plugins.media-keys` 的 custom-keybindings，
    命令是 `python3 <本文件> --ocr/--img`，经单实例 socket 派发。尽力而为：
    任何一步失败即整体放弃（用户可手动在 GNOME 设置里绑同样的命令）。
    """
    import shutil
    import subprocess

    if not _IS_GNOME:
        return False
    g = shutil.which("gsettings")
    if not g:
        return False
    schema = "org.gnome.settings-daemon.plugins.media-keys"
    base = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
    self_cmd = f"{sys.executable} {os.path.abspath(__file__)}"
    try:
        subprocess.run(
            [g, "set", schema, "custom-keybindings",
             f"['{base}/snaptext-ocr/', '{base}/snaptext-img/']"],
            capture_output=True, timeout=8)
        for name, suffix, binding in (
            ("snaptext-ocr", "ocr", cfg.hotkey_display(cfg.get("HOTKEY_OCR"))),
            ("snaptext-img", "img", cfg.hotkey_display(cfg.get("HOTKEY_IMAGE"))),
        ):
            for k, v in (("name", name), ("command", f"{self_cmd} --{suffix}"), ("binding", binding)):
                subprocess.run([g, "set", schema, f"custom-keybindings/{name}/", k, v],
                               capture_output=True, timeout=8)
        return True
    except Exception:
        return False


def _prewarm_engine():
    """后台预热 onnx 模型（模型加载/session 创建约 0.8s，首次 OCR 前做完）。

    只触发 OcrEngine 的惰性单例初始化（_get_engine 建全局唯一 RapidOCR），
    不跑真实推理；预热线程与后续 OCR 线程无共享可变状态，安全。
    """
    try:
        from ocr import _get_engine
        _get_engine()
    except Exception:
        pass  # 预热失败不致命，首次 OCR 时正常加载

_lock_fd = None

# 固定 UUID 唯一单例标识（随机生成一次后不再变）：
# 所有实例共用同一 token `<uuid>_SnapText`，配合 flock + PID 存活校验防多开。
SNAP_LOCK_TOKEN = "61714529-f194-4e05-9b24-8f16b52d699f_SnapText"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_single_instance() -> bool:
    """防多开，保证唯一单例（固定 UUID token + flock + PID 存活校验）。

    多实例会抢同一个 XGrabKey 导致热键随机失效。机制：
    - flock 排它锁：并发启动时只有一个能拿到。
    - 锁文件写入固定 token（`<uuid>_SnapText`）+ PID；若锁文件被删/重建
      （如清空数据目录）导致 flock 落到新 inode 上，仍能凭旧实例 PID
      存活判断拦截住。
    """
    global _lock_fd
    import fcntl

    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    # 拿到锁后：检查旧实例是否仍存活（处理锁文件被删后重建的场景）
    os.lseek(fd, 0, 0)
    raw = os.read(fd, 256).decode("ascii", errors="ignore").strip()
    if raw:
        try:
            old_pid = int(raw.split()[1])
            if _pid_alive(old_pid):
                os.close(fd)
                return False
        except (IndexError, ValueError):
            pass
    os.lseek(fd, 0, 0)
    os.ftruncate(fd, 0)
    os.write(fd, f"{SNAP_LOCK_TOKEN} {os.getpid()}\n".encode())
    os.fsync(fd)
    _lock_fd = fd  # 持有到进程退出，进程死了锁自动释放
    return True


class OcrWorker(QObject):
    """后台 OCR（QThread）：吃图片路径（SAVE_IMAGES=True）或内存 QPixmap，吐文本。"""

    done = Signal(str)

    def __init__(self, engine: OcrEngine, img_or_path, txt_path):
        super().__init__()
        self._engine = engine
        self._img_or_path = img_or_path
        self._txt_path = txt_path

    def run(self):
        try:
            if isinstance(self._img_or_path, str):
                text = self._engine.recognize_path(self._img_or_path)
            else:
                text = self._engine.recognize(_qpixmap_to_bgr(self._img_or_path))
        except Exception as ex:
            self.done.emit(f"[OCR 失败] {ex}")
            return
        if text:
            if self._txt_path:
                try:
                    with open(self._txt_path, "w", encoding="utf-8") as f:
                        f.write(text + "\n")
                except OSError as ex:
                    self.done.emit(f"[保存文本失败] {ex}\n\n{text}")
                    return
        self.done.emit(text)


def _qpixmap_to_bgr(pix):
    """QPixmap → BGR ndarray（SAVE_IMAGES=False 时 OCR 走内存不落盘）。"""
    import cv2
    import numpy as _np

    img = pix.toImage().convertToFormat(QImage.Format_RGB888)
    ptr = img.bits()
    ptr.setsize(img.sizeInBytes())
    arr = _np.frombuffer(ptr, _np.uint8).reshape(
        img.height(), img.bytesPerLine(), 3)[:, : img.width()]
    arr = _np.ascontiguousarray(arr)  # 拷贝脱离 QImage 生命周期，避免悬空
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


class MainWin(QWidget):
    """隐藏的编排窗口：注册热键，负责"选图 → 存盘 → 复制/OCR"流程。不 show。"""

    hotkey_pressed = Signal(str)
    hotkey_escape = Signal()
    ipc_triggered = Signal(str)   # 外部 snaptext --ocr/--img 经 socket 触发

    def __init__(self):
        super().__init__(None)
        self._busy = False
        self._pending = []      # 忙时排队的热键模式（FIFO，不丢不并发）
        self._sel = None
        self._tray = None
        self._esc = None
        self._ocr = OcrEngine()
        self._ocr_thread = None
        self._ocr_worker = None
        self._hotkeys = []
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        if _SAVE_IMAGES:
            os.makedirs(IMG_DIR, exist_ok=True)
            os.makedirs(TXT_DIR, exist_ok=True)
        # 热键回调跑在 X 轮询线程，经跨线程信号 marshal 到 GUI 线程
        self.hotkey_pressed.connect(self.start_select)
        self.hotkey_escape.connect(self._finish_cancel)
        for key, mods, mode in MODES:
            hk = _make_hotkey(key, mods, lambda m=mode: self.hotkey_pressed.emit(m))
            if hk.ok:
                self._hotkeys.append(hk)
        # 启动即后台预热 onnx 模型：模型加载约 0.8s（含 session 创建），
        # 放后台线程提前做完，首次按键不用等。OcrEngine._get_engine 是惰性
        # 单例，线程安全无锁但重复调用无害（首次真的建，后续直接拿引用）。
        if cfg.get("PREWARM_OCR"):
            threading.Thread(target=_prewarm_engine, daemon=True).start()

    def _start_next_or_idle(self):
        """当前任务收尾后调用：忙队里还有就继续下一个，没有则空闲。"""
        if self._pending:
            self._begin_select(self._pending.pop(0))
        else:
            self._busy = False

    def start_select(self, mode):
        if self._busy:
            self._pending.append(mode)   # 忙时入队，完成后自动执行
            return
        self._begin_select(mode)

    def _begin_select(self, mode):
        self._busy = True
        self._mode = mode
        self.hide()
        pix = grab_screen()
        self._sel = Selector(pix)
        self._sel.selected.connect(self._on_selected)
        self._sel.cancelled.connect(self._finish_cancel)
        self._sel.show()
        self._sel.raise_()
        self._sel.activateWindow()
        # X11：override-redirect 窗口收不到键盘事件，Esc 用临时全局热键兜底；
        # Wayland：Selector 是普通窗口、能拿键盘焦点，Esc 原生可用，不抢全局 Esc。
        if _SESSION != "wayland":
            from hotkey import GlobalHotkey
            self._esc = GlobalHotkey(cfg.get("ESC_KEY"), 0, lambda: self.hotkey_escape.emit())

    def _release_esc(self):
        if self._esc is not None:
            self._esc.release()
            self._esc = None

    def _finish_cancel(self):
        self._release_esc()
        if self._sel is not None:
            self._sel.close()
        self._sel = None
        self._start_next_or_idle()

    def _on_selected(self, r):
        src = self._sel._pix
        # 高分屏：选区 r 是逻辑坐标，pix 是设备像素（dpr=2），拷图前乘 dpr
        dpr = src.devicePixelRatio()
        pix = src.copy(
            QRect(
                int(r.x() * dpr),
                int(r.y() * dpr),
                int(r.width() * dpr),
                int(r.height() * dpr),
            )
        )
        self._release_esc()
        self._sel = None
        img_path = None
        txt_path = None
        ts = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
        if _SAVE_IMAGES:
            img_path = os.path.join(IMG_DIR, ts + ".png")
            pix.save(img_path, "PNG")
            txt_path = os.path.join(TXT_DIR, ts + ".txt")
        if self._mode == "img":
            QGuiApplication.clipboard().setPixmap(pix)
            self._notify(
                "已保存并复制图片" if img_path else "已复制图片",
                os.path.basename(img_path) if img_path else "（未存盘）",
            )
            self._start_next_or_idle()
        else:
            # SAVE_IMAGES=False 时图片只留在内存，OCR 直接吃 QPixmap
            self._run_ocr(img_path or pix, txt_path)

    def _notify(self, title, msg):
        if self._tray is not None:
            self._tray.notify(title, msg, cfg.get("NOTIFY_MS"))

    def _run_ocr(self, img_path, txt_path):
        th = QThread(self)
        wk = OcrWorker(self._ocr, img_path, txt_path)
        wk.moveToThread(th)
        th.started.connect(wk.run)
        wk.done.connect(self._on_ocr_done)
        wk.done.connect(th.quit)
        wk.done.connect(wk.deleteLater)
        th.finished.connect(th.deleteLater)
        # 必须存 self 保持强引用：PySide6 对"纯 Python 方法槽"不持强引用，
        # 局部变量作用域结束后 wk 会被 GC，run 永远不会被调用
        self._ocr_worker = wk
        self._ocr_thread = th
        th.finished.connect(lambda: setattr(self, "_ocr_worker", None))
        th.finished.connect(lambda: setattr(self, "_ocr_thread", None))
        th.start()

    def _on_ocr_done(self, text):
        self._start_next_or_idle()
        if text and not text.startswith("["):
            QGuiApplication.clipboard().setText(text)
            preview = text.replace("\n", " ")
            if len(preview) > 40:
                preview = preview[:40] + "…"
            self._notify("OCR 完成，已复制", preview)
        else:
            self._notify("OCR 失败", text)

    def closeEvent(self, e):
        self.cleanup()
        super().closeEvent(e)

    def cleanup(self):
        """退出时释放热键、等 OCR 线程收尾。"""
        for hk in self._hotkeys:
            hk.release()
        self._hotkeys.clear()
        th = self._ocr_thread
        if th is not None and th.isRunning():
            th.quit()        # 正在跑 OCR 的 slot 返回后退出事件循环
            th.wait(3000)
        self._ocr_thread = None


def main():
    argv = sys.argv[1:]
    trigger = "ocr" if "--ocr" in argv else ("img" if "--img" in argv else None)

    if not acquire_single_instance():
        # 已有常驻实例：若有触发命令，经 socket 派发给它后退出
        if trigger and _ipc_send(IPC_SOCK, trigger):
            return 0
        print("拾字 SnapText 已在运行（单实例），退出。", file=sys.stderr)
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # 托盘 app 不应随"最后一个窗口关闭"退出（选区遮罩关闭会误触发）
    app.setQuitOnLastWindowClosed(False)
    w = MainWin()
    tray = TrayIcon(
        w,
        hk_img=cfg.hotkey_display(cfg.get("HOTKEY_IMAGE")),
        hk_ocr=cfg.hotkey_display(cfg.get("HOTKEY_OCR")),
    )
    w._tray = tray
    app.aboutToQuit.connect(w.cleanup)
    tray.show()

    # 外部触发（GNOME/其它 wayland 绑命令）经 socket 派发到 GUI 线程
    if _IpcServer(IPC_SOCK, lambda m: w.ipc_triggered.emit(m)).start():
        w.ipc_triggered.connect(w.start_select)
    # GNOME：自动注册 gsettings 自定义快捷键（绑 --ocr/--img 命令），尽力而为
    if _SESSION == "wayland":
        _register_gnome_shortcuts()
    # 本次若以 --ocr/--img 启动（无常驻时），起好后触发一次
    if trigger:
        QTimer.singleShot(300, lambda: w.start_select(trigger))

    sys.exit(app.exec())


if __name__ == "__main__":
    sys.exit(main())
