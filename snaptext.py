#!/usr/bin/env python3
"""拾字 SnapText —— 极简屏幕 OCR（入口：接线 ocr/hotkey/ui 独立模块）

全局快捷键（X11）：
  Alt+X  截图 → 保存选区图片 → 复制图片到剪贴板
  Alt+C  截图 → 保存图片 → OCR → 保存文本 → 复制文字到剪贴板

模块：
  ocr.py     图片 → 文本（纯 onnx，Qt-free，可命令行单跑）
  hotkey.py  全局热键 XGrabKey（X11，Qt-free）
  ui.py      选区 Selector + 结果窗 ResultDlg + grab_screen

保存位置：
  ~/.snaptext/img/    图片  YYYYMMDD_HHMMSS_XXX.png
  ~/.snaptext/text/   文本  YYYYMMDD_HHMMSS_XXX.txt
"""
import os
import sys
import time

from PySide6.QtCore import QObject, QRect, QThread, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QWidget

from hotkey import GlobalHotkey
from ocr import OcrEngine
from tray import TrayIcon
from ui import ResultDlg, Selector, grab_screen

APP_NAME = "拾字 SnapText"
IMG_DIR = os.path.expanduser("~/.snaptext/img")
TXT_DIR = os.path.expanduser("~/.snaptext/text")

# (keysym, modifiers, mode)
MODE_IMG = ("x", 8, "img")   # Alt+X：截图+存图+复制图片
MODE_OCR = ("c", 8, "ocr")   # Alt+C：截图+存图+OCR+复制文字
HOTKEY_LABEL = {"img": "Alt+X 截图保存复制", "ocr": "Alt+C 截图+OCR"}


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

    def __init__(self):
        super().__init__(None)
        self._busy = False
        self._sel = None
        self._ocr = OcrEngine()
        self._ocr_thread = None
        self._hotkeys = []
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        os.makedirs(IMG_DIR, exist_ok=True)
        os.makedirs(TXT_DIR, exist_ok=True)
        lay = QHBoxLayout(self)
        lay.addWidget(QLabel("⚡ 截书"))
        # 热键回调跑在 X 轮询线程，经跨线程信号 marshal 到 GUI 线程
        self.hotkey_pressed.connect(self.start_select)
        for key, mods, mode in (MODE_IMG, MODE_OCR):
            hk = GlobalHotkey(key, mods, lambda m=mode: self.hotkey_pressed.emit(m))
            if hk.ok:
                self._hotkeys.append(hk)
                lay.addWidget(QLabel(f"<span style='color:#888'>{HOTKEY_LABEL[mode]}</span>"))
            else:
                lay.addWidget(QLabel(f"<span style='color:#c33'>{HOTKEY_LABEL[mode]} 注册失败</span>"))

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

    def _finish_cancel(self):
        self._sel = None
        self._busy = False
        self.show()

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
        self._sel = None
        ts = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
        img_path = os.path.join(IMG_DIR, ts + ".png")
        pix.save(img_path, "PNG")
        if self._mode == "img":
            QGuiApplication.clipboard().setPixmap(pix)
            self._finish(f"图片已保存：\n{img_path}\n\n图片已复制到剪贴板", "已保存")
        else:
            self._run_ocr(img_path, os.path.join(TXT_DIR, ts + ".txt"))

    def _finish(self, text, title="识别结果"):
        self._busy = False
        self.show()
        ResultDlg(text, title, self).exec()

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
        th.start()

    def _on_ocr_done(self, text):
        if text and not text.startswith("["):
            QGuiApplication.clipboard().setText(text)
            self._finish(text, "识别结果")
        else:
            self._finish(text, "识别失败")

    def closeEvent(self, e):
        self.cleanup()
        super().closeEvent(e)

    def cleanup(self):
        """释放热键（QApplication 退出时可能不触发 closeEvent，需显式调）。"""
        for hk in self._hotkeys:
            hk.release()
        self._hotkeys.clear()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWin()
    tray = TrayIcon(w)
    app.aboutToQuit.connect(w.cleanup)
    tray.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
