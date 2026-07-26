#!/usr/bin/env bash
# Hermes Agent 安装脚本 (Ubuntu / Python 3.12)
# 使用官方 install.sh，路径收拢至 ~/sccsos/
# 必须先于 install-sccsos.sh 执行
set -euo pipefail

SCCSOS_HOME="${SCCSOS_HOME:-$HOME/sccsos}"

# ── 全量路径变量（安装全程使用，确保一切收归 $SCCSOS_HOME）──
export SCCSOS_HOME
export HERMES_HOME="$SCCSOS_HOME/hermes"
export HERMES_CONFIG_PATH="$SCCSOS_HOME/hermes"
export HERMES_CODE_PATH="$SCCSOS_HOME/hermes-agent"    # Hermes 安装脚本读取此变量
export HERMES_INSTALL_DIR="$SCCSOS_HOME/hermes-agent"
export HERMES_BIN="$SCCSOS_HOME/hermes-agent/venv/bin/hermes"
export HERMES_BIN_DIR="$SCCSOS_HOME/hermes-agent/venv/bin"
export PATH="$HERMES_BIN_DIR:$PATH"

echo "═══ Hermes Agent 安装 ═══"
echo "  Target:  $SCCSOS_HOME"
echo ""

# ── 1. 系统依赖 + Python 3.12 ──
echo "1️⃣ 系统依赖 + Python 3.12..."
if ! command -v python3.12 &>/dev/null; then
  sudo apt-get update -qq
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

# ── 2. pip + uv 准备（--no-user 禁用 ~/.local/，确保 venv 内安装）──
echo ""
echo "2️⃣ pip + uv（--no-user 禁用本地用户目录）..."
python3.12 -m pip install --upgrade pip uv --no-user --break-system-packages --quiet
echo "  ✅ pip: $(python3.12 -m pip --version)"
echo "  ✅ uv:  $(python3.12 -m uv --version 2>/dev/null || echo uv)"

# ── 3. 目录结构 ──
echo ""
echo "3️⃣ 目录结构..."
mkdir -p "$SCCSOS_HOME"/{agents,workflows,personalities,wiki,config,data/{logs,traces},uv-cache}
echo "  ✅ $SCCSOS_HOME/"

# ── 4. 安装 Hermes Agent（官方脚本）──
echo ""
echo "4️⃣ Hermes Agent（官方 install.sh）..."

if [ -f "$HERMES_BIN" ]; then
  echo "  ↪ 已安装，跳过"
else
  # PATH 前置 python3.12 → install.sh 内部 python3 解析为 3.12
  PY312_DIR="$(dirname "$(command -v python3.12)")"
  export PATH="$PY312_DIR:$PATH"
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | \
    bash -s -- --skip-setup --skip-browser
  echo "  ✅ Hermes CLI: $HERMES_BIN"
fi
"$HERMES_BIN" --version

# ── 5. Hermes 初始配置 ──
mkdir -p "$SCCSOS_HOME/hermes/profiles/sccsos"
cat > "$SCCSOS_HOME/hermes/config.yaml" << 'EOF'
model:
  default: deepseek-v4-flash
  provider: deepseek
  base_url: "https://api.deepseek.com/v1"
EOF

# ── 6. Shell 环境变量（单引号 heredoc → 不展开，留 shell 变量引用）──
echo ""
echo "5️⃣ Shell 环境变量..."
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

# 当前会话（顶部已 export，此处保留只为可读性确认）
echo "  ✅ 当前会话: SCCSOS_HOME=$SCCSOS_HOME"

echo ""
echo "═══ Hermes 安装完成 ═══"
echo ""
echo "  下一步: source $RC_FILE && bash install-sccsos.sh"
