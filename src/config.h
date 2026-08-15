#pragma once
/** 配置模块：读取 config.conf（key = value，注释 #），未覆盖项用内置默认。
 *
 * 对应旧 Python _config.py。仅标准库依赖。启动时读一次，改后重启生效。
 */
#include <map>
#include <string>

namespace cfg {

// 内置默认值（与旧 config.py 现状一致）
struct Defaults {
    std::string dataDir = "~/.snaptext";
    std::string lockPath = "~/.snaptext.lock";
    std::string hotkeyImage = "alt+x";
    std::string hotkeyOcr = "alt+c";
    std::string escKey = "Escape";
    std::string detLimitType = "max";
    int detLimitSideLen = 960;
    int selectMinSize = 5;
    int selectMaskAlpha = 100;
    std::string selectBorderColor = "#0078D7";
    bool saveImages = true;
    bool prewarmOcr = true;
    int notifyMs = 2000;
};

const Defaults& defaults();
void load(const std::string& filePath);   // 不存在则全部用默认

const std::string& str(const char* key);   // dataDir/lockPath/hotkeyImage/hotkeyOcr/escKey/detLimitType/selectBorderColor
int int_(const char* key);                 // detLimitSideLen/selectMinSize/selectMaskAlpha/notifyMs
bool bool_(const char* key);               // saveImages/prewarmOcr

// 热键写法 "alt+x" / "ctrl+shift+e" → (键名, X11 modifier mask)
struct Hotkey {
    std::string key;
    unsigned mods = 0;
    bool valid = false;
};
Hotkey parseHotkey(const std::string& spec);

// "alt+x" → 展示文案 "Alt+X"
std::string hotkeyDisplay(const std::string& spec);

}  // namespace cfg
