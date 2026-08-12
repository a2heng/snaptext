# -*- coding: utf-8 -*-
"""内部配置模块：读取用户可编辑的 config.py（全注释模板），未覆盖项用内置默认。

config.py 是"配置模板"：所有行默认都是注释（=不改配置）。本模块在 import 时
用 ast 解析它，只收集白名单内的顶层 `名 = 值` 赋值；没有任何赋值就全部用
内置默认——与旧版本行为完全一致（"不改即现状"）。配置启动时读一次，改后需重启。

仅依赖标准库（无 Qt/第三方库），可被 ocr/ui/snaptext 任意模块 import。
"""
import ast
import re
import sys
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parent / "config.py"

DEFAULTS = {
    # --- 存储 ---
    "DATA_DIR": "~/.snaptext",
    "LOCK_PATH": "~/.snaptext.lock",
    # --- 全局热键（写法见 config.py 内说明） ---
    "HOTKEY_IMAGE": "alt+x",
    "HOTKEY_OCR": "alt+c",
    "ESC_KEY": "Escape",
    # --- OCR（见 AGENTS.md「OCR 踩过的坑」，改前先读） ---
    "OCR_WIDTH_HEIGHT_RATIO": 100,
    "OCR_DET_LIMIT_TYPE": "max",
    "OCR_DET_LIMIT_SIDE_LEN": 960,
    # --- 选区 overlay ---
    "SELECT_MIN_SIZE": 5,
    "SELECT_MASK_ALPHA": 100,
    "SELECT_BORDER_COLOR": "#0078D7",
    # --- 行为 / 落盘 ---
    "SAVE_IMAGES": True,
    "PREWARM_OCR": True,
    "NOTIFY_MS": 2000,
}

# 修饰键名 → X11 modifier mask 位。CapsLock/NumLock 变体由 hotkey.py 自动兼容。
_MOD_MASK = {"shift": 1, "ctrl": 4, "alt": 8, "super": 64}


def parse_hotkey(spec: str):
    """解析热键写法 "alt+x" / "ctrl+shift+e" → (keysym, mods)。

    最后一段是 X11 keysym（大小写不敏感），其余为修饰键（可多个、顺序不限）；
    只有键名没有修饰键（如 "F9"）→ mods=0。解析失败抛 ValueError。
    """
    parts = [p.strip() for p in spec.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"空热键写法: {spec!r}")
    key = parts[-1].lower()
    mods = 0
    for m in parts[:-1]:
        m = m.lower()
        if m not in _MOD_MASK:
            raise ValueError(f"未知修饰键 {m!r}（支持 shift/ctrl/alt/super）")
        mods |= _MOD_MASK[m]
    return key, mods


def hotkey_display(spec: str) -> str:
    """把 "alt+x" 显示成 "Alt+X"（托盘提示用）。解析失败原样返回。"""
    try:
        parts = spec.split("+")
        out = [p.capitalize() if p.lower() in _MOD_MASK else p for p in parts[:-1]]
        key = parts[-1]
        if len(key) == 1:
            key = key.upper()
        out.append(key)
        return "+".join(out)
    except Exception:
        return spec


def _hotkey_ok(spec: str) -> bool:
    try:
        parse_hotkey(spec)
        return True
    except Exception:
        return False


# 类型检查一律用 `type(v) is typ`：bool 是 int 子类，isinstance 会把 True 误放行。
_VALIDATORS = {
    "OCR_DET_LIMIT_SIDE_LEN": (int, lambda v: v >= 64),
    "SELECT_MIN_SIZE": (int, lambda v: v >= 1),
    "SELECT_MASK_ALPHA": (int, lambda v: 0 <= v <= 255),
    "OCR_WIDTH_HEIGHT_RATIO": (int, lambda v: v >= 1),
    "NOTIFY_MS": (int, lambda v: v >= 0),
    "OCR_DET_LIMIT_TYPE": (str, lambda v: v in ("max", "min")),
    "SELECT_BORDER_COLOR": (str, lambda v: re.fullmatch(r"#[0-9a-fA-F]{6}", v) is not None),
    "DATA_DIR": (str, lambda v: v != ""),
    "LOCK_PATH": (str, lambda v: v != ""),
    "ESC_KEY": (str, lambda v: v.strip() != ""),
    "HOTKEY_IMAGE": (str, _hotkey_ok),
    "HOTKEY_OCR": (str, _hotkey_ok),
    "SAVE_IMAGES": (bool, None),
    "PREWARM_OCR": (bool, None),
}


def _valid(name: str, value) -> bool:
    info = _VALIDATORS.get(name)
    if info is None:
        return False
    typ, check = info
    if type(value) is not typ:
        return False
    return check is None or check(value)


_overrides = {}
if CONFIG_FILE.exists():
    try:
        _tree = ast.parse(CONFIG_FILE.read_text(encoding="utf-8"),
                          filename=str(CONFIG_FILE))
    except SyntaxError as e:
        print(f"[配置] 解析 {CONFIG_FILE} 失败，全部使用默认（=现状）: {e}",
              file=sys.stderr)
        _tree = None
    if _tree is not None:
        for _node in ast.iter_child_nodes(_tree):
            if (isinstance(_node, ast.Assign) and len(_node.targets) == 1
                    and isinstance(_node.targets[0], ast.Name)):
                _name = _node.targets[0].id
                if _name in DEFAULTS:
                    try:
                        _value = ast.literal_eval(_node.value)
                    except (ValueError, SyntaxError):
                        continue
                    if _valid(_name, _value):
                        _overrides[_name] = _value
                    else:
                        print(f"[配置] {_name} = {_value!r} 不合法，该项回退默认"
                              f"（=现状）", file=sys.stderr)


def get(name: str):
    """取配置值；config.py 未覆盖时返回内置默认（=现状）。"""
    return _overrides.get(name, DEFAULTS[name])