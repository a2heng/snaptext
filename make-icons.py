#!/usr/bin/env python3
"""生成程序化图标：蓝底圆角方块 + 白"拾"字（与托盘 make_icon 同风格）。

输出到 ./icons/：
  snaptext-{16,24,32,48,64,128,256}.png   多尺寸 PNG（供 hicolor 主题）
  snaptext.ico                             多帧 ICO（16/32/48/256）

供 deb 打包（pack-deb.sh 调用）和 .desktop 图标使用。用 PySide6 离屏渲染，
无外部资源文件。用法：QT_QPA_PLATFORM=offscreen python3 make-icons.py
"""
import os
import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QImage,
    QPainter,
    QPixmap,
)

BG = QColor("#2b5f9c")
FG = QColor("#ffffff")
CHAR = "拾"
# 宋体 Black：笔画厚重、有书法感，小尺寸下也清晰，图标文字辨识度高。
FONT_PATH = "/usr/share/fonts/TTF/NotoSerifCJK-Black.ttc"
# 字号占边长的比例：比托盘默认更大（0.40→0.55），文字更饱满醒目。
FONT_PT_RATIO = 0.55
OUT_DIR = Path(__file__).resolve().parent / "icons"

# 缓存字体族名（运行时静态字体，仅打包/托盘加载一次）
_FONT_FAMILY = None


def _char_font(size: int) -> QFont:
    global _FONT_FAMILY
    if _FONT_FAMILY is None:
        fid = QFontDatabase.addApplicationFont(FONT_PATH)
        _FONT_FAMILY = QFontDatabase.applicationFontFamilies(fid)[0]
    f = QFont(_FONT_FAMILY)
    f.setPointSizeF(size * FONT_PT_RATIO)
    return f


def draw(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(BG)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, size, size, int(size * 0.1), int(size * 0.1))
    p.setPen(FG)
    p.setFont(_char_font(size))
    p.drawText(pm.rect(), Qt.AlignCenter, CHAR)
    p.end()
    return pm


def _png_bytes(img: QImage) -> bytes:
    ba = QBuffer()
    ba.open(QBuffer.WriteOnly)
    img.save(ba, "PNG")
    return bytes(ba.data())


def main() -> int:
    app = QGuiApplication([])  # 离屏渲染需要 QGuiApplication
    OUT_DIR.mkdir(exist_ok=True)

    for s in (16, 24, 32, 48, 64, 128, 256):
        draw(s).save(str(OUT_DIR / f"snaptext-{s}.png"), "PNG")

    # 多帧 ICO：头部 + 目录项（帧图片用 PNG 数据）
    frames = []
    for s in (16, 32, 48, 256):
        pm = draw(s)
        img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
        frames.append((s, _png_bytes(img)))
    out = bytearray()
    out += struct.pack("<HHH", 0, 1, len(frames))  # ICONDIR
    offset = 6 + 16 * len(frames)                   # ICONDIRENTRY 起点
    for s, png in frames:
        w = 0 if s >= 256 else s
        out += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    for _, png in frames:
        out += png
    (OUT_DIR / "snaptext.ico").write_bytes(bytes(out))

    print(f"已生成 {OUT_DIR}/ 下 7 个 PNG + snaptext.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
