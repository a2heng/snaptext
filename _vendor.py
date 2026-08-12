# -*- coding: utf-8 -*-
"""依赖内化引导：把全部 Python 依赖从系统 site-packages 解耦进项目 vendor/。

克隆本项目后无需安装任何 Python 包（PySide6、OCR 链全部内置）：
ocr.py / snaptext.py 在 import 第三方库之前先调用本模块，把 vendor/
插入 sys.path 最前，优先加载项目内置的 PySide6/cv2/onnxruntime/numpy/...。

vendor/ 由 setup-vendor.sh 生成（首次联网，之后完全离线），不进 git。

用法：import _vendor; _vendor.activate()
"""

import sys
from pathlib import Path

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"

_activated = False


def activate():
    """把 vendor/ 插到 sys.path[0]。重复调用无副作用。"""
    global _activated
    if _activated:
        return
    _activated = True
    if _VENDOR_DIR.is_dir():
        sys.path.insert(0, str(_VENDOR_DIR))


def is_active() -> bool:
    return str(_VENDOR_DIR) in sys.path


def vendor_dir() -> Path:
    return _VENDOR_DIR
