#!/usr/bin/env bash
# SCCS OS + Hermes Agent 一键安装 (Ubuntu / Python 3.12)
# 依次执行: install-hermes.sh → install-sccsos.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "═══ SCCS OS + Hermes Agent 一键安装 ═══"
echo ""

# Step 1: Hermes（子进程，其 export 不影响父进程）
echo "━━━ [1/2] Hermes Agent 安装 ━━━"
bash "$SCRIPT_DIR/install-hermes.sh"

# 子进程的 export 不继承，重新声明环境变量
SCCSOS_HOME="${SCCSOS_HOME:-$HOME/sccsos}"
HERMES_BIN="$SCCSOS_HOME/hermes-agent/venv/bin/hermes"
HERMES_BIN_DIR="$SCCSOS_HOME/hermes-agent/venv/bin"
export SCCSOS_HOME HERMES_BIN HERMES_BIN_DIR
export PATH="$HERMES_BIN_DIR:$PATH"

# Step 2: SCCS OS
echo ""
echo "━━━ [2/2] SCCS OS 安装 ━━━"
bash "$SCRIPT_DIR/install-sccsos.sh"

echo ""
echo "═══ 全部安装完成 ═══"
echo "  加载:   source ~/.bashrc"
echo "  配置:   export DEEPSEEK_API_KEY=\"sk-***\" && cd ~/sccsos && sccsos hermes config-sync"
echo "  启动:   cd ~/sccsos && python3 -m sccsos serve"
