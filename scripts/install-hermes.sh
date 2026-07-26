#!/usr/bin/env bash
# Hermes Agent 安装脚本 (Ubuntu / Python 3.12)
# 使用官方 install.sh，路径收拢至 ~/sccsos/
# 必须先于 install-sccsos.sh 执行
set -euo pipefail

SCCSOS_HOME="${SCCSOS_HOME:-$HOME/sccsos}"

echo "═══ Hermes Agent 安装 ═══"
echo "  Target:  $SCCSOS_HOME"
echo ""

# ── 1. 系统依赖 + Python 3.12 ──
echo "1️⃣ 系统依赖 + Python 3.12..."
sudo apt-get update -qq
if ! command -v python3.12 &>/dev/null; then
  if grep -qi "24.04\|24.10\|25.04" /etc/os-release 2>/dev/null; then
    sudo apt-get install -y -qq python3.12 python3.12-venv python3.12-pip
  else
    sudo apt-get install -y -qq software-properties-common
    sudo add-apt-repository -y ppa:deadsnakes/ppa -s
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3.12 python3.12-venv python3.12-pip
  fi
fi
sudo apt-get install -y -qq git curl xz-utils build-essential
echo "  ✅ $(python3.12 --version)"

# ── 2. 目录结构 ──
echo ""
echo "2️⃣ 目录结构..."
mkdir -p "$SCCSOS_HOME"/{agents,workflows,personalities,wiki,config,data/{logs,traces},uv-cache}
echo "  ✅ $SCCSOS_HOME/"

# ── 3. 安装 Hermes Agent（官方脚本）──
echo ""
echo "3️⃣ Hermes Agent（官方 install.sh）..."
export HERMES_HOME="$SCCSOS_HOME/hermes"
export HERMES_CODE_PATH="$SCCSOS_HOME/hermes-agent"

if [ -f "$HERMES_CODE_PATH/venv/bin/hermes" ]; then
  echo "  ↪ 已安装，跳过"
else
  # PATH 前置 python3.12 → install.sh 创建的 venv 自动用 3.12
  PY312_DIR="$(dirname "$(command -v python3.12)")"
  PATH="$PY312_DIR:$PATH" \
    curl -fsSL https://hermes-agent.nousresearch.com/install.sh | \
    bash -s -- --skip-setup --skip-browser
  echo "  ✅ Hermes CLI: $HERMES_CODE_PATH/venv/bin/hermes"
fi
"$HERMES_CODE_PATH/venv/bin/hermes" --version

# ── 4. Hermes 初始配置 ──
mkdir -p "$SCCSOS_HOME/hermes/profiles/sccsos"
cat > "$SCCSOS_HOME/hermes/config.yaml" << 'EOF'
model:
  default: deepseek-v4-flash
  provider: deepseek
  base_url: "https://api.deepseek.com/v1"
EOF

# ── 5. Shell 环境变量（单引号 heredoc → 不展开，留 shell 变量引用）──
echo ""
echo "4️⃣ Shell 环境变量..."
case "${SHELL:-bash}" in
  *zsh) RC_FILE="${ZDOTDIR:-$HOME}/.zshrc" ;;
  *bash) RC_FILE="$HOME/.bashrc" ;;
  *) RC_FILE="$HOME/.profile" ;;
esac
MARK="# ── SCCS OS + Hermes Agent ──"

if grep -qF "$MARK" "$RC_FILE" 2>/dev/null; then
  echo "  ⏭  环境变量已在 $RC_FILE 中存在，跳过"
else
  cat >> "$RC_FILE" << 'EOF'

# ── SCCS OS + Hermes Agent ──
export SCCSOS_HOME=$HOME/sccsos
export HERMES_HOME=$SCCSOS_HOME/hermes
export HERMES_CONFIG_PATH=$SCCSOS_HOME/hermes
export HERMES_INSTALL_DIR=$SCCSOS_HOME/hermes-agent
export HERMES_BIN=$SCCSOS_HOME/hermes-agent/venv/bin/hermes
export HERMES_BIN_DIR=$SCCSOS_HOME/hermes-agent/venv/bin
export PATH=$HERMES_BIN_DIR:$PATH
# ── ──
EOF
  echo "  ✅ 写入 $RC_FILE"
fi

# 当前会话立即生效
export SCCSOS_HOME HERMES_HOME HERMES_CONFIG_PATH
export HERMES_INSTALL_DIR HERMES_BIN HERMES_BIN_DIR
export PATH="$HERMES_BIN_DIR:$PATH"

echo ""
echo "═══ Hermes 安装完成 ═══"
echo ""
echo "  下一步: source $RC_FILE && bash install-sccsos.sh"
