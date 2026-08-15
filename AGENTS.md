# AGENTS.md — 拾字 SnapText

极简本地截图 + 本地 onnx OCR 工具（C++/Qt6，Linux X11 / Wayland 通用）。**git 仓库**
（main 分支，GitHub: `a2heng/snaptext`），tag 触发 CI（`.github/workflows/build-deb.yml`）。
改动提交后直接 `git log`/`git diff` 看修改路径。

## C++ 版现状（2026-08-15）

- **纯 C++/Qt6 版**：`src/`（CMake 构建）覆盖 config/ocr/ui/hotkey/portal/
  globalshortcut/tray/ipc/app/main 全部模块；`build/snaptext`（主程序）与
  `build/snaptext-ocr`（OCR CLI）可构建。OCR 用 vendor 的 RapidOCR C++（与旧 Python
  rapidocr 3.x 同模型、同推理，输出逐行一致）。**旧 Python 版已全部删除**（snaptext.py/
  ui.py/ocr.py/hotkey*.py/tray.py/config.py/_config.py/_bootstrap.py/requirements.txt），
  仅保留 `make-icons.py`（图标生成工具，图标已随仓库提交）。
- **X11 与 Wayland 均端到端验证通过（2026-08-15 晚）**：
  - X11：XGrabKey 全局热键 → 抓全屏 → 选区 → 裁剪 → 存图/复制/OCR。
  - Wayland：GlobalShortcuts portal 热键 + Screenshot portal 截图 + Selector 选区 +
    裁剪（有效 dpr 换算正确）→ 存图/复制/OCR 全通。
- 本文件各「踩坑」节描述的问题与修法均适用于 C++ 版（多数按同思路移植），改代码勿回退。

## 构建与依赖

- 构建：`bash scripts/fetch-onnxruntime.sh`（拉 onnxruntime 预编译到 `third_party/`，
  产物不入 git）→ `cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j`。
- **系统依赖**（Debian/Ubuntu 包名）：`qt6-base-dev libopencv-dev libx11-dev` + 编译器
  （`build-essential cmake`）。onnxruntime 无发行版系统包，随仓库拉预编译。
- 运行：`./build/snaptext`（托盘常驻）。**单实例**：再开被拦截。

## 模型（本地 onnx，随仓库打包）

- **模型已直接打进项目 `models/` 目录**（随 git 提交，共 31MB：PP-OCRv6
  det/rec + LCNet 方向分类器，**保留官方文件名**，真正离线、不触发下载）。
- C++ 加载：`src/ocr.cpp` 的 `OcrEngine` 吃 `models/` 下三模型路径（det/rec/cls），
  vendor RapidOCR 加载，指定 model_path 即离线。
- **更新模型时直接替换 `models/` 下文件即可，勿改名**（官方原名）。
- **模型版本选 v6（2026-08-12 实测对比）**：v5 vs v6 在同测试板/代码注释/难字/
  多场景实测，v6 在 9 项里 6 项胜出（代码注释保真、路径、键值对空格、邮箱、小字、
  速度），仅生僻字略逊；体积 +9M（共 31M）。生僻字对屏幕 OCR 使用频率低，故取 v6。
- `OcrEngine` 惰性建全局唯一单例复用（首帧冷启动约 0.7s）；`main` 里可后台预热。

## 模块架构（C++/Qt6，src/）

- **`ocr.cpp` / `ocr.h`**：图片 → 文本最小模块（纯 onnx，**不依赖 Qt**）。接口
  `recognize(bgr)->str`，失败抛异常。CLI 单跑：`build/snaptext-ocr <图片>`（stdout
  吐文本，失败 stderr+非零码）。视觉行合并 `_merge_to_lines` 移植自旧 Python 版。
- **`ui.cpp`**：`grabScreen()`（X11 抓全屏含系统面板）、`Selector`（全屏拉框 overlay，
  X11 用 `X11BypassWindowManagerHint` 盖住 KDE 底栏；Wayland 用普通置顶全屏窗抢键盘
  焦点让 Esc 原生可用；`selected(QRect)`/`cancelled()` 信号，最小选区、小选区也 emit
  cancelled）。**无结果弹窗**。
- **`hotkey.cpp`**：`GlobalHotkeyX11`（X11 专属 `XGrabKey`，轮询线程 + lock 变体 +
  防抖，`onPress` 在轮询线程回调，入口 queued 到 GUI 线程）。**不依赖 Qt**。
