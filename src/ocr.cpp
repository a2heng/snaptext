#include "ocr.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <stdexcept>

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include "ocr_engine.h"

namespace {
constexpr double kPi = 3.14159265358979323846;
}

class RapidOcrImpl {
public:
    rapidocr::OcrEngine eng;
};

OcrEngine::OcrEngine(const std::string& detPath, const std::string& clsPath,
                     const std::string& recPath, const OcrConfig& cfg)
    : cfg_(cfg), impl_(std::make_unique<RapidOcrImpl>()) {
    rapidocr::OcrModelPaths paths{detPath, clsPath, recPath};
    impl_->eng.InitializeModels(paths);
}

OcrEngine::~OcrEngine() = default;

cv::Mat OcrEngine::imreadBgr(const std::string& path) {
    return cv::imread(path, cv::IMREAD_COLOR);
}

std::vector<OcrBlock> OcrEngine::detectBlocks(const cv::Mat& bgr) {
    if (bgr.empty()) {
        throw std::runtime_error("图片为空（None）");
    }
    rapidocr::OcrRunOptions opts;
    opts.useCls = cfg_.useCls;
    opts.maxSideLen = cfg_.maxSideLen;
    opts.minSideLen = cfg_.minSideLen;
    opts.limitSideLen = cfg_.limitSideLen;
    opts.limitType = cfg_.limitType;
    opts.thresh = cfg_.thresh;
    opts.boxThresh = cfg_.boxThresh;
    opts.maxCandidates = cfg_.maxCandidates;
    opts.unclipRatio = cfg_.unclipRatio;
    opts.useDilation = cfg_.useDilation;
    opts.scoreMode = cfg_.scoreMode;
    opts.mergeCodeLines = cfg_.mergeCodeLines;

    rapidocr::OcrResult res;
    try {
        res = impl_->eng.Detect(bgr, opts);
    } catch (const std::exception& e) {
        throw std::runtime_error(std::string("OCR 识别失败: ") + e.what());
    }

    std::vector<OcrBlock> out;
    out.reserve(res.textBlocks.size());
    for (const auto& tb : res.textBlocks) {
        OcrBlock b;
        for (int i = 0; i < 4; ++i) {
            b.box[i] = tb.boxPoints[i];
        }
        b.text = tb.text;
        b.score = tb.boxScore;
        out.push_back(std::move(b));
    }
    return out;
}

// ── 视觉行合并（移植自旧 ocr.py._merge_to_lines）──────────────────────────
struct Proj {
    float a0, a1, l0, l1;
    std::string text;
};

static double textAngle(const std::array<cv::Point, 4>& box) {
    std::vector<cv::Point2f> pts;
    pts.reserve(4);
    for (const auto& p : box) {
        pts.emplace_back(static_cast<float>(p.x), static_cast<float>(p.y));
    }
    cv::RotatedRect r = cv::minAreaRect(pts);
    double w = r.size.width;
    double h = r.size.height;
    double angle = r.angle;
    if (w < h) {
        angle += 90.0;
    }
    angle = std::fmod(angle, 180.0);
    if (angle > 90.0) {
        angle -= 180.0;
    }
    return angle * kPi / 180.0;
}

std::string OcrEngine::mergeToLines(const std::vector<OcrBlock>& blocks) {
    if (blocks.empty()) {
        return "";
    }

    std::vector<double> angles;
    angles.reserve(blocks.size());
    for (const auto& b : blocks) {
        angles.push_back(textAngle(b.box));
    }
    // 中位数角度（对离群稳健）
    std::sort(angles.begin(), angles.end());
    const double theta = angles[angles.size() / 2];

    const double dx = std::cos(theta), dy = std::sin(theta);
    const double nx = -std::sin(theta), ny = std::cos(theta);

    std::vector<Proj> proj;
    proj.reserve(blocks.size());
    for (const auto& b : blocks) {
        float minA = 1e30f, maxA = -1e30f, minL = 1e30f, maxL = -1e30f;
        for (const auto& p : b.box) {
            const float a = static_cast<float>(p.x * nx + p.y * ny);
            const float l = static_cast<float>(p.x * dx + p.y * dy);
            minA = std::min(minA, a);
            maxA = std::max(maxA, a);
            minL = std::min(minL, l);
            maxL = std::max(maxL, l);
        }
        proj.push_back(Proj{minA, maxA, minL, maxL, b.text});
    }
    std::stable_sort(proj.begin(), proj.end(),
                     [](const Proj& a, const Proj& b) { return a.a0 < b.a0; });

    std::vector<std::vector<Proj>> lines;
    std::vector<Proj> cur;
    for (const auto& p : proj) {
        if (!cur.empty()) {
            float curA0 = cur.front().a0;
            float curA1 = cur.front().a1;
            for (const auto& c : cur) {
                curA0 = std::min(curA0, c.a0);
                curA1 = std::max(curA1, c.a1);
            }
            const float overlap = std::min(p.a1, curA1) - std::max(p.a0, curA0);
            const float span = std::min(p.a1 - p.a0, curA1 - curA0);
            if (overlap > 0.0f && overlap >= span * 0.6f) {
                cur.push_back(p);
                continue;
            }
        }
        if (!cur.empty()) {
            lines.push_back(std::move(cur));
            cur.clear();
        }
        cur.push_back(p);
    }
    if (!cur.empty()) {
        lines.push_back(std::move(cur));
    }

    std::string out;
    for (auto& ln : lines) {
        std::stable_sort(ln.begin(), ln.end(),
                         [](const Proj& a, const Proj& b) { return a.l0 < b.l0; });
        for (std::size_t i = 0; i < ln.size(); ++i) {
            if (i > 0) {
                out += ' ';
            }
            out += ln[i].text;
        }
        out += '\n';
    }
    if (!out.empty() && out.back() == '\n') {
        out.pop_back();
    }
    return out;
}

std::string OcrEngine::recognize(const cv::Mat& bgr) {
    return mergeToLines(detectBlocks(bgr));
}

std::string OcrEngine::recognizePath(const std::string& path) {
    cv::Mat img = imreadBgr(path);
    if (img.empty()) {
        throw std::runtime_error("无法读取图片: " + path);
    }
    return recognize(img);
}
