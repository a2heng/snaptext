# -*- coding: utf-8 -*-
"""独立 OCR 模块：图片 → 文本（本地 onnx，Qt-free）。

仅依赖标准库 + numpy + cv2 + rapidocr（新版统一包，旧 rapidocr_onnxruntime
已停更）。模型在项目 models/ 内本地加载，不联网；模块内复用单个 RapidOCR 实例。
"""

import sys
from pathlib import Path

import _bootstrap

_bootstrap.activate()

import _config

import cv2
from rapidocr import OCRVersion, RapidOCR

_engine = None

# 模型随项目打包（models/，仓库内），真正离线、不依赖 wheel 内置模型。
# PP-OCRv5（2026-08-12 升级：行合并更完整、字符识别更准，见 AGENTS.md）。
# 新版 rapidocr 用 params（"段.键" 形式）指定模型路径，走 model_path 即不下载。
_MODELS = {
    "det": Path(__file__).resolve().parent / "models" / "PP-OCRv6_det_small.onnx",
    "rec": Path(__file__).resolve().parent / "models" / "PP-OCRv6_rec_small.onnx",
    "cls": Path(__file__).resolve().parent / "models" / "ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx",
}


def _get_engine() -> RapidOCR:
    """惰性获取全局唯一 RapidOCR 实例（首次调用才加载模型）。

    新版 rapidocr 3.x 参数形式是 "{段}.{键}"（段 ∈ Global/Det/Cls/Rec/EngineConfig）：
    - 模型路径：Det/Cls/Rec.model_path 指定即离线加载，不触发下载。
    - 坑1（宽高比跳过 det）：新 API 已改为 apply_vertical_padding 处理窄条；
      Global.width_height_ratio 保留但语义变"加垂直 padding 的触发阈值"。
    - 坑2（扁图放大爆炸）：Det.limit_type='max' + limit_side_len=960 语义不变
      （长边封顶 960、32 对齐），4K/窄条都不会全尺寸推理。
    """
    global _engine
    if _engine is None:
        _engine = RapidOCR(params={
            "Det.model_path": str(_MODELS["det"]),
            "Rec.model_path": str(_MODELS["rec"]),
            "Cls.model_path": str(_MODELS["cls"]),
            # PP-OCRv6 det/rec + v5 的 LCNet 方向分类器（v6 复用 v5 的 cls，
            # 输入 [3,80,160]；设 Cls.ocr_version=v5 匹配形状，否则默认 v4 用
            # [3,48,192] 维度不匹配报错）。
            "Det.ocr_version": OCRVersion.PPOCRV6,
            "Rec.ocr_version": OCRVersion.PPOCRV6,
            "Cls.ocr_version": OCRVersion.PPOCRV5,
            "Global.width_height_ratio": _config.get("OCR_WIDTH_HEIGHT_RATIO"),
            "Det.limit_type": _config.get("OCR_DET_LIMIT_TYPE"),
            "Det.limit_side_len": _config.get("OCR_DET_LIMIT_SIDE_LEN"),
        })
    return _engine


class OcrEngine:
    """图片 → 文本的 OCR 引擎。"""

    @staticmethod
    def _merge_to_lines(results, y_tol_ratio=0.6):
        """把 det 切碎的框按视觉行合并（旋转稳健）。

        RapidOCR 的 det 按连通域出框，一行内有大间隙（标签页/菜单项等）会
        切成多个词块框，直接逐框输出会"换行过频"。这里做行合并：
        1. 用 minAreaRect 求每框方向角，取主导方向为文本方向；
        2. 把每框中心投影到"文本方向"与"法线"轴上；
        3. 沿法线轴聚类成行，同行内沿文本方向排序、空格连接。
        对水平/倾斜/竖排文本均成立（倾斜时投影到同一法线上仍同属一行）。
        """
        if not results:
            return ""
        import numpy as _np

        def _text_angle(box):
            """框长边方向角（弧度），归一到 (-90,90]，即文本走向。"""
            (_, _), (w, h), angle = cv2.minAreaRect(
                _np.array(box, _np.float32))
            if w < h:
                angle += 90
            angle = angle % 180
            if angle > 90:
                angle -= 180
            return _np.radians(angle)

        items = []
        for box, text, _score in results:
            cx = sum(p[0] for p in box) / 4
            cy = sum(p[1] for p in box) / 4
            items.append((cx, cy, box, text))
        if not items:
            return ""

        # 主导文本方向：中位数角度（对离群角度稳健）。角度已归一到 (-90,90]。
        theta = _np.median([_text_angle(box) for _, _, box, _ in items])
        d = (_np.cos(theta), _np.sin(theta))   # 文本方向单位向量
        n = (-_np.sin(theta), _np.cos(theta))  # 法线单位向量（垂直于文本方向）

        proj = []
        for cx, cy, box, text in items:
            acr = [p[0] * n[0] + p[1] * n[1] for p in box]
            along = [p[0] * d[0] + p[1] * d[1] for p in box]
            proj.append((min(acr), max(acr), min(along), max(along), text))
        proj.sort(key=lambda p: p[0])

        # 同一视觉行 = 相邻框沿法线的重叠比例足够高（框在同一文字带内）。
        # 不同行即使法线区间轻微搭界（如紧挨的窄条文字），重叠比例也很低，
        # 不会误连。重叠比例以两框中较矮者为基准。
        lines, cur = [], []
        for a0, a1, l0, l1, text in proj:
            if cur:
                cur_a0 = min(c[0] for c in cur)
                cur_a1 = max(c[1] for c in cur)
                overlap = min(a1, cur_a1) - max(a0, cur_a0)
                span = min(a1 - a0, cur_a1 - cur_a0)
                if overlap > 0 and overlap >= span * 0.6:
                    cur.append((a0, a1, l0, l1, text))
                    continue
            if cur:
                lines.append(cur)
            cur = [(a0, a1, l0, l1, text)]
        if cur:
            lines.append(cur)

        out = []
        for ln in lines:
            ln.sort(key=lambda c: c[2])
            out.append(" ".join(c[4] for c in ln))
        return "\n".join(out)

    @staticmethod
    def _to_results(res) -> list:
        """新版 RapidOCROutput → 旧的 [(box, text, score), ...] 列表。

        新 API 空结果返回 RapidOCROutput()（boxes/txts/scores 均 None），
        有结果时 boxes 是 (N,4,2) ndarray、txts/scores 是等长 tuple。
        """
        if res is None or res.boxes is None or res.txts is None:
            return []
        return [
            (box, text, score)
            for box, text, score in zip(res.boxes, res.txts, res.scores)
        ]

    def recognize(self, img) -> str:
        """img 为 BGR ndarray（cv2 约定），返回每行文本用 \\n 拼接；无文本返回空串。"""
        if img is None:
            raise RuntimeError("图片为空（None）")
        try:
            res = _get_engine()(img)
        except Exception as e:
            raise RuntimeError(f"OCR 识别失败: {e}") from e
        return self._merge_to_lines(self._to_results(res))

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
