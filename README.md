# 拾字 SnapText

极简本地截图 + 本地 onnx OCR 工具（Linux X11 / KDE Plasma）。截图、OCR 全部本地完成，模型随仓库打包，**不联网、不上传、无云依赖**。

## 功能

| 快捷键 | 动作 |
| --- | --- |
| `Alt+X` | 全屏拉框截图 → 保存 png → 复制图片到剪贴板 |
| `Alt+C` | 全屏拉框截图 → 保存 png → 本地 OCR → 保存 txt → 复制文字到剪贴板 |

- 常驻系统托盘（右键退出、左键提示热键），**全程无确认弹窗**，结果走托盘非阻塞气泡。
- 选区 **1:1 所见即所得**，覆盖全屏含系统面板（KDE 底栏也能截）。
- 单实例：多开会被拦截，避免热键冲突。

## 环境要求

- Linux + **X11**（全局热键用 XGrabKey，**Wayland 下不工作**），KDE Plasma 下测试。
- Python 3.14+。

### 依赖

依赖走系统/全局 site-packages（无 vendor、无项目内 venv）：

```bash
python3 -m pip install -r requirements.txt
```

`requirements.txt` 用新版 unified `rapidocr`（3.x，旧 rapidocr-onnxruntime 已停更）。
`ocr.py` / `snaptext.py` 顶部 `import _bootstrap; _bootstrap.activate()`——deb 产物里
把无系统包的依赖（`lib/`）插到 sys.path，源码直跑时 `lib/` 不存在 = 空操作走系统包。

## 运行与使用

```bash
python3 snaptext.py
```

- 托盘出现后，任意窗口下按 `Alt+X` / `Alt+C` 拉框即可。
- 落盘位置：
  - `~/.snaptext/img/`  `YYYYMMDD_HHMMSS_XXX.png`
  - `~/.snaptext/text/`  `YYYYMMDD_HHMMSS_XXX.txt`
- 单实例锁文件：`~/.snaptext.lock`（UUID token + flock + PID 校验）。
- 退出：托盘图标右键 → 退出。

## 配置

`config.py` 是一个**全注释配置模板**：不改它 = 保持现状（默认行为）。想改哪项，
就取消注释对应示例行、改成你要的值，重启程序生效。可调项：全局热键、数据目录、
OCR 清晰度/速度权衡（`OCR_DET_LIMIT_SIDE_LEN`）、选区样式（遮罩黑度/蓝框色/最小
选区）、`SAVE_IMAGES`（False = 结果只进剪贴板、不落盘）。配置读写在 `_config.py`
（只依赖标准库），写错名字/类型/值会**静默回退默认**并在启动 stderr 给警示。

## 开发逻辑（模块架构）

拆分为四个独立本地 py + 入口，各模块接口最小、可单独验证：

```
snaptext.py   入口：接线四模块，热键→选区→存盘→复制/OCR 流程编排
  ├── ocr.py      图片→文本（纯 onnx，Qt-free）。OcrEngine 惰性单例复用
  │               RapidOCR；模型用项目内 models/（随仓库打包，真正离线）；
  │               CLI 可单跑：python3 ocr.py <图片>
  ├── ui.py       选区 Selector（全屏 override-redirect 遮罩）+ grab_screen
  ├── hotkey.py   全局热键 GlobalHotkey（ctypes 直调 libX11 XGrabKey，Qt-free）
  ├── tray.py     托盘图标 TrayIcon（程序化图标，无外部资源）
  ├── config.py   配置模板（全注释，不改=现状）+ _config.py 读取器
  ├── _bootstrap.py  deb 产物把内置 lib/ 插到 sys.path（源码直跑=空操作）
  ├── make-icons.py  程序化生成图标（icons/ 已随仓库提交，无需重新生成）
  ├── models/     PP-OCRv6 onnx 模型（随仓库打包，官方原名，真正离线）
  └── icons/      托盘同款静态图标（png 多尺寸 + ico）
```

