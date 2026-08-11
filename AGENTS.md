# AGENTS.md — 拾字 SnapText

极简本地截图 + 本地 onnx OCR 工具（Linux X11 / KDE Plasma）。**git 仓库**
（main 分支，GitHub: `a2heng/snaptext`），无 requirements.txt、无测试/构建配置
（无 CI）。改动提交后直接 `git log`/`git diff` 看修改路径。

## 运行与依赖

- 运行：`python3 snaptext.py`（需 X11 `DISPLAY`，本机 `:0`）。**单实例**：再开被拦截。
- **全部依赖装系统 Python 3.14.6 用户 site-packages（`~/.local/...`），不用 venv**
  （符合 `/home/aheng/AGENTS.md` 的机器策略）。已装：PySide6 6.11.1、
  rapidocr-onnxruntime 1.2.3、onnxruntime 1.28.0、opencv-python 5.0.0.93、numpy 2.4.1。
- 装新依赖走 `pip3 install --user --break-system-packages`，默认走 NJU PyPI 镜像
  （`/etc/pip.conf`）。

## 模型（本地 onnx，无下载）

- OCR 用 `rapidocr_onnxruntime`。**模型直接打包在 wheel 里**（包内
  `models/`：ch_PP-OCRv3_det/rec_infer.onnx、ch_ppocr_mobile_v2.0_cls_infer.onnx），
  首次调用即本地加载，**不联网下载、无镜像问题**。不要把模型丢进项目目录或重下。
- `OcrEngine` 惰性建全局唯一 `RapidOCR` 单例复用（首帧冷启动约 0.7s）。

## 模块架构

拆成四个独立本地 py + 入口，各模块接口最小、可单独验证：

- **`ocr.py`**：图片 → 文本最小模块（纯 onnx，**不依赖 Qt**）。接口
  `recognize_path(path)->str` / `recognize(img: BGR ndarray)->str`，失败抛
  `RuntimeError`。可命令行单跑：`python3 ocr.py <图片>`（stdout 吐文本，失败
  stderr+非零码）。
- **`ui.py`**：只含 Qt/UI。`grab_screen()`（抓全屏含系统面板）、`Selector`
  （全屏拉框 overlay，**`X11BypassWindowManagerHint`** 绕过 WM 盖住 KDE 底栏，
  `selected(QRect)`/`cancelled()` 信号，5×5 最小选区，小选区也 emit cancelled）。
  **无结果弹窗**（已删 ResultDlg）。override-redirect 收不到键盘事件，Esc 由
  入口侧全局热键兜底。
- **`hotkey.py`**：`GlobalHotkey(key, mods, on_press)`，ctypes 直调 libX11
  `XGrabKey`，**X11 专属，Wayland 下不工作**。`on_press` 在轮询线程回调，入口需
  用跨线程信号 marshal 到 GUI 线程。**不依赖 Qt**。可重复调用 `release()`。
- **`snaptext.py`**：入口，接线四个模块。**两个快捷键都=截图+存图**：Alt+X
  （keysym `x` + Mod1Mask=8）＝截图+存图+复制图片；Alt+C（`c`）＝截图+存图+OCR+
  复制文字。**全程无确认弹窗**，结果走托盘非阻塞气泡（`tray.notify`）。热键回调
  跑在 X 轮询线程，经 `hotkey_pressed` 信号 queued 到 GUI 线程。`OcrWorker` 复用
  已保存的 png 喂 `OcrEngine`，QThread 后台跑。**托盘模式，MainWin 不 show**；
  `setQuitOnLastWindowClosed(False)`（选区遮罩关闭不误退）；单实例锁
  `acquire_single_instance()`。
- **`tray.py`**：`TrayIcon`（程序化图标无资源文件），右键退出、左键提示热键、
  `notify(title, msg)` 非阻塞气泡。

数据流：热键(X线程) → 信号(GUI线程) → `start_select` 抓全屏 → Selector 拉框 →
存 png → 复制图片 / QThread 后台 OCR → 存 txt → 复制文本 → 托盘气泡。

## 设计哲学

1. **极简**：一个功能只做一个，不堆配置不堆依赖。每层"最小可用"，够用即止。
2. **本地优先**：一切本地处理。模型打包在依赖 wheel 里，不下载、不上传、无网络
   依赖。剪贴板即"输出"，结果落盘即"存档"。
3. **模块独立**：每层独立 py、接口最小、可单独跑验证（ocr 能 CLI 单跑；ui 可
   offscreen import；hotkey 不依赖 Qt）。Ui/OCR/hotkey/tray 互相不掺。
4. **零摩擦交互**：快捷键直达结果，无确认弹窗、无多步骤。反馈走托盘非阻塞气泡，
   不打断当前工作。
5. **所见即所得（1:1）**：选区覆盖全屏含系统面板，抓什么显示什么、存什么。高分屏
   dpr 显式换算，坐标空间不含糊。
6. **稳健优先于花哨**：单实例锁防热键冲突；线程/GC/高分屏/Xlib 等坑全部显式
   处理并把结论写进本文件，改代码勿回退。

## 实践（怎么做到上述哲学）

- **拆层顺序**：ocr 驱动独立 → ui 独立 → 热键独立 → 托盘收尾。每步保持模块
  "可单独跑"再往下拆。
- **验证习惯**：`python3 -m py_compile *.py` →
  `QT_QPA_PLATFORM=offscreen` 无界面 import → 模块单跑 → `xdotool` 注入真实热键
  → `PYTHONMALLOC=malloc` 严格内存检查（pymalloc 会掩盖堆损坏）。改 GUI/热键必须
  走真实进程 e2e（拖拽用 `xdotool mousemove ... mousedown 1 ... mousemove ... mouseup 1`
  带 sleep 才稳定）。
- **踩坑即沉淀**：每修一个非显而易见的问题，把结论写进 AGENTS.md（本文件即"踩坑
  日志"），同时作为 git commit message。
- **清理测试残留**：`pkill -9 -f 'snaptext[.]py'`（用 `[.]` 转义避免 pkill 匹配到
  自身命令；注意别在命令里再写裸 `snaptext.py` 字样）。
- **单实例测试**：`~/.snaptext.lock` 持锁为唯一实例；清数据目录（`~/.snaptext`）
  不影响锁（锁在 `~/.snaptext.lock`）。

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
  "未响应/关不掉"。
- **托盘 app 必须 `setQuitOnLastWindowClosed(False)`**：选区遮罩作为唯一可见窗口
  关闭时会误触发 quit。
- **override-redirect 窗口收不到键盘**：Esc 用临时全局热键兜底。
- **单实例锁**：多开实例抢同一 XGrabKey，热键随机失效。锁在数据目录外
  （`~/.snaptext.lock`），flock + 固定 UUID token（`<uuid>_SnapText`）+ PID 存活校验。

## 落盘与流程

- 截图 `grabWindow(0)` 抓全屏 → `Selector` 全屏半透明拉框 overlay（覆盖系统面板）。
- 落盘 `~/.snaptext/img/`（png）、`~/.snaptext/text/`（txt），文件名
  `YYYYMMDD_HHMMSS_XXX`。
- OCR 结果 `\n` 拼接，成功自动复制剪贴板；反馈走托盘非阻塞气泡（无弹窗）。
