#!/usr/bin/env bash
# 下载 onnxruntime Linux x64 预编译包到 third_party/onnxruntime/
# （onnxruntime 无发行版系统包，需随仓库拉取；产物不入 git）
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:-1.29.0}"
DEST="third_party/onnxruntime"
URL="https://github.com/microsoft/onnxruntime/releases/download/v${VERSION}/onnxruntime-linux-x64-${VERSION}.tgz"

mkdir -p "$DEST"
echo "下载 $URL ..."
curl -sL -o "$DEST/ort.tgz" "$URL"
tar xzf "$DEST/ort.tgz" -C "$DEST"
rm -f "$DEST/ort.tgz"
echo "完成: $(ls -d "$DEST"/onnxruntime-linux-x64-*)"