- **`globalshortcut.cpp`**：Wayland 全局热键（`org.freedesktop.portal.GlobalShortcuts`，
  见「Wayland 通用架构」节）。`makeWaylandHotkeys(triggerImg, triggerOcr, onImg, onOcr)`
  一次会话绑定 img/ocr 两条。
- **`app.cpp`**：流程编排 + 按会话选热键后端。两个快捷键都=截图+存图：Alt+X=截图+
  存图+复制图片；Alt+C=截图+存图+OCR+复制文字。全程无确认弹窗，结果走托盘气泡。
  忙时热键入队（FIFO，`pending_`），当前任务收尾统一走 `finish()` 自动执行下一个。
- **`portal.cpp`**：Wayland 截屏（`org.freedesktop.portal.Screenshot` 非交互），
  见「Wayland 通用架构」节。
- **`tray.cpp`**：`TrayIcon`（加载静态资源 `icons/snaptext-64.png`），右键退出、左键
  提示热键、`notify(title, msg)` 非阻塞气泡。热键展示文案由入口传入。
- **`config.cpp`**：可选 `config.conf`（全注释模板、不改=现状），仅标准库，白名单
  校验、非法项静默回退默认并 stderr 警示。见「配置」节。
- **`ipc.cpp`**：单实例 unix socket（`~/.snaptext.sock`）派发 `--ocr`/`--img`。
- **`main.cpp`**：入口——单实例锁 `acquireSingleInstance`、`--ocr`/`--img` 派发、GNOME
  gsettings 自动注册快捷键（尽力而为）。

数据流：热键(X线程 / portal Activated) → GUI 线程 → `startSelect` 抓全屏 → Selector
拉框 → 存 png → 复制图片 / 后台线程 OCR → 存 txt → 复制文本 → 托盘气泡。

## Wayland 通用架构（2026-08-15，C++ 版）

**原则：只依赖跨合成器标准机制，不绑任何桌面**（曾用 kglobalaccel 做 KDE 热键、
interactive portal 选区，均已废弃，勿回退）。

- **wayland 没有统一的全局快捷键协议**（`zwp_global_shortcuts_v1` 标准里有但
  KDE/GNOME 都没实现，不可依赖），也没有应用能自行绘制全屏 overlay 的能力。
  所以热键与选区都只能走「合成器/portal 提供的标准接口」。
- **热键（跨合成器标准接口：GlobalShortcuts portal，2026-08-15 晚已打通并集成）**：
  Wayland 下全局快捷键走 `org.freedesktop.portal.GlobalShortcuts`（KDE Plasma 6+、
  GNOME 48+、Hyprland 都有后端，Electron/Chromium/OBS 均用）。`makeWaylandHotkeys()`
  一次会话绑定 `img`/`ocr` 两条快捷键，触发时 portal 发 `Activated(session_handle,
  shortcut_id, timestamp, options)` 信号 → 应用回调（GUI 线程）→ 与 X11 热键同一
  处理链（截图/OCR）。实现见 `src/globalshortcut.cpp`。
- **GlobalShortcuts 踩坑（2026-08-15 晚实测，勿回退）**：
  - **`Registry.Register(app_id, {})` 必须先行**（`org.freedesktop.host.portal.Registry`，
    portal>=1.20 要求 host 应用先声明身份）。不注册则 CreateSession 能成功但
    BindShortcuts 后端报 `org.kde.kglobalaccel.NoSuchComponent`、无 Response。
  - **app_id 必须有同名 .desktop 文件支撑**（`~/.local/share/applications/
    <app_id>.desktop` 或 `/usr/share/applications/`，deb 打包需带上）。缺了
    Register 报 `App info not found`。app id 用 `io.github.a2heng.snaptext`。
  - **`preferred_trigger` 必须 XDG 格式（大写修饰键 + xkb keysym，如 `ALT+X`）**。
    KDE 后端用 `XdgShortcut::parse`：`<Alt>X`（尖括号）解析失败、小写不行 →
    keySequence 空 → kglobalshortcutsrc 里 `img=Alt+X,none,…`（current=none）→
    绑了但**永远不触发**。格式对 + 首次绑定（new shortcut）时弹允许对话框，
    接受后 current 自动写入并生效。
  - **首次绑定弹 QuickDialog**（「应用想添加全局快捷键，允许/拒绝」）；接受后
    preferred 写入 current；拒绝则 current=none，之后可到系统设置里配。
  - **已存在（returning）的快捷键重绑不会更新 current**（Autoloading 不覆盖已有
    current）。改热键后若想强制更新，需清掉 kglobalshortcutsrc 对应段重来或去
    系统设置改。
  - BindShortcuts 同步返回实际 request_handle（QDBusObjectPath），订阅它收
    Response（勿自拼路径）。CreateSession 无同步返回值，用自拼路径
    `/…/request/{bus名去前导冒号}/{token}`（同截图踩坑 1）。
  - **a(sa{sv}) 封送**：`Q_DECLARE_METATYPE(QPair<QString,QVariantMap>)` +
    `qDBusRegisterMetaType`，传 `QVariant::fromValue(QList<ShortcutEntry>)` 而非
    `QList<QVariant>`（后者封成 `av` 类型不匹配）。
