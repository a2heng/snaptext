# 拾字 SnapText

极简本地截图 + 本地 onnx OCR 工具（C++/Qt6，Linux **X11 / Wayland** 通用）。截图、
OCR 全部本地完成，模型随仓库打包，**不联网、不上传、无云依赖**。

## 功能

| 快捷键 | 动作 |
| --- | --- |
| `Alt+X` | 全屏拉框截图 → 保存 png → 复制图片到剪贴板 |
| `Alt+C` | 全屏拉框截图 → 保存 png → 本地 OCR → 保存 txt → 复制文字到剪贴板 |

- 常驻系统托盘（右键退出、左键提示热键），**全程无确认弹窗**，结果走托盘非阻塞气泡。
- 选区 **1:1 所见即所得**，覆盖全屏含系统面板（KDE 底栏也能截）。
- 单实例：多开会被拦截，避免热键冲突。
- **全局热键按会话自适应**：
  - X11：`XGrabKey`（原生，含 NumLock/CapsLock 变体、防抖）。
  - Wayland：`xdg-desktop-portal GlobalShortcuts`（跨合成器标准接口，KDE Plasma 6+ /
    GNOME 48+ / Hyprland 均支持）。后端不可用时回退命令行触发（见下）。

## 环境要求

- Linux + Qt6（Widgets/DBus/Network）+ OpenCV + X11，KDE Plasma 6 下测试。
- 高分屏：选区/裁剪按**有效 dpr = portal 图物理尺寸 ÷ 屏逻辑几何**换算，KWin 分数
  缩放（150% 等）也正确。

## 构建与运行

```bash
# 1. 拉取 onnxruntime 预编译包（无发行版系统包，产物不入 git）
bash scripts/fetch-onnxruntime.sh

# 2. 构建
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j

# 3. 运行（托盘模式，无主窗口）
./build/snaptext
```

依赖：`qt6-base-dev libopencv-dev libx11-dev`（Debian/Ubuntu 包名）。

- 落盘位置：
  - `~/.snaptext/img/`  `YYYYMMDD_HHMMSS_XXX.png`
  - `~/.snaptext/text/`  `YYYYMMDD_HHMMSS_XXX.txt`
- 单实例锁文件：`~/.snaptext.lock`（UUID token + flock + PID 校验）。
- 退出：托盘图标右键 → 退出。

### OCR CLI 单跑

```bash
./build/snaptext-ocr <图片>   # stdout 输出识别文字，失败 stderr+非零码
```

### 命令行触发（Wayland 后端不可用时的兜底）

```bash
snaptext --ocr    # 触发一次截图+OCR（派发给常驻进程，无常驻则启动并触发一次）
snaptext --img    # 触发一次截图+复制图片
```

可在自己的合成器里把快捷键绑到这两条命令（KDE 系统设置 / GNOME 设置 / Sway
bindsym / Hyprland bind…）。

## 配置

程序启动时读取**可选的 `config.conf`**（放在可执行文件旁或当前目录），全注释模板、
不改 = 现状。改哪项就写 `key=value`。可调项：全局热键（`hotkey_image`/`hotkey_ocr`/
`esc_key`）、数据目录（`data_dir`）、OCR 清晰度/速度权衡（`det_limit_side_len`）、
选区样式（遮罩黑度/蓝框色/最小选区）、`save_images`（False = 结果只进剪贴板、不落
盘）。写错名字/类型/值会**静默回退默认**并在启动 stderr 给警示。

完整配置项见 `src/config.cpp` 的 `DEFAULTS`。也可用环境变量 `SNAPTEXT_MODELS_DIR`
指定模型目录。

## 开发逻辑（模块架构，C++/Qt6）

`src/` 按职责拆成独立模块，接口最小、可单独验证：

```
src/main.cpp            入口：单实例锁 + --ocr/--img 派发 + GNOME gsettings 注册
  ├── app.cpp           流程编排：热键→抓图→选区→存盘/复制/OCR→托盘气泡
  ├── ui.cpp            Selector 拉框遮罩（X11 override-redirect / Wayland 普通窗）
  ├── portal.cpp        Wayland 截屏：xdg-desktop-portal Screenshot（非交互）
  ├── globalshortcut.cpp Wayland 热键：GlobalShortcuts portal（img/ocr 两条）
  ├── hotkey.cpp        X11 热键：XGrabKey（轮询线程 + lock 变体 + 防抖）
  ├── ocr.cpp           onnx OCR（vendor/rapidocr），视觉行合并
  ├── config.cpp        配置读取（可选 config.conf，仅标准库）
  ├── tray.cpp          托盘图标 + 非阻塞气泡
  └── ipc.cpp           单实例 unix socket（--ocr/--img 派发）
```

数据流：热键(X线程/portal Activated) → GUI 线程 → 抓全屏 → Selector 拉框 → 存 png
→ 复制图片 / 后台线程 OCR → 存 txt → 复制文本 → 托盘气泡。

## 设计哲学

见 [`AGENTS.md`](AGENTS.md)「设计哲学」一节。

## 打包发行（deb / CI）

- `./pack-deb.sh`：本地手动打 deb（产出 `dist/`，约 35MB）。体积策略：**Qt6/OpenCV/
  X11 走系统包（Depends 声明）**；onnxruntime 无跨发行版统一系统包，随包内置到
  `/opt/snaptext/lib`（启动脚本设 `LD_LIBRARY_PATH`）。
- **模型**：PP-OCRv6 det/rec + LCNet 方向分类器（`models/` 随仓库打包，官方原名，
  真正离线）。**图标**：托盘同款静态图标（`icons/` 随仓库提交，CI 不生成）。
- **Wayland 热键依赖 desktop 文件**：deb 安装
  `io.github.a2heng.snaptext.desktop`（文件名 = GlobalShortcuts 的 app_id，勿改名），
  否则 portal `Registry.Register` 报 "App info not found"、热键绑定失败。
- GitHub Actions（`.github/workflows/build-deb.yml`）：**tag `v*` 推送触发**
  （如 `v2026.08.15.2130`），在 `ubuntu:latest` 容器装 Qt6/OpenCV 构建后自动创建
  GitHub Release 并挂 deb 产物；也可 `workflow_dispatch` 手动触发验证。
- 版本号：tag 触发时取 `v` 后的版本号，保证 deb 与 tag 一致；本地打包取当前时间。
- 安装 deb：`sudo apt install ./snaptext-Linux-amd64-<版本>-release.deb`
  （会拉取 Depends 里的系统包）；启动命令 `snaptext`。

## 为什么不内置配置界面 / 不提供打包发行

刻意不做：**本项目是 MIT 协议，直接 fork 改代码即可**。

- 常用可调项（热键、落盘路径、OCR 参数、选区样式、是否落盘）已收敛到 `config.conf`，
  改文件即可，无需碰代码。
- 想换图标 / 加功能 / 改模块行为，是单个模块内的小改动（`src/ui.cpp` /
  `src/ocr.cpp` 等）。
- 不做设置界面——那是"给多数用户用"的软件才需要的复杂度。本项目面向
  "愿意改配置/改代码的人"，**保持极简，把复杂度留给你 fork 后的自由**。
- deb 打包 / CI 已提供，需要时直接打、直接发布。

## License

MIT。见 [`LICENSE`](LICENSE)。
