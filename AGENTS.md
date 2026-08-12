# AGENTS.md — 拾字 SnapText

极简本地截图 + 本地 onnx OCR 工具（Linux X11 / KDE Plasma）。**git 仓库**
（main 分支，GitHub: `a2heng/snaptext`），有 `requirements.txt`、tag 触发 CI
（`.github/workflows/build-deb.yml`）。改动提交后直接 `git log`/`git diff`
看修改路径。

## 运行与依赖

- 运行：`python3 snaptext.py`（需 X11 `DISPLAY`，本机 `:0`）。**单实例**：再开被拦截。
- **依赖走系统/全局 site-packages，无 vendor、无项目内 venv**：
  `python3 -m pip install -r requirements.txt` 装一次即可（PySide6 + OCR 链）。
  `requirements.txt` 用新版 unified `rapidocr`（3.x，旧 rapidocr-onnxruntime 停更）。
- `_bootstrap.py`：deb 产物里把项目内置 `lib/`（无系统包的 rapidocr/shapely/
  pyclipper/omegaconf/antlr4）插到 `sys.path`；源码直跑时 `lib/` 不存在 = 空操作，
  走系统包。`ocr.py` / `snaptext.py` 顶部 `import _bootstrap; _bootstrap.activate()`。

## 模型（本地 onnx，随仓库打包）

- **模型已直接打进项目 `models/` 目录**（随 git 提交，共 31MB：PP-OCRv6
  det/rec + LCNet 方向分类器，**保留官方文件名**，真正离线、不依赖 wheel 内置模型）。
- `ocr.py` 的 `_MODELS` 指向项目内模型，经 `RapidOCR(params={"Det.model_path":...,
  "Rec.model_path":..., "Cls.model_path":...})` 加载；指定 model_path 即离线、不触发下载。
- **`Cls.ocr_version` 必须设 `PPOCRV5`**：rapidocr 3.x 的 cls 形状表只有 v4/v5
  （`CLS_SHAPE_BY_OCR_VERSION`），v6 没有自己的 cls、复用 v5 的 LCNet（输入
  `[3,80,160]`）；设 v6 会 KeyError，设 v4 维度不匹配报错。Det/Rec 设 `PPOCRV6`。
- **更新模型时直接替换 `models/` 下文件即可，勿改名**（官方原名，见下「模型版本」节）。
- **模型版本选 v6（2026-08-12 实测对比）**：v5 vs v6 在同测试板/代码注释/难字/
  多场景实测，v6 在 9 项里 6 项胜出（代码注释保真、路径、键值对空格、邮箱、小字、
  速度），仅生僻字略逊；体积 +9M（共 31M）。生僻字对屏幕 OCR 使用频率低，故取 v6。
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
  `acquire_single_instance()`。**忙时热键入队（2026-08-12）**：选区/OCR 进行中再按
  热键不再丢弃，FIFO 排队（`_pending`），当前任务收尾（`_finish_cancel`/img 完成/
  `_on_ocr_done`）统一走 `_start_next_or_idle()` 自动执行下一个。**启动预热 onnx
  （2026-08-12）**：`main` 里后台线程调 `ocr._get_engine()` 提前完成模型加载
  （~0.8s），首次按键 OCR 即快；预热线程池与后续 OCR 线程共享进程级单例，无额外开销。
- **`tray.py`**：`TrayIcon`（程序化图标无资源文件），右键退出、左键提示热键、
  `notify(title, msg)` 非阻塞气泡。热键展示文案由入口传入（跟随 config.py 改热键）。
- **`config.py` / `_config.py`（2026-08-12）**：`config.py` 是**全注释配置模板**
  （不改=现状）；`_config.py` 只依赖标准库，import 时 ast 解析 config.py 收集
  白名单内顶层赋值，未覆盖项用内置默认。见「配置」节。

数据流：热键(X线程) → 信号(GUI线程) → `start_select` 抓全屏 → Selector 拉框 →
存 png → 复制图片 / QThread 后台 OCR → 存 txt → 复制文本 → 托盘气泡。

## 设计哲学

1. **极简**：一个功能只做一个，不堆配置不堆依赖。每层"最小可用"，够用即止。
2. **模块独立**：每层独立 py、接口最小、可单独跑验证（ocr 能 CLI 单跑；ui 可
   offscreen import；hotkey 不依赖 Qt）。Ui/OCR/hotkey/tray 互相不掺。
3. **零摩擦交互**：快捷键直达结果，无确认弹窗、无多步骤。反馈走托盘非阻塞气泡，
   不打断当前工作。
4. **所见即所得（1:1）**：选区覆盖全屏含系统面板，抓什么显示什么、存什么。高分屏
   dpr 显式换算，坐标空间不含糊。
