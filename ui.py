"""拾字 SnapText —— 独立 UI 模块（全屏选区 + 结果窗）。

只含 Qt/UI 逻辑：不掺热键、不掺 OCR。其它模块通过
grab_screen / Selector / ResultDlg 调用。
"""
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def grab_screen() -> QPixmap:
    """抓取当前主屏。"""
    return QGuiApplication.primaryScreen().grabWindow(0)


class Selector(QWidget):
    """全屏半透明拉框 overlay，快捷键触发截图后展示。"""

    selected = Signal(QRect)  # 松手且选区 >= 5x5 时 emit
    cancelled = Signal()      # Esc 取消时 emit

    def __init__(self, pix: QPixmap):
        super().__init__(
            None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
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
        # 底图铺满整个屏幕
        p.drawPixmap(self.rect(), self._pix, QRect(QPoint(0, 0), self._pix.size()))
        # 半透明黑遮罩
        p.fillRect(self.rect(), QColor(0, 0, 0, 100))
        r = self.sel_rect()
        if self._selecting and not r.isNull():
            # 选区原位还原
            p.drawPixmap(r, self._pix, r)
            # 蓝框
            p.setPen(QPen(QColor(0, 120, 215), 2))
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
            if r.width() >= 5 and r.height() >= 5:
                self.selected.emit(r)
            else:
                self.cancelled.emit()  # 太小视为取消
            self.close()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.cancelled.emit()
            self.close()


class ResultDlg(QDialog):
    """结果/提示弹窗：只读文本 + 「复制」「关闭」。"""

    def __init__(self, text, title="识别结果", parent=None):
        super().__init__(parent, Qt.Tool | Qt.WindowStaysOnTopHint)
        self._text = text
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        edit = QTextEdit()
        edit.setReadOnly(True)
        edit.setPlainText(text)
        lay.addWidget(edit)
        btns = QHBoxLayout()
        copy_btn = QPushButton("复制")
        copy_btn.clicked.connect(self._copy)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        btns.addWidget(copy_btn)
        btns.addWidget(close_btn)
        lay.addLayout(btns)
        self.resize(420, 300)

    def _copy(self):
        QGuiApplication.clipboard().setText(self._text)