- **热键兜底（后端不可用时）**：`snaptext --ocr` / `snaptext --img` 命令行触发，经
  单实例 unix socket（`~/.snaptext.sock`，`IpcServer` + queued 信号 marshal 到 GUI
  线程）派发给常驻进程；无常驻则本次启动并触发一次。**用户在自己合成器里把快捷键
  绑到这两条命令**（KDE 系统设置 / GNOME 设置 / Sway bindsym / Hyprland bind…）。
  GlobalShortcuts 后端不可用（非 Wayland / portal 缺失 / 用户拒绝授权）时自动落此
  兜底。
- **GNOME 自动注册**：wayland+GNOME 会话启动时 `registerGnomeShortcuts()` 用
  `gsettings` 写 `org.gnome.settings-daemon.plugins.media-keys` 的 custom-keybindings
  （命令 = `<exe> --ocr/--img`），尽力而为、失败即放弃（可手动在设置里绑）。
- **截图（跨合成器唯一通用接口）**：xdg-desktop-portal `Screenshot`。各桌面各自实现
  后端（KDE→xdg-desktop-portal-kde，GNOME→-gnome，wlroots→-wlr 走 zwlr_screencopy，
  COSMIC/niri→-generic 走 ext-image-copy-capture），应用侧只需调
  `org.freedesktop.portal.Screenshot.Screenshot`，后端自动选。**必须用非交互模式**：
  `interactive=true` 的选区 UI 由合成器决定（KDE 弹系统对话框且无统一区域模式），
  不可依赖。**portal Screenshot 没有「区域」参数** → 通用做法：非交互抓全屏 →
  应用侧 `Selector` 在截图图上自绘拉框选区 → 裁剪。选区体验全合成器一致。
- **非交互 portal 流程（portal.cpp）**：`portalScreenshotFullscreen(cb)` 构造 Request
  句柄 → 订阅 `Response` 信号 → 调 `Screenshot`（无 interactive；**须带
  `background: true`**，否则后台应用——热键触发时不在前台——在部分合成器（GNOME）
  会被拒）→ Response 里取 `uri`（file://）转本地路径。
  **响应码语义**：0=成功、1=用户取消、2=其它错误；`onResponse` 把 1 映射为
  `cancelled=true`（调用方静默）、2/缺 uri 映射为 `cancelled=false`（调用方托盘提示
  「截图失败」）。
- **portal 踩坑 1：Request 路径构造必须去掉前导冒号（2026-08-15 晚根因）**：
  portal 实际发出的 Response 信号路径是 `/org/freedesktop/portal/desktop/request/1_42/…`
  （bus 唯一名 `:1.42` → `1_42`：**去前导 `:`** 再把其余 `:`、`.` 换 `_`）。
  若按 `_1_42`（带下划线）构造 handle，connect 返回 true 但 match rule 永远匹配不上
  → Response 信号静默丢失、回调永不触发（portal 端图已保存、无任何报错）。排查时
  极易误判为「portal 没响应/系统损坏」。
