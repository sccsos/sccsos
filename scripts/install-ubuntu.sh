#!/usr/bin/env bash
# DEPRECATED — 已拆分为 install-hermes.sh + install-sccsos.sh
# 请使用: bash <(curl -fsSL https://raw.githubusercontent.com/sccsos/sccsos/main/scripts/install.sh)
echo "DEPRECATED: 请使用 install.sh（自动调用 install-hermes.sh → install-sccsos.sh）"
echo ""
echo "  单命令安装:"
echo "    bash <(curl -fsSL https://raw.githubusercontent.com/sccsos/sccsos/main/scripts/install.sh)"
echo ""
echo "  分步安装:"
echo "    bash install-hermes.sh && source ~/.bashrc && bash install-sccsos.sh"
exit 0