5. **稳健优先于花哨**：单实例锁防热键冲突；线程/GC/高分屏/Xlib 等坑全部显式
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
- **NumLock/CapsLock 开启时被动 grab 匹配不上 → 热键静默失效（2026-08-12 根因）**：
  XGrabKey 只精确匹配注册的 modifiers 组合，**X server 不会自动为被动 grab 注册
  lock 变体**。本机 NumLock 常开，按 Alt+X 实际 state=0x18（Mod1+Mod2），而只注册
  mods=8 的 grab 匹配不上 → 热键完全失效。修法：`_lock_variants(mods)` 显式注册全部
  4 个变体（mods / mods|Caps / mods|NumLock / mods|Caps|NumLock），事件侧用
  `state & ~(LOCK|MOD2) == mods` 过滤兼容任意 lock 状态。排查时曾误判"被动 grab 全部
  失效"，实际是注册的 lock 变体不全。
- **KeyRelease 重新武装不能按 mods 过滤（2026-08-12）**：按住触发后需等 KeyRelease
  重新 arm。若 KeyRelease 也要求 `state & ~(LOCK|MOD2) == mods`，**先松 Alt 再松 X
  时 KeyRelease(X) 到达已无 Mod1（state=0），永远 re-arm 失败 → 热键只触发一次就
  永久失效**。修法：KeyRelease 只凭 keycode 重新 arm，不检查 state。
- **防抖（2026-08-12）**：按住热键时 X11 auto-repeat 连续发 KeyPress，每个都触发
  回调 → 一次长按触发几十次截图/OCR，线程堆积（实测 175 线程、CPU 766%）。修法：
  `_armed` 标志，KeyPress 触发后置 False，KeyRelease 才重新 arm，一次按键只触发一次。

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

## OCR 踩过的坑（ocr.py 已修，改它时勿回退）

- **新版 unified `rapidocr`（3.x）迁移（2026-08-12）**：旧 `rapidocr-onnxruntime`
  停更，`ocr.py` 已迁到 `from rapidocr import RapidOCR`。API 变化：
  - 参数形式从 `RapidOCR(det_model_path=...)` 改为 `RapidOCR(params={"Det.model_path":...,
    "Rec.model_path":..., "Cls.model_path":...})`（"段.键" 形式，段∈Global/Det/Cls/Rec/EngineConfig）。
  - 输出从 `(results, elapse)` 二元组改为 `RapidOCROutput(boxes, txts, scores)` 对象；
    `_to_results()` 适配成旧 `[(box,text,score),...]` 喂给 `_merge_to_lines`。
  - 枚举参数（`ocr_version`/`model_type`/`lang_type`）必须传 Enum，如
    `OCRVersion.PPOCRV6`，不能传字符串。
  - rec 从 onnx 模型内嵌字符表（`have_key()`），不会下载 dict。
- **宽高比跳过 det 的坑，新版语义变了**：旧 rapidocr_onnxruntime 对宽高比 >
  `width_height_ratio`（默认 8）的窄条**跳过 det、整图直喂 rec** → 识别为空。
  新版 rapidocr 3.x 改为 **`apply_vertical_padding` 给窄条加竖直 padding** 再走 det，
  `Global.width_height_ratio` 变成"触发 padding 的阈值"。`OCR_WIDTH_HEIGHT_RATIO=100`
  沿用（几乎不触发 padding，窄条也正常）。**注意参数是 `Global.` 前缀**，不是 `det_`。
- **det 长边封顶（性能）**：新版 rapidocr 3.x 的 det 在 `limit_type='max'` 时按
  `max_wh` 自动选 960/1500/2000 封顶，`Det.limit_side_len=960` 语义延续
  （长边封顶、32 对齐）。`Det.limit_type='max'` + `Det.limit_side_len=960` 让扁图/
  4K 都不全尺寸推理（旧版 `limit_type='min'` 会把 694×50 扁图放大成 10200×736，
  3-4 秒）。实测 4K 全屏 ~1s、扁图 ~0.5s。
- **行合并 `_merge_to_lines`（旋转稳健）**：det 按连通域出框，一行内有大间隙（标签页/
  菜单项等）会切成多个词块框 → 逐框输出"换行过频"。修复：用 `minAreaRect` 求每框
  方向角（归一到 (-90,90]，`angle%180` 后 `>90` 减 180 处理 179.5→-0.5 的环绕），
  取中位数为文本方向；把框 4 点投影到"文本方向/法线"轴，沿法线按"重叠比例>0.6
  （基准取两框中较矮者）"聚类成行，同行内沿文本方向排序空格连接。**判据要点**：紧挨
  的两行文字法线区间可能搭界 2px，但重叠比例极低（行高 27/44 时仅 7%），不会误连；
  而同一行框重叠比例 90%+。旋转/倾斜文本投影到同一法线上仍同属一行，天然稳健。