- **portal 踩坑 2：connect 响应信号**不能**传显式 D-Bus 签名 `"uav"`（2026-08-15 晚
  根因）**：带 signature 的 `QDBusConnection::connect` 重载注册的 match rule 与实际
  信号对不上，connect 返回成功但 Response 永不触发（本会话用 4 路对比实测：带
  signature 的 A/B/C 全不触发，不带 signature 的 D 正常触发）。直接用无签名重载
  `connect(service, path, iface, name, this, SLOT(onResponse(uint, QVariantMap)))`。
  （此前「须显式传 uav 否则 introspection 失败」的结论是错的，勿再回退。）
- **Wayland 选区窗口（ui.cpp Selector）**：普通无边框置顶全屏窗口（无
  `X11BypassWindowManagerHint`/`Qt::Tool`——前者在 Wayland 被忽略、后者可能被部分
  合成器特殊处理）；`showFullScreen` 后 `raise+activateWindow+setFocus` 抢键盘焦点，
  让 Esc 原生可用。
- **KDE 全屏勿扰（2026-08-15，勿回退到工作区窗口）**：KWin 判定活动窗口为真全屏
  （xdg-shell fullscreen 状态）时会自动进入勿扰/抑制通知（为游戏/视频设计，应用侧
  无法拦截，系统设置也没有对应开关）。**结论：盖住任务栏必须真全屏，勿扰只在选区
  期间闪现、选完自动恢复**，属 KWin 硬约束，别用「工作区几何普通窗」替代（会被夹
  到工作区、盖不住任务栏）。**副作用修复**：`handleRegion` 里 Image 分支紧跟在
  `selector_->close()` 后的 `tray_->notify` 会因刚关全屏仍处勿扰态而被吞，须用
  `QTimer::singleShot(400, ...)` 延迟到全屏状态释放后再弹「已复制图片」。
- **Wayland 高分屏**：portal 返回合成器输出的物理分辨率全屏图（如 3840×2160），加载后
  **有效 dpr 用「图物理尺寸 / 屏逻辑几何」推导**，勿用 `QScreen::devicePixelRatio()`：
  KWin 分数缩放（如 150%）时 Qt 上报的 dpr 可能是整数（2），而图/逻辑比是 1.5，
  直接用 Qt dpr 会导致选区整体错位（2026-08-15 晚实测，改 1.5 缩放后复现并修复）。
  按尺寸比设 dpr 后，Selector 的 dpr 换算（选区×dpr 裁剪）自动生效、图逻辑尺寸==
  屏逻辑几何。
  **多显示器**：portal 非交互抓图尺寸由后端决定（多数后端=主屏/请求来源输出），
  Selector 窗口=primaryScreen 几何，宽高比通常一致；异形多屏组合图会压到单屏窗口
  （与 X11 `grabScreen` 同级别限制，暂不处理）。
- **Esc 兜底仅 X11**：x11 的 override-redirect 选区窗收不到键盘，才用临时全局 Esc 热键；
  wayland 的 Selector 是普通窗口、能拿键盘焦点，Esc 原生可用（`keyPressEvent`），不抢全局 Esc。
- **portal 权限（2026-08-15 晚验证）**：portal Screenshot 是否放行由合成器经  `org.freedesktop.impl.portal.PermissionStore` 的 `Lookup(table="screenshot", id=应用id)`
  决定（KDE 数据落在 `~/.local/share/flatpak/db/screenshot`，本机授权条目形如
  `ai.opencode.desktop → screenshot: yes`）。**未授权时 KDE 后端会对 Screenshot 报
  `UnknownObject`、Spectacle 抓不出图、KWin 无 ScreenShot2 节点**——曾误判为「系统级
  截图损坏」，实际是权限没授予。授权方式：触发一次带交互的 portal 截图（KWin 弹权限
  对话框，用户点「始终允许」），或直接写权限表；授权后非交互截图即正常。
- **系统级截图损坏与本项目无关（2026-08-15 实测）**：若合成器的 portal 后端确实坏了
  （而非权限未授），任何走 portal 的工具都会失败，与本应用代码无关。代码按标准实现
  即可；排查顺序：先查权限（PermissionStore Lookup），再查后端实现。

## 设计哲学

1. **极简**：一个功能只做一个，不堆配置不堆依赖。每层"最小可用"，够用即止。
2. **模块独立**：每层独立模块、接口最小、可单独跑验证（ocr 能 CLI 单跑；ui 可
   offscreen 编译；hotkey 不依赖 Qt）。Ui/OCR/hotkey/tray 互相不掺。
