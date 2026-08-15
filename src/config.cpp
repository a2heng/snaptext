#include "config.h"

#include <cctype>
#include <fstream>
#include <map>
#include <mutex>
#include <sstream>
#include <vector>

namespace cfg {
namespace {

std::once_flag g_once;
std::map<std::string, std::string> g_str;
std::map<std::string, int> g_int;
std::map<std::string, bool> g_bool;

// X11 modifier mask
const std::map<std::string, unsigned> kModMask = {
    {"shift", 1}, {"ctrl", 4}, {"alt", 8}, {"super", 64},
};

std::string trim(const std::string& s) {
    size_t b = 0, e = s.size();
    while (b < e && std::isspace(static_cast<unsigned char>(s[b]))) ++b;
    while (e > b && std::isspace(static_cast<unsigned char>(s[e - 1]))) --e;
    return s.substr(b, e - b);
}

bool parseBool(const std::string& v, bool& out) {
    std::string s = v;
    for (auto& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    if (s == "true" || s == "1" || s == "yes" || s == "on") { out = true; return true; }
    if (s == "false" || s == "0" || s == "no" || s == "off") { out = false; return true; }
    return false;
}

bool parseHexColor(const std::string& v) {
    if (v.size() != 7 || v[0] != '#') return false;
    for (size_t i = 1; i < v.size(); ++i) {
        if (!std::isxdigit(static_cast<unsigned char>(v[i]))) return false;
    }
    return true;
}

void validate(const std::string& key, const std::string& val) {
    if (key == "data_dir" || key == "lock_path" || key == "hotkey_image" ||
        key == "hotkey_ocr" || key == "esc_key" || key == "det_limit_type" ||
        key == "select_border_color") {
        if (!val.empty()) g_str[key] = val;
    } else if (key == "det_limit_side_len" || key == "select_min_size" ||
               key == "select_mask_alpha" || key == "notify_ms") {
        try {
            int iv = std::stoi(val);
            bool ok = false;
            if (key == "det_limit_side_len") ok = iv >= 64;
            else if (key == "select_min_size") ok = iv >= 1;
            else if (key == "select_mask_alpha") ok = iv >= 0 && iv <= 255;
            else if (key == "notify_ms") ok = iv >= 0;
            if (ok) g_int[key] = iv;
        } catch (...) {
        }
    } else if (key == "save_images" || key == "prewarm_ocr") {
        bool bv = false;
        if (parseBool(val, bv)) g_bool[key] = bv;
    }
    // 其余未知键忽略；拼错键名 = 回退默认
}

}  // namespace

const Defaults& defaults() {
    static const Defaults d;
    return d;
}

void load(const std::string& filePath) {
    std::call_once(g_once, [&]() {
        const Defaults& d = defaults();
        g_str["data_dir"] = d.dataDir;
        g_str["lock_path"] = d.lockPath;
        g_str["hotkey_image"] = d.hotkeyImage;
        g_str["hotkey_ocr"] = d.hotkeyOcr;
        g_str["esc_key"] = d.escKey;
        g_str["det_limit_type"] = d.detLimitType;
        g_str["select_border_color"] = d.selectBorderColor;
        g_int["det_limit_side_len"] = d.detLimitSideLen;
        g_int["select_min_size"] = d.selectMinSize;
        g_int["select_mask_alpha"] = d.selectMaskAlpha;
        g_int["notify_ms"] = d.notifyMs;
        g_bool["save_images"] = d.saveImages;
        g_bool["prewarm_ocr"] = d.prewarmOcr;

        std::ifstream in(filePath);
        if (!in) return;
        std::string line;
        while (std::getline(in, line)) {
            size_t hash = line.find('#');
            if (hash != std::string::npos) line = line.substr(0, hash);
            line = trim(line);
            if (line.empty()) continue;
            size_t eq = line.find('=');
            if (eq == std::string::npos) continue;
            std::string key = trim(line.substr(0, eq));
            std::string val = trim(line.substr(eq + 1));
            if (!key.empty()) validate(key, val);
        }
    });
}

const std::string& str(const char* key) {
    static const std::string empty;
    auto it = g_str.find(key);
    return it != g_str.end() ? it->second : empty;
}

int int_(const char* key) {
    auto it = g_int.find(key);
    return it != g_int.end() ? it->second : 0;
}

bool bool_(const char* key) {
    auto it = g_bool.find(key);
    return it != g_bool.end() ? it->second : false;
}

Hotkey parseHotkey(const std::string& spec) {
    Hotkey hk;
    std::vector<std::string> parts;
    std::istringstream ss(spec);
    std::string p;
    while (std::getline(ss, p, '+')) {
        std::string t = trim(p);
        if (!t.empty()) parts.push_back(t);
    }
    if (parts.empty()) return hk;
    std::string key = parts.back();
    for (auto& c : key) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    unsigned mods = 0;
    for (size_t i = 0; i + 1 < parts.size(); ++i) {
        std::string m = parts[i];
        for (auto& c : m) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        auto it = kModMask.find(m);
        if (it == kModMask.end()) return hk;  // 未知修饰键
        mods |= it->second;
    }
    hk.key = key;
    hk.mods = mods;
    hk.valid = !key.empty();
    return hk;
}

std::string hotkeyDisplay(const std::string& spec) {
    std::string out;
    std::istringstream ss(spec);
    std::string p;
    bool first = true;
    while (std::getline(ss, p, '+')) {
        std::string t = trim(p);
        if (t.empty()) continue;
        if (!first) out += "+";
        first = false;
        std::string low = t;
        for (auto& c : low) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        if (kModMask.count(low)) {
            if (!low.empty()) low[0] = static_cast<char>(std::toupper(static_cast<unsigned char>(low[0])));
            out += low;
        } else {
            if (t.size() == 1) {
                t[0] = static_cast<char>(std::toupper(static_cast<unsigned char>(t[0])));
            }
            out += t;
        }
    }
    return out;
}

}  // namespace cfg
