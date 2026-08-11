# -*- coding: utf-8 -*-
"""独立 OCR 模块：图片 → 文本（本地 onnx，Qt-free）。

仅依赖标准库 + numpy + cv2 + rapidocr_onnxruntime。
模型在 rapidocr wheel 内本地加载，不联网；模块内复用单个 RapidOCR 实例。
"""

import sys

import cv2
from rapidocr_onnxruntime import RapidOCR

_engine = None


def _get_engine() -> RapidOCR:
    """惰性获取全局唯一 RapidOCR 实例（首次调用才加载模型）。"""
    global _engine
    if _engine is None:
        _engine = RapidOCR()
    return _engine


class OcrEngine:
    """图片 → 文本的 OCR 引擎。"""

    def recognize(self, img) -> str:
        """img 为 BGR ndarray（cv2 约定），返回每行文本用 \\n 拼接；无文本返回空串。"""
        if img is None:
            raise RuntimeError("图片为空（None）")
        try:
            res, _ = _get_engine()(img)
        except Exception as e:
            raise RuntimeError(f"OCR 识别失败: {e}") from e
        return "\n".join(line[1] for line in (res or []))

    def recognize_path(self, path: str) -> str:
        """读图片文件 → 文本；文件不存在/打不开/引擎异常均抛 RuntimeError。"""
        img = cv2.imread(path)
        if img is None:
            raise RuntimeError(f"无法读取图片: {path}")
        return self.recognize(img)


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python3 ocr.py <图片路径>", file=sys.stderr)
        return 2
    try:
        print(OcrEngine().recognize_path(sys.argv[1]))
    except Exception as e:
        print(f"OCR 失败: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
