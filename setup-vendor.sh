#!/usr/bin/env bash
# 项目内 venv：把 Python 依赖装进 vendor/（离线内化）。
#
# vendor/ 不进 git（见 .gitignore）。克隆本项目后只需联网跑一次本脚本，
# 之后依赖完全离线，无需再 pip install。
#
# 用法：
#   ./setup-vendor.sh                      # 安装 OCR 链默认依赖
#   ./setup-vendor.sh <包名>...            # 追加安装任意包（自动拉其依赖）
#
# 依赖走当前 pip 源（默认 /etc/pip.conf 的 NJU 镜像）。
set -euo pipefail
cd "$(dirname "$0")"

# 默认：OCR 链（ocr.py 需要）。追加参数时改为安装用户指定的包。
DEFAULT_PKGS=(rapidocr-onnxruntime onnxruntime opencv-python numpy Pillow pyclipper PyYAML Shapely six flatbuffers packaging PySide6)

if [ "$#" -gt 0 ]; then
    PKGS=("$@")
    echo "==> 追加安装到 vendor/：${PKGS[*]}（仅本次需要联网）"
else
    PKGS=("${DEFAULT_PKGS[@]}")
    echo "==> 安装全部默认依赖（OCR 链 + PySide6）到 vendor/（仅本次需要联网）"
fi

python3 -m pip install --target vendor "${PKGS[@]}"

echo "==> 清理构建残留"
rm -rf vendor/__pycache__

echo "==> vendor/ 现有顶层包："
ls -d vendor/*/ 2>/dev/null | sed 's#vendor/##; s#/$##' | tr '\n' ' '
echo
