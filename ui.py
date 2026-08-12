"""拾字 SnapText —— 独立 UI 模块（全屏选区）。

只含 Qt/UI 逻辑：不掺热键、不掺 OCR。其它模块通过 grab_screen / Selector 调用。
"""
import _config

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

_MIN_SIZE = _config.get("SELECT_MIN_SIZE")
_MASK_ALPHA = _config.get("SELECT_MASK_ALPHA")
_BORDER_COLOR = QColor(_config.get("SELECT_BORDER_COLOR"))


def grab_screen() -> QPixmap:
    """抓取主屏全屏（含系统面板）。

    配合 Selector 的 X11BypassWindowManagerHint 全屏 overlay，两者 1:1：
    所见即所得，也能选中/截到面板区域。
    """
    return QGuiApplication.primaryScreen().grabWindow(0)


class Selector(QWidget):
    """全屏半透明拉框 overlay，快捷键触发截图后展示。"""

    selected = Signal(QRect)  # 松手且选区 >= 5x5 时 emit
    cancelled = Signal()      # Esc 取消时 emit

    def __init__(self, pix: QPixmap):
        # X11BypassWindowManagerHint：绕过 WM 直接叠在根窗口上，
        # 才能盖住 KDE 系统面板（普通置顶窗会被面板压住）；代价是
        # 收不到键盘事件，Esc 需由入口侧用全局热键兜底。
        super().__init__(
            None,
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.X11BypassWindowManagerHint,
        )
        self._pix = pix
        self._start = QPoint()
        self._cur = QPoint()
        self._selecting = False
        screen = QGuiApplication.primaryScreen()
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMouseTracking(True)

    def sel_rect(self) -> QRect:
        """当前选区（规范化，任意方向拖拽都为正）。"""
        return QRect(self._start, self._cur).normalized()

    def paintEvent(self, event):
        p = QPainter(self)
        # 高分屏：pix 是设备像素（如 3840x2160, dpr=2），窗口/鼠标坐标是逻辑
        # （1920x1080）。drawPixmap 的 source 矩形按"图片像素"计，必须乘 dpr。
        dpr = self._pix.devicePixelRatio()
        # 底图铺满整个屏幕
        p.drawPixmap(
            QRectF(self.rect()),
            self._pix,
            QRectF(0, 0, self._pix.width(), self._pix.height()),
        )
        # 半透明黑遮罩
        p.fillRect(self.rect(), QColor(0, 0, 0, _MASK_ALPHA))
        r = self.sel_rect()
        if self._selecting and not r.isNull():
            # 选区原位还原：source 用设备像素（r * dpr），target 用逻辑 r
            p.drawPixmap(
                QRectF(r),
                self._pix,
                QRectF(r.x() * dpr, r.y() * dpr, r.width() * dpr, r.height() * dpr),
            )
            # 蓝框
            p.setPen(QPen(_BORDER_COLOR, 2))
            p.drawRect(r)
            # "宽 × 高" 尺寸文字（带底衬保证可读）
            label = f"{r.width()} × {r.height()}"
            fm = p.fontMetrics()
            tw, th = fm.horizontalAdvance(label) + 8, fm.height()
            tx, ty = r.left(), r.top() - th - 4
            if ty < 0:
                ty = r.bottom() + 4
            p.fillRect(tx, ty, tw, th, QColor(0, 0, 0, 160))
            p.drawText(QRect(tx, ty, tw, th), Qt.AlignCenter, label)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._start = ev.position().toPoint()
            self._cur = self._start
            self._selecting = True
            self.update()

    def mouseMoveEvent(self, ev):
        if self._selecting:
            self._cur = ev.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._selecting:
            self._selecting = False
            r = self.sel_rect()
            if r.width() >= _MIN_SIZE and r.height() >= _MIN_SIZE:
                self.selected.emit(r)
            else:
                self.cancelled.emit()  # 太小视为取消
            self.close()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.cancelled.emit()
            self.close()