3. **零摩擦交互**：快捷键直达结果，无确认弹窗、无多步骤。反馈走托盘非阻塞气泡，
   不打断当前工作。
4. **所见即所得（1:1）**：选区覆盖全屏含系统面板，抓什么显示什么、存什么。高分屏
   dpr 显式换算，坐标空间不含糊。
5. **稳健优先于花哨**：单实例锁防热键冲突；线程/高分屏/Xlib/portal 等坑全部显式
   处理并把结论写进本文件，改代码勿回退。

## 实践（怎么做到上述哲学）

- **拆层顺序**：ocr 驱动独立 → ui 独立 → 热键独立 → 托盘收尾。每步保持模块
  "可单独跑"再往下拆。
- **验证习惯**：C++ 用 `cmake --build build` 编译 → `build/snaptext-ocr <图>` 单跑
  OCR → `xdotool` 注入真实热键（X11）/ 实际按键（Wayland）→ 走真实进程 e2e
  （拖拽用 `xdotool mousemove ... mousedown 1 ... mousemove ... mouseup 1` 带 sleep
  才稳定）。改 GUI/热键必须走真实进程 e2e。
- **踩坑即沉淀**：每修一个非显而易见的问题，把结论写进 AGENTS.md（本文件即"踩坑
  日志"），同时作为 git commit message。
- **更新即沉淀（2026-08-13 补）**：不只踩坑要记，**任何非平凡的改动/决策/演进都
  要同步写进 AGENTS.md**——包括依赖变更、打包方案选择、模型版本取舍、目录/接口
  增删、需求来回（试过又放弃的方案）。原则：**改了什么，AGENTS.md 就要跟着对得上**，
  否则下次别人（或你自己）读文档会以为代码还是旧行为。改完顺手 `git diff` 对照，
  确认文档描述与代码一致。
- **清理测试残留**：`pkill -9 -f 'build/[s]naptext'` 或 `'opencode/[g]stest'`
  **只能单独一条命令跑**——`[s]`/`[g]` 只挡「本命令自身的正则字样」，但同一命令里
  其它参数（如 `setsid nohup … ./build/snaptext`）仍含 `build/snaptext` 字面量会被
  pkill 匹配 → 自杀。务必 pkill 与启动分两条命令。
- **单实例测试**：`~/.snaptext.lock` 持锁为唯一实例；清数据目录（`~/.snaptext`）
  不影响锁（锁在 `~/.snaptext.lock`）。

## X11 热键踩过的坑（hotkey.cpp 已修，改它时勿回退）

- **`XGrabKey` 恒返回 1**，不是状态码；注册成败经 error handler + `XSync` 同步判断
  （`grabOk()`）。用返回值判断会永远"注册失败"。
- 轮询线程与主线程并发访问同一 Display，启动先调 `XInitThreads()`。
- `release()` 必须 join 轮询线程，否则收尾时资源未释放。
- **NumLock/CapsLock 开启时被动 grab 匹配不上 → 热键静默失效（2026-08-12 根因）**：
  XGrabKey 只精确匹配注册的 modifiers 组合，**X server 不会自动为被动 grab 注册
  lock 变体**。本机 NumLock 常开，按 Alt+X 实际 state=0x18（Mod1+Mod2），而只注册
  mods=8 的 grab 匹配不上 → 热键完全失效。修法：`lockVariants(mods)` 显式注册全部
  4 个变体（mods / mods|Caps / mods|NumLock / mods|Caps|NumLock），事件侧用
  `state & ~(LOCK|MOD2) == mods` 过滤兼容任意 lock 状态。排查时曾误判"被动 grab 全部
  失效"，实际是注册的 lock 变体不全。
- **KeyRelease 重新武装不能按 mods 过滤（2026-08-12）**：按住触发后需等 KeyRelease
  重新 arm。若 KeyRelease 也要求 `state & ~(LOCK|MOD2) == mods`，**先松 Alt 再松 X
  时 KeyRelease(X) 到达已无 Mod1（state=0），永远 re-arm 失败 → 热键只触发一次就
  永久失效**。修法：KeyRelease 只凭 keycode 重新 arm，不检查 state。
