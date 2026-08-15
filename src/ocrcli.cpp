#include <cstdio>
#include <cstdlib>
#include <string>

#include "ocr.h"

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "用法: snaptext-ocr <图片路径> [det_model] [cls_model] [rec_model]\n");
        return 2;
    }
    const std::string img = argv[1];
    const std::string det = argc > 2 ? argv[2] : "models/PP-OCRv6_det_small.onnx";
    const std::string cls = argc > 3 ? argv[3] : "models/ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx";
    const std::string rec = argc > 4 ? argv[4] : "models/PP-OCRv6_rec_small.onnx";

    try {
        OcrEngine engine(det, cls, rec);
        std::string text = engine.recognizePath(img);
        std::printf("%s\n", text.c_str());
    } catch (const std::exception& e) {
        std::fprintf(stderr, "OCR 失败: %s\n", e.what());
        return 1;
    }
    return 0;
}
