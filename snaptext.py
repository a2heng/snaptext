#!/usr/bin/env python3
"""拾字 SnapText —— 极简屏幕 OCR（入口：接线 ocr/hotkey/ui/tray 独立模块）

全局快捷键（X11，可改，见 config.py）：
  Alt+X（默认）截图 → 保存选区图片 → 复制图片到剪贴板
  Alt+C（默认）截图 → 保存图片 → OCR → 保存文本 → 复制文字到剪贴板

模块：
  ocr.py     图片 → 文本（纯 onnx，Qt-free，可命令行单跑）
  hotkey.py  全局热键 XGrabKey（X11，Qt-free）
  ui.py      选区 Selector + ResultDlg + grab_screen
  tray.py    常驻托盘图标

保存位置（可改，见 config.py）：
  ~/.snaptext/img/    图片  YYYYMMDD_HHMMSS_XXX.png
  ~/.snaptext/text/   文本  YYYYMMDD_HHMMSS_XXX.txt
"""
import os
import sys
import threading
import time

import _config as cfg

from PySide6.QtCore import QObject, QRect, QThread, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QWidget

from hotkey import GlobalHotkey
from ocr import OcrEngine
from tray import TrayIcon
from ui import Selector, grab_screen

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
            hk = GlobalHotkey(key, mods, lambda m=mode: self.hotkey_pressed.emit(m))
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
        # override-redirect 窗口收不到键盘事件，Esc 用临时全局热键兜底
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
    if not acquire_single_instance():
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
    sys.exit(app.exec())


if __name__ == "__main__":
    sys.exit(main())
