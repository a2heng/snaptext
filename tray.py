"""拾字 SnapText —— 独立托盘模块（常驻托盘图标替代小窗口）。

只含 Qt/UI：QSystemTrayIcon + 右键菜单（退出）。热键/OCR 逻辑不掺进来。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

APP_NAME = "拾字 SnapText"

# 与 make-icons.py 保持一致：宋体 Black、字号占边长 0.55，托盘/deb 图标同款。
_BG = QColor("#2b5f9c")
_FG = QColor("#ffffff")
_CHAR = "拾"
_FONT_PATH = "/usr/share/fonts/TTF/NotoSerifCJK-Black.ttc"
_FONT_PT_RATIO = 0.55
_font_family = None


def _char_font(size: int) -> QFont:
    global _font_family
    if _font_family is None:
        fid = QFontDatabase.addApplicationFont(_FONT_PATH)
        _font_family = QFontDatabase.applicationFontFamilies(fid)[0]
    f = QFont(_font_family)
    f.setPointSizeF(size * _FONT_PT_RATIO)
    return f


def make_icon() -> QIcon:
    """程序化生成托盘图标（蓝底圆角方块 + 白"拾"字），无外部资源文件。"""
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(_BG)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, 64, 64, 7, 7)
    p.setPen(_FG)
    p.setFont(_char_font(64))
    p.drawText(pm.rect(), Qt.AlignCenter, _CHAR)
    p.end()
    return QIcon(pm)


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