- **竖排文本是 det 能力边界**：PP-OCR det 按连通域出框，两列竖排文字被 unclip 弥合
  成一个框（angle≈0），任何后处理都无法分行。属模型固有短板，非行合并可解。

## 配置（config.py / _config.py，2026-08-12）

- `config.py` 是**全注释模板**：默认状态一个赋值都没有 → 所有项回退内置默认
  （=现状，行为与旧版本完全一致）。改配置 = 取消注释那一项示例行、改值；删行
  = 恢复该项默认。**启动时读一次，改配置需重启**。
- `_config.py` 只依赖标准库。import 时 `ast.parse` 用户文件 + `literal_eval`
  收集顶层 `名 = 值`，只在 `DEFAULTS` 白名单内的名字才生效；拼错名/类型错/
  值非法 → 该项**静默回退默认**并 stderr 警示，不影响其它项。
- **bool 校验用 `type(v) is bool`**：bool 是 int 子类，`isinstance(True, int)`
  会误把 `SAVE_IMAGES = 1` 放行；int 项也要用 `type(v) is int` 挡掉布尔。
- 热键写法 `修饰键+修饰键+键名`：shift/ctrl/alt/super 可组合（OR），键名=X11
  keysym；`parse_hotkey()` 解析成 `(keysym, mods)`、`hotkey_display()` 生成托盘
  展示文案。CapsLock/NumLock 由 hotkey.py 的 lock 变体自动兼容，不额外注册。
- `SAVE_IMAGES=False`：图片不落盘、OCR 走内存——`_on_selected` 不再存 png，
  `OcrWorker` 第二参吃 **str 路径或 QPixmap 二选一**（snaptext 的
  `_qpixmap_to_bgr` 把 QPixmap 转 BGR ndarray，`ascontiguousarray` 拷贝脱离
  QImage 生命周期，防悬空）。此时 data 目录不自动创建、txt 也不落盘，结果只进
  剪贴板。
- 配置项清单以 config.py 注释为准；新增配置项 = `DEFAULTS` + `_VALIDATORS`
  各加一条，`get(name)` 取用。

## deb 打包（pack-deb.sh，2026-08-12）

- **最小体积策略**：deb 只装 源码 + models + 少量"无系统包"依赖，PySide6/opencv/
  onnxruntime/numpy 等走系统包（Depends 声明），deb 约 27MB。
- 布局：`/opt/snaptext/{*.py, models/, lib/, snaptext.ico}` + `/usr/bin/snaptext`
  （启动脚本）+ `.desktop` + hicolor 图标 + 文档。`_bootstrap.py` 把 `lib/` 插进 sys.path。
- **剥进 lib/ 的依赖**（AOSC/Debian/Ubuntu 均无系统包）：rapidocr（弃内置 28M
  模型）+ pyclipper + omegaconf + antlr4-python3-runtime。
- **shapely 已用 numpy 公式 patch 掉（2026-08-12 精简大头）**：rapidocr 只在
  `ch_ppocr_det/utils.py` 的 `unclip` 一处用 `Polygon.area/length`（算缩放距离），
  用鞋带公式求面积 + 边长求和替代，结果完全一致（实测 0.00% 差），从而 lib/ 无需
  打包 shapely（省 ~10MB，目标机也无需系统 shapely）。改 rapidocr 版本时需重验此 patch。
- **colorlog 处理**：rapidocr 的 log.py 仅用于日志着色，打包时替换为标准库 logging
  （完整重写，非 sed 补丁——只注释 import 会留 `colorlog.ColoredFormatter` 报错）。
- **图标静态化（2026-08-12）**：`icons/`（png 多尺寸 + ico，托盘同款宋体 Black）
  随仓库提交，打包时直接拷贝，**CI 不生成图标**（少一个故障点）。需重画时跑
  `QT_QPA_PLATFORM=offscreen python3 make-icons.py` 并提交新 icons/。
- **Depends 按发行版选包名**：`SNAPTEXT_DEPS` 环境变量覆盖，否则读 `/etc/os-release`
  的 ID 选 AOSC（无 python3- 前缀）或 Debian 系（python3-*）命名。
- 版本号：tag 触发 CI 时取 `GITHUB_REF_NAME`（去 v），本地跑回退当前时间。
- **模型文件名必须保留官方原名**（PP-OCRv6_det_small.onnx / PP-OCRv6_rec_small.onnx /
  ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx），勿自定义改名。

## 落盘与流程

- 截图 `grabWindow(0)` 抓全屏 → `Selector` 全屏半透明拉框 overlay（覆盖系统面板）。
- 落盘 `~/.snaptext/img/`（png）、`~/.snaptext/text/`（txt），文件名
  `YYYYMMDD_HHMMSS_XXX`。数据目录/热键/OCR 参数/行为等均可在 config.py 调整。
- OCR 结果 `\n` 拼接，成功自动复制剪贴板；反馈走托盘非阻塞气泡（无弹窗）。
