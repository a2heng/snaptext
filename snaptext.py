#!/usr/bin/env python3
"""拾字 SnapText —— 极简屏幕 OCR（入口：接线 ocr/hotkey/ui/tray 独立模块）

全局快捷键（X11）：
  Alt+X  截图 → 保存选区图片 → 复制图片到剪贴板
  Alt+C  截图 → 保存图片 → OCR → 保存文本 → 复制文字到剪贴板

模块：
  ocr.py     图片 → 文本（纯 onnx，Qt-free，可命令行单跑）
  hotkey.py  全局热键 XGrabKey（X11，Qt-free）
  ui.py      选区 Selector + 结果窗 ResultDlg + grab_screen
  tray.py    常驻托盘图标

保存位置：
  ~/.snaptext/img/    图片  YYYYMMDD_HHMMSS_XXX.png
  ~/.snaptext/text/   文本  YYYYMMDD_HHMMSS_XXX.txt
"""
import os
import sys
import time

from PySide6.QtCore import QObject, QRect, QThread, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

from hotkey import GlobalHotkey
from ocr import OcrEngine
from tray import TrayIcon
from ui import Selector, grab_screen

APP_NAME = "拾字 SnapText"
IMG_DIR = os.path.expanduser("~/.snaptext/img")
TXT_DIR = os.path.expanduser("~/.snaptext/text")
# 锁文件放数据目录外：清空/删除 ~/.snaptext 不影响单例锁（flock 依赖文件持续存在）
LOCK_PATH = os.path.expanduser("~/.snaptext.lock")

# (keysym, modifiers, mode)
MODE_IMG = ("x", 8, "img")   # Alt+X：截图+存图+复制图片
MODE_OCR = ("c", 8, "ocr")   # Alt+C：截图+存图+OCR+复制文字

_lock_fd = None

# 固定 UUID 唯一单例标识（随机生成一次后不再变）：
# 所有实例共用同一 token `<uuid>_SnapText`，配合 flock + PID 存活校验防多开。
SNAP_LOCK_UUID = "61714529-f194-4e05-9b24-8f16b52d699f"
SNAP_LOCK_TOKEN = f"{SNAP_LOCK_UUID}_SnapText"


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
    """后台 OCR（QThread）：吃图片路径，吐文本。"""

    done = Signal(str)

    def __init__(self, engine: OcrEngine, img_path: str, txt_path: str):
        super().__init__()
        self._engine = engine
        self._img_path = img_path
        self._txt_path = txt_path

    def run(self):
        try:
            text = self._engine.recognize_path(self._img_path)
        except Exception as ex:
            self.done.emit(f"[OCR 失败] {ex}")
            return
        if text:
            try:
                with open(self._txt_path, "w", encoding="utf-8") as f:
                    f.write(text + "\n")
            except OSError as ex:
                self.done.emit(f"[保存文本失败] {ex}\n\n{text}")
                return
        self.done.emit(text)


class MainWin(QWidget):
    """隐藏的编排窗口：注册热键，负责"选图 → 存盘 → 复制/OCR"流程。不 show。"""

    hotkey_pressed = Signal(str)
    hotkey_escape = Signal()

    def __init__(self):
        super().__init__(None)
        self._busy = False
        self._sel = None
        self._tray = None
        self._esc = None
        self._ocr = OcrEngine()
        self._ocr_thread = None
        self._ocr_worker = None
        self._hotkeys = []
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        os.makedirs(IMG_DIR, exist_ok=True)
        os.makedirs(TXT_DIR, exist_ok=True)
        # 热键回调跑在 X 轮询线程，经跨线程信号 marshal 到 GUI 线程
        self.hotkey_pressed.connect(self.start_select)
        self.hotkey_escape.connect(self._finish_cancel)
        for key, mods, mode in (MODE_IMG, MODE_OCR):
            hk = GlobalHotkey(key, mods, lambda m=mode: self.hotkey_pressed.emit(m))
            if hk.ok:
                self._hotkeys.append(hk)

    def start_select(self, mode):
        if self._busy:
            return
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
        # override-redirect 窗口收不到键盘事件，Esc 用临时全局热键兜底
        self._esc = GlobalHotkey("Escape", 0, lambda: self.hotkey_escape.emit())

    def _release_esc(self):
        if self._esc is not None:
            self._esc.release()
            self._esc = None

    def _finish_cancel(self):
        self._release_esc()
        if self._sel is not None:
            self._sel.close()
        self._sel = None
        self._busy = False

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
        ts = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
        img_path = os.path.join(IMG_DIR, ts + ".png")
        pix.save(img_path, "PNG")
        if self._mode == "img":
            QGuiApplication.clipboard().setPixmap(pix)
            self._busy = False
            self._notify("已保存并复制图片", ts + ".png")
        else:
            self._run_ocr(img_path, os.path.join(TXT_DIR, ts + ".txt"))

    def _notify(self, title, msg):
        if self._tray is not None:
            self._tray.notify(title, msg)

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
        self._busy = False
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
    if not acquire_single_instance():
        print("拾字 SnapText 已在运行（单实例），退出。", file=sys.stderr)
        return 1
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # 托盘 app 不应随"最后一个窗口关闭"退出（选区遮罩关闭会误触发）
    app.setQuitOnLastWindowClosed(False)
    w = MainWin()
    tray = TrayIcon(w)
    w._tray = tray
    app.aboutToQuit.connect(w.cleanup)
    tray.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    sys.exit(main())
