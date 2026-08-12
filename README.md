# 拾字 SnapText

极简本地截图 + 本地 onnx OCR 工具（Linux X11 / KDE Plasma）。截图、OCR 全部本地完成，模型直接打包在依赖里，**不联网、不上传、无云依赖**。

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

### 依赖内化（vendor/，类似项目内 venv）

依赖已内化到 `vendor/` 目录（**不进 git**），克隆后只需联网跑一次：

```bash
./setup-vendor.sh        # 安装全部默认依赖（OCR 链 + PySide6）
./setup-vendor.sh <包>…  # 追加安装任意包
```

之后完全离线运行，无需再 `pip install`。`ocr.py` / `snaptext.py` 启动时会自动
把 `vendor/` 插到 `sys.path` 最前（见 `_vendor.py`），优先加载项目内置依赖。

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

## 开发逻辑（模块架构）

拆分为四个独立本地 py + 入口，各模块接口最小、可单独验证：

```
snaptext.py   入口：接线四模块，热键→选区→存盘→复制/OCR 流程编排
  ├── ocr.py      图片→文本（纯 onnx，Qt-free）。OcrEngine 惰性单例复用
  │               RapidOCR；模型用项目内 models/（缺失回退 wheel）；
  │               CLI 可单跑：python3 ocr.py <图片>
  ├── ui.py       选区 Selector（全屏 override-redirect 遮罩）+ grab_screen
  ├── hotkey.py   全局热键 GlobalHotkey（ctypes 直调 libX11 XGrabKey，Qt-free）
  ├── tray.py     托盘图标 TrayIcon（程序化图标，无外部资源）
  ├── _vendor.py  依赖内化引导：把 vendor/ 插到 sys.path 最前
  ├── models/     三个 onnx 模型文件（随仓库打包，真正离线）
  └── vendor/     内化依赖（setup-vendor.sh 生成，不进 git）
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

## 为什么不内置热键自定义 / 不提供打包发行

刻意不做：**本项目是 MIT 协议，直接 fork 改代码、自己打包即可**。

- 热键在 `snaptext.py` 顶部就是两个元组（`MODE_IMG` / `MODE_OCR`），改 keysym
  和修饰键掩码即可，30 秒改完。
- 想换图标/改落盘路径/调 OCR 行为，都是单个模块内的小改动（`ui.py` / `tray.py` /
  `ocr.py`）。
- 不做配置文件、不做设置界面、不做打包产物——那是"给多数用户用"的软件才需要的
  复杂度。本项目面向"愿意改代码的人"，**保持极简，把复杂度留给你 fork 后的自由**。

## License

MIT。见 [`LICENSE`](LICENSE)。
