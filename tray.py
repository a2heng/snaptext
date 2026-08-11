"""拾字 SnapText —— 独立托盘模块（常驻托盘图标替代小窗口）。

只含 Qt/UI：QSystemTrayIcon + 右键菜单（退出）。热键/OCR 逻辑不掺进来。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

APP_NAME = "拾字 SnapText"


def make_icon() -> QIcon:
    """程序化生成托盘图标（蓝底圆角方块 + 白"拾"字），无外部资源文件。"""
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#2b5f9c"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, 64, 64, 12, 12)
    p.setPen(QColor("#ffffff"))
    font = p.font()
    font.setPointSize(26)
    font.setBold(True)
    p.setFont(font)
    p.drawText(pm.rect(), Qt.AlignCenter, "拾")
    p.end()
    return QIcon(pm)


class TrayIcon(QSystemTrayIcon):
    """常驻托盘图标。右键菜单：退出。左键点击提示热键用法。"""

    def __init__(self, parent=None):
        super().__init__(make_icon(), parent)
        self.setToolTip(f"{APP_NAME}\nAlt+X 截图保存复制\nAlt+C 截图+OCR")
        menu = QMenu()
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self._quit)
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.showMessage(
                APP_NAME,
                "Alt+X 截图保存复制\nAlt+C 截图+OCR",
                QSystemTrayIcon.Information,
                3000,
            )

    def _quit(self):
        QApplication.instance().quit()
