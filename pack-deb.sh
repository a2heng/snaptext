#!/bin/bash
# 拾字 SnapText（C++/Qt6 版）— Linux deb 打包脚本
# 产出: dist/snaptext-Linux-<arch>-<版本>-release.deb
#
# 布局:
#   /opt/snaptext/snaptext           主程序（托盘常驻，X11+Wayland）
#   /opt/snaptext/snaptext-ocr       OCR CLI（可单独跑）
#   /opt/snaptext/{models/, icons/}  模型 + 静态图标
#   /opt/snaptext/lib/               内置 onnxruntime（SONAME 自含）
#   /usr/bin/snaptext                启动脚本（LD_LIBRARY_PATH + SNAPTEXT_MODELS_DIR）
#   /usr/share/applications/io.github.a2heng.snaptext.desktop
#   /usr/share/icons/hicolor/...     （16..256 多尺寸）
#   /usr/share/doc/snaptext/README + AGENTS + LICENSE
#
# 体积策略：Qt6/OpenCV/libx11 走系统包（Depends），产物体积优先于自包含。
# onnxruntime 例外：跨发行版无统一系统包名（Ubuntu=libonnxruntime1.x，版本各异的
# SONAME），且本仓库 third_party 已内置编译好的库，故随包自含（~28MB）到
# /opt/snaptext/lib，启动脚本设 LD_LIBRARY_PATH 指向它。仅依赖系统 libc/libstdc++。
#
# 注意：desktop 文件名必须叫 io.github.a2heng.snaptext.desktop——GlobalShortcuts
# portal 的 Registry.Register 用 app_id=io.github.a2heng.snaptext 查找同名 desktop
# 文件，缺了会报 "App info not found"、热键绑定失败（见 AGENTS.md）。
#
# 版本号解析：tag 触发 CI 时取自 GITHUB_REF_NAME（v2026.08.15.2130 → 2026.08.15.2130），
# 本地/手动跑回退当前时间。tag 必须手动打成 `vYYYY.MM.DD.HHMM`（10 位，含分钟）。

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

echo "==> 构建 C++ 程序"
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)"

echo "==> 准备打包目录 $STAGE"
rm -rf "$STAGE"
mkdir -p "$ROOT/opt/snaptext/lib" \
         "$ROOT/usr/bin" \
         "$ROOT/usr/share/applications" \
         "$ROOT/usr/share/doc/snaptext" \
         "$ROOT/DEBIAN"

echo "==> 拷贝程序/模型/图标"
install -m755 build/snaptext "$ROOT/opt/snaptext/snaptext"
install -m755 build/snaptext-ocr "$ROOT/opt/snaptext/snaptext-ocr"
cp -r models "$ROOT/opt/snaptext/"
cp -r icons "$ROOT/opt/snaptext/"
for s in 16 24 32 48 64 128 256; do
  mkdir -p "$ROOT/usr/share/icons/hicolor/${s}x${s}/apps"
  cp "icons/snaptext-$s.png" "$ROOT/usr/share/icons/hicolor/${s}x${s}/apps/snaptext.png"
done

echo "==> 内置 onnxruntime（跨发行版无统一系统包，随包自含保证 SONAME 匹配）"
# -P 保留符号链接（libonnxruntime.so.1 -> .1.29.0），否则 cp 会跟随展开成两份实文件
cp -P third_party/onnxruntime/onnxruntime-linux-x64-*/lib/libonnxruntime.so.1* "$ROOT/opt/snaptext/lib/"
cp -P third_party/onnxruntime/onnxruntime-linux-x64-*/lib/libonnxruntime_providers_shared.so "$ROOT/opt/snaptext/lib/" 2>/dev/null || true

echo "==> /usr/bin/snaptext 启动脚本（LD_LIBRARY_PATH 指向内置 onnxruntime）"
cat > "$ROOT/usr/bin/snaptext" <<'EOF'
#!/bin/sh
# 拾字 SnapText（C++）— 内置 onnxruntime 在 /opt/snaptext/lib
export SNAPTEXT_MODELS_DIR=/opt/snaptext/models
if [ -d /opt/snaptext/lib ]; then
    export LD_LIBRARY_PATH=/opt/snaptext/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
fi
exec /opt/snaptext/snaptext "$@"
EOF
chmod +x "$ROOT/usr/bin/snaptext"

echo "==> desktop 文件（文件名 = GlobalShortcuts app_id，勿改名）"
cat > "$ROOT/usr/share/applications/io.github.a2heng.snaptext.desktop" <<'EOF'
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

echo "==> 解析 Depends（跨发行版 OR 兼容，可用 SNAPTEXT_DEPS 覆盖）"
# Qt6 在 Debian 拆包且新版带 t64 后缀；OpenCV 版本号随发行版（4.8/4.10/410…）。
# onnxruntime 已自含，不在此列。各发行版实测用 SNAPTEXT_DEPS 精确覆盖。
if [ -n "${SNAPTEXT_DEPS:-}" ]; then
    DEPS="$SNAPTEXT_DEPS"
else
    DEPS="libqt6widgets6 | libqt6widgets6a | qt6-base, \
libqt6gui6 | libqt6gui6a, \
libqt6core6 | libqt6core6t64, \
libqt6dbus6, \
libqt6network6 | libqt6network6t64, \
libopencv-core410 | libopencv-core4.10 | libopencv-core4.8 | libopencv-core, \
libopencv-imgproc410 | libopencv-imgproc4.10 | libopencv-imgproc4.8 | libopencv-imgproc, \
libopencv-imgcodecs410 | libopencv-imgcodecs4.10 | libopencv-imgcodecs4.8 | libopencv-imgcodecs, \
libx11-6"
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
 极简本地截图 + 本地 onnx OCR 工具（C++/Qt6，Linux X11 / Wayland）。
 截图、OCR 全部本地完成，模型直接打包在仓库里，不联网、不上传、无云依赖。
 全局热键按会话自适应：X11 用 XGrabKey；Wayland 用 xdg-desktop-portal
 GlobalShortcuts（跨合成器标准）；后端不可用时回退命令行触发（snaptext --ocr/--img）。
  .
 onnxruntime 内置（/opt/snaptext/lib），其余 Qt6/OpenCV 走系统包。
EOF

echo "==> 构建 $PKG_FILE"
mkdir -p "$DIST"
rm -f "$DIST/$PKG_FILE"
dpkg-deb --build --root-owner-group "$ROOT" "$DIST/$PKG_FILE" >/dev/null
echo "==> 完成: $DIST/$PKG_FILE"
ls -lh "$DIST/$PKG_FILE"
dpkg-deb --info "$DIST/$PKG_FILE" | head -12 || true
