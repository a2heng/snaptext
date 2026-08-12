#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 OCR 测试标定板 ocr_test.png（4K 16:9）。

核心思路：每一张测试卡独立渲染成子图再拼贴成 3x3 网格。
无任何标题/标签文字，卡内全部是差异化测试内容，填满不留白。
用法: python3 make_ocr_test.py
输出: ./ocr_test.png（3840x2160）
"""
from PIL import Image, ImageDraw, ImageFont

W, H = 3840, 2160
M, GAP = 56, 20
COLS = ROWS = 3
CW = (W - 2 * M - (COLS - 1) * GAP) // COLS
CH = (H - 2 * M - (ROWS - 1) * GAP) // ROWS
PAD = 40

FONTS = {
    "sans": "/usr/share/fonts/TTF/NotoSansCJK-Regular.ttc",
    "sans_bold": "/usr/share/fonts/TTF/NotoSansCJK-Bold.ttc",
    "sans_light": "/usr/share/fonts/TTF/NotoSansCJK-Light.ttc",
    "serif": "/usr/share/fonts/TTF/NotoSerifCJK-Regular.ttc",
    "serif_bold": "/usr/share/fonts/TTF/NotoSerifCJK-Bold.ttc",
    "mono": "/usr/share/fonts/OTF/NotoSansMonoCJKsc-Regular.otf",
}


def font(kind, size):
    return ImageFont.truetype(FONTS[kind], size)


def fit(cd, kind, txt, maxw, base=30, max_size=96):
    """在不超过 maxw 内尽量放大的字号。"""
    lo, hi = base, max_size
    while lo <= hi:
        mid = (lo + hi) // 2
        tb = cd.textbbox((0, 0), txt, font=font(kind, mid))
        if tb[2] - tb[0] <= maxw:
            lo = mid + 1
        else:
            hi = mid - 1
    return hi


def draw_text(img, cd, pos, txt, size, color=(0, 0, 0), kind="sans", angle=0):
    """绘制文本，返回真实占位 (w, h)。"""
    x0, y0 = pos
    f = font(kind, size)
    tb = cd.textbbox((0, 0), txt, font=f)
    tw_, th = tb[2] - tb[0], tb[3] - tb[1]
    if angle:
        pad = max(8, size // 3)
        tmp = Image.new("RGBA", (tw_ + pad * 2, th + pad * 2), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((pad - tb[0], pad - tb[1]), txt, font=f, fill=color)
        tmp = tmp.rotate(angle, expand=True, resample=Image.BICUBIC,
                         fillcolor=(0, 0, 0, 0))
        img.paste(tmp, (x0, y0), tmp)
        return tmp.size
    cd.text((x0 - tb[0], y0 - tb[1]), txt, font=f, fill=color)
    return (tw_, th)


def make_card(fn):
    card = Image.new("RGB", (CW, CH), (252, 252, 252))
    cd = ImageDraw.Draw(card)
    cd.rectangle([0, 0, CW - 1, CH - 1], fill=(252, 252, 252),
                 outline=(140, 146, 158), width=2)
    fn(card, cd, CW, CH)
    return card


def full_line(cd, kind, txt, y, maxw, color=(0, 0, 0), base=30):
    """整行铺满：字号放大到恰好一行的宽度。"""
    size = fit(cd, kind, txt, maxw, base=base)
    draw_text(None, cd, (PAD, y), txt, size, color, kind)
    tb = cd.textbbox((0, 0), txt, font=font(kind, size))
    return y + (tb[3] - tb[1]) + 12


# 卡 1: 字号梯度（多行不同字号，内容即文本）
def card_fontsize(img, cd, w, h):
    lines = [
        (18, "一寸光阴一寸金 123"),
        (26, "寸金难买寸光阴 456"),
        (38, "春宵一刻值千金 789"),
        (56, "花有清香月有阴 2026"),
        (80, "歌管楼台声细细 0"),
    ]
    y = PAD
    for size, txt in lines:
        tb = cd.textbbox((0, 0), txt, font=font("sans", size))
        cd.text((PAD, y), txt, font=font("sans", size), fill=(0, 0, 0))
        y += tb[3] - tb[1] + 10


# 卡 2: 黑体字重
def card_heiti(img, cd, w, h):
    rows = [
        ("落霞与孤鹜齐飞 秋水共长天一色", "sans"),
        ("大江东去浪淘尽 千古风流人物", "sans_bold"),
        ("清风徐来 水波不兴 举酒属客", "sans_light"),
        ("惟江上之清风 与山间之明月", "sans"),
    ]
    y = PAD
    for txt, kind in rows:
        size = fit(cd, kind, txt, w - PAD * 2, base=30)
        draw_text(None, cd, (PAD, y), txt, size, (0, 0, 0), kind)
        tb = cd.textbbox((0, 0), txt, font=font(kind, size))
        y += tb[3] - tb[1] + 18


# 卡 3: 宋体 + 等宽
def card_songti(img, cd, w, h):
    rows = [
        ("秋水共长天一色 落霞与孤鹜齐飞", "serif"),
        ("会当凌绝顶 一览众山小 会当凌绝顶", "serif_bold"),
        ("def ocr(path):  return engine.recognize(path)", "mono"),
        ("cfg = {'dpi': 192, 'lang': 'zh-CN', 'v': 1}", "mono"),
        ("for i in range(10):  print(f'line {i}')", "mono"),
    ]
    y = PAD
    for txt, kind in rows:
        size = fit(cd, kind, txt, w - PAD * 2, base=28)
        draw_text(None, cd, (PAD, y), txt, size, (0, 0, 0), kind)
        tb = cd.textbbox((0, 0), txt, font=font(kind, size))
        y += tb[3] - tb[1] + 16


# 卡 4: 颜色（每行一句彩色文案）
def card_color(img, cd, w, h):
    rows = [
        ("枫叶染红了整个山野", (200, 20, 20)),
        ("海浪卷起深蓝的泡沫", (20, 20, 200)),
        ("林间松针滴着翠绿的露水", (20, 140, 20)),
        ("葡萄架下紫藤花垂落", (128, 0, 128)),
        ("湖面倒映着青色的天", (0, 130, 130)),
        ("夕阳把云朵染成琥珀色", (210, 110, 0)),
    ]
    y = PAD
    for txt, c in rows:
        size = fit(cd, "sans", txt, w - PAD * 2, base=28)
        draw_text(None, cd, (PAD, y), txt, size, c, "sans")
        tb = cd.textbbox((0, 0), txt, font=font("sans", size))
        y += tb[3] - tb[1] + 14


# 卡 5: 倾斜角度（古诗整段旋转，无标签）
def card_rot(img, cd, w, h):
    items = [
        (-10, "梅子黄时日日晴 小溪泛尽却山行"),
        (-5, "绿阴不减来时路 添得黄鹂四五声"),
        (+5, "竹外桃花三两枝 春江水暖鸭先知"),
        (+10, "蒌蒿满地芦芽短 正是河豚欲上时"),
        (+15, "千里莺啼绿映红 水村山郭酒旗风"),
        (+20, "南朝四百八十寺 多少楼台烟雨中"),
    ]
    for i, (ang, txt) in enumerate(items):
        cx = PAD + (i % 2) * (w // 2)
        cy = PAD + (i // 2) * ((h - PAD * 2) // 3)
        size = fit(cd, "sans", txt, w // 2 - PAD * 2, base=26)
        draw_text(img, cd, (cx, cy), txt, size, (0, 0, 0), "sans", angle=ang)


# 卡 6: 深色背景
def card_dark(img, cd, w, h):
    cd.rectangle([0, 0, w - 1, h - 1], fill=(28, 28, 30))
    rows = [
        ("深色背景上的白色文字 123456", (255, 255, 255)),
        ("暗色模式 OCR 测试明亮前景更易识别", (255, 214, 100)),
        ("深灰底上的浅灰文字同样可读", (170, 175, 185)),
        ("hex #2A2A2E  date 2026-08-12  snaptext", (230, 230, 230)),
        ("mono 固定宽度: 0O1l 8B 5S 2Z", (120, 220, 180)),
    ]
    y = PAD
    for txt, c in rows:
        size = fit(cd, "sans", txt, w - PAD * 2, base=26, max_size=72)
        kind = "mono" if txt.startswith(("hex", "mono")) else "sans"
        draw_text(None, cd, (PAD, y), txt, size, c, kind)
        tb = cd.textbbox((0, 0), txt, font=font(kind, size))
        y += tb[3] - tb[1] + 16


# 卡 7: 英文长句
def card_en(img, cd, w, h):
    lines = [
        "This is a sentence with several words to test line merging.",
        "Multi-line blocks should stay as separate lines when detected.",
        "A third line makes the paragraph unmistakably multi-row.",
        "Quick brown foxes jump over lazy dogs near the river bank.",
    ]
    y = PAD
    for txt in lines:
        size = fit(cd, "sans", txt, w - PAD * 2, base=30)
        draw_text(None, cd, (PAD, y), txt, size, (0, 0, 0), "sans")
        tb = cd.textbbox((0, 0), txt, font=font("sans", size))
        y += tb[3] - tb[1] + 20


# 卡 8: 中文长句
def card_zh(img, cd, w, h):
    lines = [
        "中文长句应该保持在同一行被完整检测出来不产生多余断行。",
        "这一句同样用来验证多个中文词块能否正确合并到一条线。",
        "行合并完成后按阅读顺序从左到右依次输出每一条文本。",
        "数字与汉字混排验证 2026 年 8 月 12 日 9 时 37 分 42 秒。",
    ]
    y = PAD
    for txt in lines:
        size = fit(cd, "sans", txt, w - PAD * 2, base=30)
        draw_text(None, cd, (PAD, y), txt, size, (0, 0, 0), "sans")
        tb = cd.textbbox((0, 0), txt, font=font("sans", size))
        y += tb[3] - tb[1] + 20


# 卡 9: 数字符号 / 混排
def card_sym(img, cd, w, h):
    lines = [
        ("0123456789  977.53  -42  3.14159  2e10", "mono"),
        ("C++  @ # $ % & *  =  !=  >=  <=  &&  ||", "mono"),
        ("标点：，。！？：；（）【】《》·——中英混排", "sans"),
        ("Mix 中英混排 test 大小写 CASE abcDEF 123", "sans"),
        ("HeIlO wOrLd 全大写 ABC 全小写 xyz 0x3F 1101", "sans_bold"),
        ("IPv6 ::1  MAC aa:bb:cc:dd:ee:ff  UUID 8-4-4-4-12", "mono"),
    ]
    y = PAD
    for txt, kind in lines:
        size = fit(cd, kind, txt, w - PAD * 2, base=26, max_size=64)
        draw_text(None, cd, (PAD, y), txt, size, (0, 0, 0), kind)
        tb = cd.textbbox((0, 0), txt, font=font(kind, size))
        y += tb[3] - tb[1] + 14


CARDS = [card_fontsize, card_heiti, card_songti, card_color, card_rot, card_dark,
         card_en, card_zh, card_sym]

grid = Image.new("RGB", (W, H), (255, 255, 255))
for idx, fn in enumerate(CARDS):
    row, col = divmod(idx, COLS)
    card = make_card(fn)
    grid.paste(card, (M + col * (CW + GAP), M + row * (CH + GAP)))

out = "ocr_test.png"
grid.save(out)
print(f"已生成 {out} ({W}x{H})  卡片 {COLS}x{ROWS} = {CW}x{CH}")