关键接口：

- `ocr.OcrEngine.recognize_path(path) -> str` / `recognize(img: BGR ndarray) -> str`
- `hotkey.GlobalHotkey(key, mods, on_press)`，`on_press` 在 X 轮询线程回调，需跨线程信号 marshal 到 GUI 线程
- `ui.grab_screen() -> QPixmap`、`ui.Selector(pix)`（`selected(QRect)`/`cancelled()` 信号）
- `tray.TrayIcon(parent)`（右键退出、`notify(title, msg)` 非阻塞提示）

数据流：热键(X线程) → 信号(GUI线程) → `start_select` 抓全屏 → Selector 拉框 → 存 png → 复制图片 / QThread 后台 OCR → 存 txt → 复制文本 → 托盘气泡。

## 验证方式

```bash
python3 -m py_compile *.py                      # 语法
QT_QPA_PLATFORM=offscreen python3 -c "import ui"  # 无界面 import
python3 ocr.py 某图.png                          # OCR 模块单跑
xdotool key alt+x                               # 注入真实热键（会弹选区遮罩）
PYTHONMALLOC=malloc python3 snaptext.py          # 严格内存检查（pymalloc 会掩盖堆损坏）
```

## 设计哲学

见 [`AGENTS.md`](AGENTS.md)「设计哲学」一节。

## 打包发行（deb / CI）

提供最小体积 deb 打包与 tag 触发的 CI 自动发布：

- `./pack-deb.sh`：本地手动打 deb（用 `dpkg-deb`，产出 `dist/`，约 27MB）。
  体积策略：**只装源码 + models + 无系统包的依赖**（rapidocr 纯代码 + pyclipper +
  omegaconf + antlr4，剥进 `lib/`）；PySide6/opencv/onnxruntime/numpy 等依赖走
  系统包（`Depends` 声明，按发行版选包名）。
- **模型**：PP-OCRv6 det/rec + LCNet 方向分类器（`models/` 随仓库打包，官方原名，
  真正离线）。**图标**：托盘同款静态图标（`icons/` 随仓库提交，CI 不生成）。
- GitHub Actions（`.github/workflows/build-deb.yml`）：**tag `v*` 推送触发**
  （如 `v2026.08.12.1517`），打包后自动创建 GitHub Release 并挂 deb 产物；
  也可 `workflow_dispatch` 手动触发验证。
- 版本号：tag 触发时取 `v` 后的版本号，保证 deb 与 tag 一致；本地打包取当前时间。
- 安装 deb：`sudo apt install ./snaptext-Linux-amd64-<版本>-release.deb`
  （会拉取 Depends 里的系统包）；启动命令 `snaptext`。

> 说明：deb 形态不携带 vendor/，PySide6/opencv/onnxruntime/numpy 等以系统包
> （`python3-pyside6.*` / `python3-opencv` / `python3-onnxruntime` 等）形式安装。
> rapidocr 无系统包，故把其纯 python 部分 + pyclipper/omegaconf/antlr4 打进了 deb
> `lib/`（shapely 用 numpy 公式 patch 掉了，不依赖）；模型仍随仓库 `models/` 打包。

## 为什么不内置配置界面 / 不提供打包发行

刻意不做：**本项目是 MIT 协议，直接 fork 改代码即可**。

- 常用可调项（热键、落盘路径、OCR 参数、选区样式、是否落盘）已收敛到
  `config.py`，改文件即可，无需碰代码。
- 想换图标 / 加功能 / 改模块行为，是单个模块内的小改动（`ui.py` / `tray.py` /
  `ocr.py`）。
- 不做设置界面——那是"给多数用户用"的软件才需要的复杂度。本项目面向
  "愿意改配置/改代码的人"，**保持极简，把复杂度留给你 fork 后的自由**。
- deb 打包 / CI 已提供，需要时直接打、直接发布。

## License

MIT。见 [`LICENSE`](LICENSE)。