- **防抖（2026-08-12）**：按住热键时 X11 auto-repeat 连续发 KeyPress，每个都触发
  回调 → 一次长按触发几十次截图/OCR，线程堆积（实测 175 线程、CPU 766%）。修法：
  `armed_` 标志，KeyPress 触发后置 False，KeyRelease 才重新 arm，一次按键只触发一次。

## Qt6 / 高分屏踩过的坑（已修，别回退）

- **4K 屏 dpr=2**：X11 `grabWindow(0)` 返回设备像素图（3840×2160），窗口/鼠标坐标是
  逻辑（1920×1080）。Select 画布 source rect 和 `_on_selected` 拷图 rect 都必须乘
  dpr，否则选区显示巨大/位置错位、存图错裁。（Wayland 的有效 dpr 见「Wayland 通用
  架构」节，用「图物理尺寸/屏逻辑几何」推导，不能直接用 `devicePixelRatio()`。）
- **后台 OCR 线程用 QThread/std::thread**：worker 要持有强引用（局部变量会在作用域
  结束被销毁，`started→run` 永不触发、txt 不落盘）；finished 后不再访问已销毁对象。
- **弹窗期间保持 `busy_`**：否则忙时再按热键会叠全屏选区遮罩，看起来程序
  "未响应/关不掉"。
- **托盘 app 必须 `setQuitOnLastWindowClosed(false)`**：选区遮罩作为唯一可见窗口
  关闭时会误触发 quit。
- **X11 override-redirect 窗口收不到键盘**：Esc 用临时全局热键兜底。
- **单实例锁**：多开实例抢同一 XGrabKey，热键随机失效。锁在数据目录外
  （`~/.snaptext.lock`），flock + 固定 UUID token（`<uuid>_SnapText`）+ PID 存活校验。

## OCR 踩过的坑（ocr.cpp 已修，改它时勿回退）

- **行合并 `_merge_to_lines`（旋转稳健）**：det 按连通域出框，一行内有大间隙（标签页/
  菜单项等）会切成多个词块框 → 逐框输出"换行过频"。修复：用 `minAreaRect` 求每框
  方向角（归一到 (-90,90]，`angle%180` 后 `>90` 减 180 处理 179.5→-0.5 的环绕），
  取中位数为文本方向；把框 4 点投影到"文本方向/法线"轴，沿法线按"重叠比例>0.6
  （基准取两框中较矮者）"聚类成行，同行内沿文本方向排序空格连接。**判据要点**：紧挨
  的两行文字法线区间可能搭界 2px，但重叠比例极低（行高 27/44 时仅 7%），不会误连；
  而同一行框重叠比例 90%+。旋转/倾斜文本投影到同一法线上仍同属一行，天然稳健。
- **det 长边封顶（性能）**：det 在 `limit_type='max'` 时按 `max_wh` 自动选
  960/1500/2000 封顶，`Det.limit_side_len=960` 语义延续（长边封顶、32 对齐）。
  让扁图/4K 都不全尺寸推理（旧版 `limit_type='min'` 会把 694×50 扁图放大成
  10200×736，3-4 秒）。实测 4K 全屏 ~1s、扁图 ~0.5s。
- **宽高比窄条**：rapidocr 对宽高比 > `width_height_ratio` 的窄条用 `apply_vertical_padding`
  加竖直 padding 再走 det（`Global.width_height_ratio=100` 几乎不触发 padding）。
- **竖排文本是 det 能力边界**：PP-OCR det 按连通域出框，两列竖排文字被 unclip 弥合
  成一个框（angle≈0），任何后处理都无法分行。属模型固有短板，非行合并可解。

## 配置（config.conf，2026-08-15）

- 程序启动读**可选 `config.conf`**（可执行文件旁或当前目录，全注释模板、不改=现状）。
  改配置 = 取消注释那一项示例行、改值；**启动时读一次，改配置需重启**。
- `src/config.cpp` 只依赖标准库。读取时按行 `key=value` 解析，只在 `DEFAULTS` 白名单
  内的名字才生效；拼错名/类型错/值非法 → 该项**静默回退默认**并 stderr 警示，不影响
  其它项。
- **bool 校验用 `type(v) is bool` 思路（C++ 用严格解析）**：`1` 不能被当成 `true`
  放行；int 项也挡掉布尔。
