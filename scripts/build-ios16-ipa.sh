#!/bin/bash
# 在 Mac 上一键编译出部署目标为 iOS 16.2 的无签名 IPA。
set -euo pipefail
cd "$(dirname "$0")/.."

bash scripts/build-unsigned-ipa.sh
python3 scripts/patch-ios16.py \
  dist/TVADB-unsigned.ipa \
  dist/TVADB-iOS16.2-unsigned.ipa
python3 scripts/check-symbols.py dist/TVADB-iOS16.2-unsigned.ipa

echo ""
echo "完成：dist/TVADB-iOS16.2-unsigned.ipa"
echo "把这个 IPA 传到 iPhone，用 TrollStore 打开安装即可（无需签名证书）。"
