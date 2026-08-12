"""拾字 SnapText —— 独立托盘模块（常驻托盘图标替代小窗口）。

只含 Qt/UI：QSystemTrayIcon + 右键菜单（退出）。热键/OCR 逻辑不掺进来。
图标加载自项目内置资源 `icons/`（随仓库提交，不运行时生成）。
"""
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

APP_NAME = "拾字 SnapText"

# 托盘图标：直接加载已提交的静态资源（icons/snaptext-64.png），不运行时生成。
_ICON_PATH = Path(__file__).resolve().parent / "icons" / "snaptext-64.png"


def make_icon() -> QIcon:
    """从静态资源加载托盘图标（若缺失退回空图标，不崩溃）。"""
    return QIcon(str(_ICON_PATH))


class TrayIcon(QSystemTrayIcon):
    """常驻托盘图标。右键菜单：退出。左键点击提示热键用法。"""

    def __init__(self, parent=None, hk_img="Alt+X", hk_ocr="Alt+C"):
        super().__init__(make_icon(), parent)
        self._hk_img = hk_img
        self._hk_ocr = hk_ocr
        self.setToolTip(f"{APP_NAME}\n{hk_img} 截图保存复制\n{hk_ocr} 截图+OCR")
        menu = QMenu()
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self._quit)
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.showMessage(
                APP_NAME,
                f"{self._hk_img} 截图保存复制\n{self._hk_ocr} 截图+OCR",
                QSystemTrayIcon.Information,
                3000,
            )

    def notify(self, title, msg, timeout=2000):
        """非阻塞气泡提示（结果反馈，代替确认弹窗）。"""
        self.showMessage(title, msg, QSystemTrayIcon.Information, timeout)

    def _quit(self):
        QApplication.instance().quit()
