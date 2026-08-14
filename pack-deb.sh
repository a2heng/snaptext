#!/bin/bash
# 拾字 SnapText — Linux deb 打包脚本（最小体积：代码+models+少量无系统包依赖）
# 产出: dist/snaptext-Linux-<arch>-<版本>-release.deb
#
# 体积策略：deb 只装 源码 + models + rapidocr 纯代码 + 无系统包的纯/二进制依赖，
# PySide6/opencv/onnxruntime/numpy 等走系统包（Depends 声明），体积 ~20MB。
#
# 布局:
#   /opt/snaptext/{*.py, models/, lib/}   源码 + 模型 + 剥离的无系统包依赖
#   /usr/bin/snaptext                    启动脚本（_config.py 不依赖 vendor）
#   /usr/share/applications/snaptext.desktop
#   /usr/share/doc/snaptext/README + AGENTS + LICENSE
#
# 依赖拆分（2026-08-12 调研）：
#   走系统包：pyside6 opencv numpy onnxruntime pillow pyyaml six tqdm requests
#   剥进 lib/（AOSC/Debian/Ubuntu 均无系统包）：rapidocr(弃内置28M模型)
#     + shapely + pyclipper + omegaconf + antlr4-python3-runtime
#   colorlog：rapidocr 的 log.py 仅用于日志着色，打包时替换为标准库 logging，
#     免去 colorlog 依赖（注意：源码运行仍需 rapidocr 自带 colorlog，此处仅产物替换）。
#
# 版本号解析：tag 触发 CI 时取自 GITHUB_REF_NAME（v2026.08.13.1505 → 2026.08.13.1505），
# 保证 deb 与 tag 名一致；本地/手动跑回退当前时间。
#
# tag 命名约定见 AGENTS.md「deb 打包」节：必须手动打成 `vYYYY.MM.DD.HHMM`（10 位，
# 含分钟），如 v2026.08.13.1505（= 2026-08-13 15:05，下午 3 点 5 分）。

set -euo pipefail
cd "$(dirname "$0")"

if [ -n "${GITHUB_REF_NAME:-}" ] && [[ "$GITHUB_REF_NAME" == v* ]]; then
    VERSION="${GITHUB_REF_NAME#v}"
else
    VERSION="$(date +%Y.%m.%d.%H%M)"
fi
REV="1"
DATE="${VERSION//./-}"
ARCH="amd64"
PKG_FILE="snaptext-Linux-${ARCH}-${DATE}-release.deb"
DIST="dist"
STAGE="${TMPDIR:-/tmp}/snaptext_deb_build"
ROOT="$STAGE/root"
TMPDL="$(mktemp -d)"
trap 'rm -rf "$TMPDL"' EXIT

echo "==> 语法校验"
python3 -m py_compile snaptext.py ocr.py ui.py hotkey.py hotkey_wayland.py tray.py config.py _config.py _bootstrap.py

echo "==> 准备打包目录 $STAGE"
rm -rf "$STAGE"
mkdir -p "$ROOT/opt/snaptext/lib" \
         "$ROOT/usr/bin" \
         "$ROOT/usr/share/applications" \
         "$ROOT/usr/share/icons/hicolor/256x256/apps" \
         "$ROOT/usr/share/doc/snaptext" \
         "$ROOT/DEBIAN"

echo "==> 拷贝源码/模型"
for f in snaptext.py ocr.py ui.py hotkey.py hotkey_wayland.py tray.py config.py _config.py _bootstrap.py; do
    cp "$f" "$ROOT/opt/snaptext/"
done
cp -r models "$ROOT/opt/snaptext/"

echo "==> 拷贝静态图标（icons/ 随仓库提交，无需生成）"
# 多尺寸 PNG → hicolor 主题；snaptext.ico + icons/ → /opt/snaptext（托盘加载用）
for s in 16 24 32 48 64 128 256; do
    d="$ROOT/usr/share/icons/hicolor/${s}x${s}/apps"
    mkdir -p "$d"
    cp "icons/snaptext-$s.png" "$d/snaptext.png"
done
cp icons/snaptext.ico "$ROOT/opt/snaptext/"
cp -r icons "$ROOT/opt/snaptext/"

