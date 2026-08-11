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

## 现状：模块化拆分已完成

已从单文件拆成四个独立 py，**这是 git 仓库（main 分支）**，改动提交后可直接
`git log`/`git diff` 查看修改路径。无 requirements.txt、无测试/构建配置（无 CI）。

- **`ocr.py`**：图片 → 文本最小模块（纯 onnx，**不依赖 Qt**）。`OcrEngine`
  惰性建全局唯一 `RapidOCR` 单例复用（首帧冷启动约 0.7s）。接口
  `recognize_path(path)->str` / `recognize(img: BGR ndarray)->str`，失败抛
  `RuntimeError`。可命令行单跑：`python3 ocr.py <图片>`（stdout 吐文本，失败
  stderr+非零码）。
- **`ui.py`**：只含 Qt/UI。`grab_screen()`（抓**可用区域**=屏幕减系统面板，避免
  选区与 KDE 底栏错位/双底栏）、`Selector`（全屏拉框 overlay，几何与抓图同取
  `availableGeometry()`，`selected(QRect)`/`cancelled()` 信号，5×5 最小选区，Esc
  取消，小选区也 emit cancelled）。**无结果弹窗**（不再有 ResultDlg）。
- **`hotkey.py`**：`GlobalHotkey(key, mods, on_press)`，ctypes 直调 libX11
  `XGrabKey`，**X11 专属，Wayland 下不工作**。`on_press` 在轮询线程回调，入口需
  用跨线程信号 marshal 到 GUI 线程。**不依赖 Qt**。可重复调用 `release()`。
- **`snaptext.py`**：入口，接线三个模块。**两个快捷键都=截图+存图**：Alt+X
  （keysym `x` + Mod1Mask=8）＝截图+存图+复制图片；Alt+C（`c`）＝截图+存图+OCR+
  复制文字。**全程无确认弹窗**，结果走托盘非阻塞气泡（`tray.notify`）。热键回调
  跑在 X 轮询线程，经 `hotkey_pressed` 信号 queued 到 GUI 线程。`OcrWorker` 复用
  已保存的 png 喂 `OcrEngine`，QThread 后台跑。**托盘模式，MainWin 不 show**；
  单实例锁（`fcntl.flock`，多开会抢同一 XGrabKey 致热键失效）。

## Xlib 热键踩过的坑（hotkey.py 已修，改它时勿回退）

- **`XNextEvent` 按 union `XEvent` 拷贝 192 字节**，不是 `XKeyEvent`（96B）。只分配
  96B 缓冲每次消费事件都越界写坏堆 → 退出 GC 时 `free(): invalid size` / `_Py_Dealloc`
  段错误（间歇）。必须用 `XEventBuf`（XKeyEvent + pad 到 192B）占位再读字段。
- **`XGrabKey` 恒返回 1**，不是状态码；注册成败经 error handler + `XSync` 同步判断
  （`_x_grab_ok`）。用返回值判断会永远"注册失败"。
- 轮询线程与主线程并发访问同一 Display，模块加载时先调 `XInitThreads()`。
- `release()` 必须 join 轮询线程、持有 error handler 回调引用，否则解释器收尾 GC
  崩溃。

## PySide6 / 高分屏踩过的坑（已修，别回退）

- **4K 屏 dpr=2**：`grabWindow(0)` 返回设备像素图（3840×2160），窗口/鼠标坐标是
  逻辑（1920×1080）。Select 画布 source rect 和 `_on_selected` 拷图 rect 都必须乘
  dpr，否则选区显示巨大/位置错位、存图错裁。
- **QThread worker 要存 self 保持强引用**：PySide6 对"纯 Python 方法槽"不持强引用，
  `OcrWorker` 只作局部变量会在作用域结束后被 GC，`started→run` 永不触发、txt 不落盘。
- **线程 finished 后 `deleteLater` 会删 C++ 对象**，再访问 `_ocr_thread.isRunning()`
  崩 `RuntimeError`；finished 时把 `_ocr_thread` 置 None。
- **弹窗期间保持 `_busy`**：否则弹窗开着时再按热键会叠全屏选区遮罩，看起来程序
  "未响应/关不掉"。`ResultDlg` 关闭统一走 `reject()` 保证 `exec()` 返回。
- **单实例锁**：多开实例抢同一 XGrabKey，热键随机失效。`acquire_single_instance()`。

## 运行与验证

- 运行：`python3 snaptext.py`（需 X11 `DISPLAY`，本机 `:0`）。**单实例**：再开会被
  拦截退出。
- 验证：`python3 -m py_compile *.py`；`QT_QPA_PLATFORM=offscreen` 可无界面 import；
  用 `xdotool key alt+x` 注入真实热键测试（注意会弹选区遮罩）；
  严格内存检查用 `PYTHONMALLOC=malloc`（pymalloc 会掩盖堆损坏）。
  清理测试残留实例：`pkill -f '[s]naptext.py'`（带方括号防误杀自身命令）。
- **全部依赖装系统 Python 3.14.6 用户 site-packages（`~/.local/...`），不用 venv**
  （符合 `/home/aheng/AGENTS.md` 的机器策略）。已装：PySide6 6.11.1、
  rapidocr-onnxruntime 1.2.3、onnxruntime 1.28.0、opencv-python 5.0.0.93、numpy 2.4.1。
- 装新依赖走 `pip3 install --user --break-system-packages`，默认走 NJU PyPI 镜像
  （`/etc/pip.conf`）。

## 模型（本地 onnx，无下载）

- OCR 用 `rapidocr_onnxruntime`。**模型直接打包在 wheel 里**（包内
  `models/`：ch_PP-OCRv3_det/rec_infer.onnx、ch_ppocr_mobile_v2.0_cls_infer.onnx），
  首次调用即本地加载，**不联网下载、无镜像问题**。不要把模型丢进项目目录或重下。

## 落盘与流程

- 截图 `grabWindow(0)` 抓主屏 → `Selector` 全屏半透明拉框 overlay。
- 落盘 `~/.snaptext/img/`（png）、`~/.snaptext/text/`（txt），文件名
  `YYYYMMDD_HHMMSS_XXX`。
- OCR 结果 `\n` 拼接，成功自动复制剪贴板 + 弹结果窗（可再复制/关闭）。

## 目标架构（剩余最后一步）

1. ✅ **ocr 驱动独立**：图片 → 文本最小模块（纯 onnx，不依赖 Qt/UI），CLI 可单跑。
2. ✅ **ui 独立**：选区 + 结果窗，不掺热键/OCR 逻辑。
3. ✅ **快捷键独立**：XGrabKey 热键模块（保持 X11 实现）。
4. ⏳ **最后起托盘**：常驻托盘图标替代现在的小窗口（`tray.py`）。

拆分时保持各模块接口简单可单独跑（ocr 模块应能从命令行吃一张图吐文本验证）。