- 热键写法 `修饰键+修饰键+键名`：shift/ctrl/alt/super 可组合（OR），键名=X11
  keysym；`parseHotkey()` 解析成 `(key, mods)`、`hotkeyDisplay()` 生成托盘展示文案。
  CapsLock/NumLock 由 hotkey.cpp 的 lock 变体自动兼容，不额外注册。
- `save_images=false`：图片不落盘、OCR 走内存（`QPixmap`→BGR 拷贝，`ascontiguousarray`
  脱离 QImage 生命周期，防悬空）。此时 data 目录不自动创建、txt 也不落盘，结果只进
  剪贴板。
- 配置项清单以 `src/config.cpp` 的 `DEFAULTS` 为准；新增配置项 = `DEFAULTS` 各加一条，
  `str()/int_()/bool_()` 取用。另可用环境变量 `SNAPTEXT_MODELS_DIR` 指定模型目录。

## deb 打包（pack-deb.sh，2026-08-15 C++ 版）

- **体积策略**：deb 装 二进制 + models + 内置 onnxruntime，Qt6/OpenCV/libx11 走系统包
  （Depends 声明），deb 约 35MB。
- 布局：`/opt/snaptext/{snaptext, snaptext-ocr, models/, icons/, lib/}` +
  `/usr/bin/snaptext`（启动脚本，设 `LD_LIBRARY_PATH=/opt/snaptext/lib` +
  `SNAPTEXT_MODELS_DIR`）+ desktop + hicolor 图标 + 文档。
- **onnxruntime 内置**：跨发行版无统一系统包名（Ubuntu=libonnxruntime1.x，版本各异的
  SONAME），随包自含到 `lib/`（`cp -P` 保留符号链接，勿展开成两份实文件），仅依赖
  系统 libc/libstdc++。
- **desktop 文件名 = GlobalShortcuts app_id（关键）**：装
  `io.github.a2heng.snaptext.desktop`，否则 portal `Registry.Register` 报
  "App info not found"、Wayland 热键绑定失败。勿改名。
- **Depends 跨发行版 OR 兼容（2026-08-13）**：同一依赖不同发行版/版本包名不同——
  Qt6 在 Debian 拆包且新版带 t64 后缀（`libqt6core6 | libqt6core6t64`）、OpenCV
  版本号随发行版（`libopencv-core410 | libopencv-core4.10 | libopencv-core4.8`）。
  用 deb 的 OR 关系 `a | b`（每项满足其一即可）。`SNAPTEXT_DEPS` 仍可完全覆盖。
- **图标静态化（2026-08-12）**：`icons/`（png 多尺寸 + ico，蓝底圆角 + 宋体 Black
  "拾"字）随仓库提交，打包时直接拷贝，**CI 不生成图标**（少一个故障点）。
  **托盘也加载静态资源**（tray.cpp 读 `icons/snaptext-64.png`，不运行时绘制）。
  需重画时跑 `QT_QPA_PLATFORM=offscreen python3 make-icons.py` 并提交新 icons/。
  样式参数（圆角/字号/垂直偏移/超采样）见 make-icons.py 顶部常量。
- **tag 命名准则（2026-08-13）**：tag 触发 CI 时版本取 `GITHUB_REF_NAME`（去 `v`），
  本地跑回退当前时间。**tag 必须手动打成 `vYYYY.MM.DD.HHMM`（10 位、含分钟）**，
  例：`v2026.08.15.2130` = 2026-08-15 **21:30（晚上 9 点 30 分）**。HHMM 是 24 小时制，
  用 15xx/2xxx 这种无歧义时刻举例，避免 `0021` 被误读为"凌晨 00:21"。
  不要打缺分钟的 tag（如 `v2026.08.15.1`）——会发布出无分钟的错误版本号。
- **模型文件名必须保留官方原名**（PP-OCRv6_det_small.onnx / PP-OCRv6_rec_small.onnx /
  ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx），勿自定义改名。

## 落盘与流程

- 截图（X11 `grabScreen` / Wayland portal）抓全屏 → `Selector` 全屏半透明拉框 overlay
  （覆盖系统面板）。
- 落盘 `~/.snaptext/img/`（png）、`~/.snaptext/text/`（txt），文件名
  `YYYYMMDD_HHMMSS_XXX`。数据目录/热键/OCR 参数/行为等均可在 config.conf 调整。
- OCR 结果 `\n` 拼接，成功自动复制剪贴板；反馈走托盘非阻塞气泡（无弹窗）。