# ---- 剥离无系统包依赖到 lib/ ----
# rapidocr 内置 28MB 模型弃用（项目用自带模型）；colorlog 用 logging 替换；
# shapely 用 numpy 公式 patch 掉（rapidocr 只用它的 Polygon.area/length）。
# 保留仍需的：pyclipper(offset) + omegaconf + antlr4。
STRIP_PKGS=(rapidocr pyclipper omegaconf)
python3 -m pip download --no-deps -d "$TMPDL" "${STRIP_PKGS[@]}" >/dev/null 2>&1
echo "==> 剥离 rapidocr（弃内置模型）+ pyclipper + omegaconf"
# antlr4-python3-runtime 只有 sdist，单独下载
python3 -m pip download --no-deps --no-binary :all: -d "$TMPDL" "antlr4-python3-runtime==4.9.3" >/dev/null 2>&1

extract_to_lib() {
    local wheel="$1"
    [ -n "$wheel" ] || { echo "缺少 wheel" >&2; return 1; }
    unzip -q -o "$wheel" -d "$TMPDL/extract"
    find "$TMPDL/extract" -maxdepth 1 -mindepth 1 -type d \
        ! -name '*.dist-info' ! -name '*.*.dist-info' -exec cp -r {} "$ROOT/opt/snaptext/lib/" \;
}
extract_to_lib "$(find "$TMPDL" -iname 'rapidocr-*.whl' | head -1)"
extract_to_lib "$(find "$TMPDL" -iname 'pyclipper-*.whl' | head -1)"
extract_to_lib "$(find "$TMPDL" -iname 'omegaconf-*.whl' | head -1)"

# antlr4-python3-runtime 是 sdist（.tar.gz），解出 src/antlr4 目录
ANTLR_TGZ="$(find "$TMPDL" -name 'antlr4-python3-runtime-*.tar.gz' | head -1)"
[ -n "$ANTLR_TGZ" ] && tar -xzf "$ANTLR_TGZ" -C "$TMPDL" \
    && cp -r "$TMPDL"/antlr4-python3-runtime-*/src/antlr4 "$ROOT/opt/snaptext/lib/"

# 弃 rapidocr 内置模型；colorlog 替换为标准库 logging（产物免 colorlog 依赖）
rm -rf "$ROOT/opt/snaptext/lib/rapidocr/models"
cat > "$ROOT/opt/snaptext/lib/rapidocr/utils/log.py" <<'EOF'
# -*- encoding: utf-8 -*-
import logging
# 标准库 logging 版（去掉 colorlog 着色依赖，仅打包产物用）

class Logger:
    def __init__(self, log_level=logging.INFO, logger_name=None):
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(log_level)
        self.logger.propagate = False
        formatter = logging.Formatter(
            f"[%(levelname)s] %(asctime)s [{logger_name}] %(filename)s:%(lineno)d: %(message)s"
        )
        if not self.logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            console_handler.setLevel(log_level)
            self.logger.addHandler(console_handler)

    def get_log(self):
        return self.logger


logger = Logger(log_level=logging.INFO, logger_name="RapidOCR").get_log()
EOF

# 去掉 shapely 依赖：rapidocr 只用 shapely.geometry.Polygon 的 area/length 一处
# （ch_ppocr_det/utils.py 的 unclip），用 numpy 鞋带公式/周长替换，结果完全一致，
# 从而 lib/ 无需打包 shapely（省 ~10MB，且目标机无需系统 shapely）。
DET_UTILS="$ROOT/opt/snaptext/lib/rapidocr/ch_ppocr_det/utils.py"
sed -i '/^from shapely.geometry import Polygon$/d' "$DET_UTILS"
python3 - "$DET_UTILS" <<'PYEOF'
import sys
p = sys.argv[1]
s = open(p).read()
old = '''        poly = Polygon(box)
        distance = poly.area * unclip_ratio / poly.length'''
new = '''        x, y = box[:, 0], box[:, 1]
        _area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
        _len = np.sum(np.sqrt(np.diff(x, append=x[0]) ** 2 + np.diff(y, append=y[0]) ** 2))
        distance = _area * unclip_ratio / _len'''
