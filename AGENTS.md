# AGENTS.md — 拾字 SnapText

极简本地截图 + 本地 onnx OCR 工具（Linux X11 / KDE Plasma）。不是 git 仓库，无
requirements.txt，无测试/构建配置。

## 运行与依赖

- 运行：`python3 snaptext.py`（需 X11 `DISPLAY`，本机 `:0`）。验证改动用
  `python3 -m py_compile snaptext.py` + 手动起托盘窗口。
- **全部依赖装系统 Python 3.14.6 用户 site-packages（`~/.local/...`），不用 venv**
  （符合 `/home/aheng/AGENTS.md` 的机器策略）。已装：PySide6 6.11.1、
  rapidocr-onnxruntime 1.2.3、onnxruntime 1.28.0、opencv-python 5.0.0.93、numpy 2.4.1。
- 装新依赖走 `pip3 install --user --break-system-packages`，默认走 NJU PyPI 镜像
  （`/etc/pip.conf`）。

## 模型（本地 onnx，无下载）

- OCR 用 `rapidocr_onnxruntime`。**模型直接打包在 wheel 里**（包内
  `models/`：ch_PP-OCRv3_det/rec_infer.onnx、ch_ppocr_mobile_v2.0_cls_infer.onnx），
  首次调用即本地加载，**不联网下载、无镜像问题**。不要把模型丢进项目目录或重下。
- 当前实现每张图都新建 `RapidOCR()` 实例（见 `OcrWorker.run`），首帧冷启动慢；
  若要提速可复用单例。

## 现状：单文件单体

`snaptext.py` 一个文件装下全栈，按本机运维备忘（`/home/aheng/AGENTS.md`）中的
RapidOCR 用法实现：

- **全局热键**：`GlobalHotkey` 用 ctypes 直调 libX11 `XGrabKey`，零额外依赖。
  Alt+X（keysym `x` + Mod1Mask=8）＝截图+存图+复制图片；Alt+C（`c`）＝截图+存图+OCR+
  复制文字。**X11 专属，Wayland 下不工作**。
- **截图**：`grabWindow(0)` 抓主屏 → `Selector` 全屏半透明拉框 overlay（最小 5×5px，
  Esc 取消）。
- **落盘**：`~/.snaptext/img/`（png）、`~/.snaptext/text/`（txt），文件名
  `YYYYMMDD_HHMMSS_XXX`。
- **OCR**：QThread 后台跑，经临时 png 喂 RapidOCR，结果 `\n` 拼接，成功自动复制到
  剪贴板 + 弹结果窗（可再复制/关闭）。
- 主窗口是 `Qt.Tool | WindowStaysOnTopHint` 无边框小窗，关闭时释放热键。

## 目标架构（拆分成独立本地 py，按序做）

1. **ocr 驱动独立**：图片 → 文本的最小模块（纯 onnx，不依赖 Qt/UI），本地独立 py。
2. **ui 独立**：选区 + 结果窗，不掺热键/OCR 逻辑。
3. **快捷键独立**：XGrabKey 热键模块（保持 X11 实现）。
4. **最后起托盘**：常驻托盘图标替代现在的小窗口。

拆分时保持各模块接口简单可单独跑（ocr 模块应能从命令行吃一张图吐文本验证）。
