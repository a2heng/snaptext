# -*- coding: utf-8 -*-
"""deb 产物依赖引导：把项目内置 lib/（无系统包的 rapidocr/shapely/pyclipper/omegaconf）
插入 sys.path。

- 源码直跑：lib/ 不存在，本模块是空操作，依赖走系统/全局 site-packages。
- deb 产物：lib/ 在 /opt/snaptext/lib，import 前 activate() 让它可被找到。
"""
import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent / "lib"

_activated = False


def activate():
    global _activated
    if _activated:
        return
    _activated = True
    if _LIB_DIR.is_dir():
        sys.path.insert(0, str(_LIB_DIR))