if old in s:
    s = s.replace(old, new)
    open(p, "w").write(s)
    print("    shapely 已 patch 为 numpy（unclip 等效）")
else:
    sys.exit("unclip 代码未匹配，shapely patch 失败")
PYEOF

echo "==> 依赖清理"
# 删所有 __pycache__ 目录与 *.pyc（先删最深层，避免 rm -rf 父目录时子目录仍在）
find "$ROOT/opt/snaptext" -depth -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$ROOT/opt/snaptext" -name '*.pyc' -delete 2>/dev/null || true
# 删纯开发/测试冗余：omegaconf 的 pydevd 调试残留（16K）
rm -rf "$ROOT/opt/snaptext/lib/pydevd_plugins" 2>/dev/null || true

echo "==> /usr/bin/snaptext 启动脚本"
cat > "$ROOT/usr/bin/snaptext" <<'EOF'
#!/bin/sh
# 拾字 SnapText — 系统包依赖 + 项目内置 lib/（rapidocr/pyclipper/omegaconf）
exec /usr/bin/python3 /opt/snaptext/snaptext.py "$@"
EOF
chmod +x "$ROOT/usr/bin/snaptext"

echo "==> desktop 文件"
cat > "$ROOT/usr/share/applications/snaptext.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=拾字 SnapText
GenericName=Screen OCR
GenericName[zh_CN]=屏幕文字识别
Comment=极简本地截图 + 本地 onnx OCR 工具
Comment[zh_CN]=极简本地截图 + 本地 onnx OCR 工具
Exec=/usr/bin/snaptext
Icon=snaptext
Terminal=false
Categories=Graphics;Utility;
Keywords=screenshot;ocr;text;snaptext;
EOF

echo "==> 文档"
cp README.md AGENTS.md LICENSE "$ROOT/usr/share/doc/snaptext/"

echo "==> 解析 Depends（跨发行版 OR 兼容 AOSC + Debian/Ubuntu，可用 SNAPTEXT_DEPS 覆盖）"
# 同一依赖在不同发行版包名不同：AOSC 无 python3- 前缀（pyside6/opencv/...），
# Debian/Ubuntu 是 python3-* 拆分名。用 deb 的 OR 关系 `a | b` 让一个 deb
# 同时被两边满足（每项满足其一即可）。可用 SNAPTEXT_DEPS 完全覆盖。
if [ -n "${SNAPTEXT_DEPS:-}" ]; then
    DEPS="$SNAPTEXT_DEPS"
else
    DEPS="pyside6 | python3-pyside6.qtgui, \
opencv | python3-opencv, \
numpy | python3-numpy, \
pillow | python3-pillow, \
pyyaml | python3-yaml, \
six | python3-six, \
tqdm | python3-tqdm, \
requests | python3-requests, \
onnxruntime | python3-onnxruntime"
fi
echo "==> Depends: $DEPS"

echo "==> DEBIAN/control"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: snaptext
Version: $VERSION-$REV
Section: graphics
Priority: optional
Architecture: $ARCH
Maintainer: a2heng <aheng@users.noreply.github.com>
Depends: $DEPS
Description: 拾字 SnapText — 极简本地截图 + 本地 onnx OCR
 极简本地截图 + 本地 onnx OCR 工具（Linux X11 / KDE Plasma）。
 截图、OCR 全部本地完成，模型直接打包在仓库里，不联网、不上传、无云依赖。
 全局热键按会话自适应：X11 用 XGrabKey；KDE Plasma Wayland 用 KGlobalAccel；
 GNOME 及其它 Wayland 用命令行触发（snaptext --ocr / --img，可绑定系统快捷键）。
  .
 AIX: 需要 X11 或 Wayland 桌面环境（Qt6 + KDE/GLib 组件由系统提供）。
EOF

echo "==> 构建 $PKG_FILE"
mkdir -p "$DIST"
rm -f "$DIST/$PKG_FILE"
dpkg-deb --build --root-owner-group "$ROOT" "$DIST/$PKG_FILE" >/dev/null
echo "==> 完成: $DIST/$PKG_FILE"
ls -lh "$DIST/$PKG_FILE"
dpkg-deb --info "$DIST/$PKG_FILE" | head -12 || true