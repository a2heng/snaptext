#pragma once
/** OCR 模块：图片 → 文本（onnx 推理 + 视觉行合并），纯 C++，不依赖 Qt。
 *
 * 对应旧 Python ocr.py。推理核心用 vendor 的 RapidOCR C++（MIT），
 * 行合并 _merge_to_lines 移植自旧 ocr.py。可被 CLI（ocrcli.cpp）与
 * 主程序（app）共用。OcrEngine 的 Run 线程安全，可跨线程共享。
 */
#include <array>
#include <memory>
#include <string>
#include <vector>

#include <opencv2/core.hpp>

struct OcrBlock {
    std::array<cv::Point, 4> box;
    std::string text;
    float score;
};

struct OcrConfig {
    bool useCls = true;
    int maxSideLen = 2000;
    int minSideLen = 30;
    float limitSideLen = 960.0f;
    std::string limitType = "max";
    float thresh = 0.3f;
    float boxThresh = 0.5f;
    int maxCandidates = 1000;
    float unclipRatio = 1.6f;
    bool useDilation = true;
    std::string scoreMode = "fast";
    bool mergeCodeLines = false;
};

class OcrEngine {
public:
    OcrEngine(const std::string& detPath, const std::string& clsPath,
              const std::string& recPath, const OcrConfig& cfg = {});
    ~OcrEngine();
    OcrEngine(const OcrEngine&) = delete;
    OcrEngine& operator=(const OcrEngine&) = delete;

    /** BGR 图 → 每行文本（\n 拼接，已做视觉行合并）；失败抛 std::runtime_error。 */
    std::string recognize(const cv::Mat& bgr);

    /** 读图文件（BGR）→ 文本；读不到文件抛 std::runtime_error。 */
    std::string recognizePath(const std::string& path);

    /** det 原始框结果（未合并），供调用方自己合并/调试。 */
    std::vector<OcrBlock> detectBlocks(const cv::Mat& bgr);

    /** 视觉行合并（移植自旧 ocr.py._merge_to_lines）。 */
    static std::string mergeToLines(const std::vector<OcrBlock>& blocks);

    /** 读取图片文件为 BGR；失败返回空 Mat。 */
    static cv::Mat imreadBgr(const std::string& path);

    const OcrConfig& config() const { return cfg_; }

private:
    std::unique_ptr<class RapidOcrImpl> impl_;
    OcrConfig cfg_;
};
