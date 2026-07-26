#!/usr/bin/env bash
# Hermes Agent 安装脚本 (Ubuntu / Python 3.12)
# 使用官方 install.sh，路径收拢至 ~/sccsos/
# 必须先于 install-sccsos.sh 执行
set -euo pipefail

SCCSOS_HOME="${SCCSOS_HOME:-$HOME/sccsos}"
PYTHON="${PYTHON:-python3.12}"

echo "═══ Hermes Agent 安装 ═══"
echo "  Target:  $SCCSOS_HOME"
echo "  Python:  $PYTHON"
echo ""

# ── 1. 系统依赖 + Python 3.12 ──
echo "1️⃣ 系统依赖 + Python 3.12..."
sudo apt-get update -qq
if ! command -v "$PYTHON" &>/dev/null; then
  if grep -qi "24.04\|24.10\|25.04" /etc/os-release 2>/dev/null; then
    sudo apt-get install -y -qq python3.12 python3.12-venv python3.12-pip 2>&1 | tail -1
  else
    sudo apt-get install -y -qq software-properties-common 2>&1 | tail -1
    sudo add-apt-repository -y ppa:deadsnakes/ppa -s 2>&1 | tail -1
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3.12 python3.12-venv python3.12-pip 2>&1 | tail -1
  fi
fi
sudo apt-get install -y -qq git curl xz-utils build-essential 2>&1 | tail -1
echo "  ✅ $($PYTHON --version)"

# ── 2. 目录结构 ──
echo ""
echo "2️⃣ 目录结构..."
mkdir -p "$SCCSOS_HOME"/{agents,workflows,personalities,wiki,config,data/{logs,traces},uv-cache}
echo "  ✅ $SCCSOS_HOME/"

# ── 3. 安装 Hermes Agent（官方脚本）──
echo ""
echo "3️⃣ Hermes Agent（官方 install.sh）..."
# 设置环境变量重定向安装路径：
#   HERMES_HOME      → ~/sccsos/hermes     （数据：profiles/skills/memories）
#   HERMES_CODE_PATH → ~/sccsos/hermes-agent（源码安装目录）
export HERMES_HOME="$SCCSOS_HOME/hermes"
export HERMES_CODE_PATH="$SCCSOS_HOME/hermes-agent"

# 如果已安装，跳过
if [ -f "$HERMES_CODE_PATH/venv/bin/hermes" ]; then
  echo "  ↪ Hermes Agent 已安装，跳过"
else
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | \
    bash -s -- --no-venv --skip-setup --skip-browser
  echo "  ✅ Hermes CLI: $HERMES_CODE_PATH/venv/bin/hermes"
fi

# 验证
"$HERMES_CODE_PATH/venv/bin/hermes" --version

# ── 4. Hermes 空配置 ──
mkdir -p "$SCCSOS_HOME/hermes/profiles/sccsos"
cat > "$SCCSOS_HOME/hermes/config.yaml" << 'HERMES_YAML'
model:
  default: deepseek-v4-flash
  provider: deepseek
  base_url: "https://api.deepseek.com/v1"
HERMES_YAML

# ── 5. Shell 环境变量 ──
echo ""
echo "4️⃣ Shell 环境变量..."
detect_rc() {
  case "${SHELL:-bash}" in
    *zsh) echo "${ZDOTDIR:-$HOME}/.zshrc" ;;
    *bash) echo "$HOME/.bashrc" ;;
    *) echo "$HOME/.profile" ;;
  esac
}
RC_FILE="$(detect_rc)"

if grep -q "SCCSOS_HOME" "$RC_FILE" 2>/dev/null; then
  echo "  ⏭  环境变量已在 $RC_FILE 中存在，跳过"
else
  cat >> "$RC_FILE" << 'RC_EOF'

# ── SCCS OS + Hermes Agent ──
export SCCSOS_HOME="$HOME/sccsos"
export HERMES_HOME="$SCCSOS_HOME/hermes"
export HERMES_CONFIG_PATH="$SCCSOS_HOME/hermes"
export HERMES_INSTALL_DIR="$SCCSOS_HOME/hermes-agent"
export HERMES_BIN="$SCCSOS_HOME/hermes-agent/venv/bin/hermes"
export HERMES_BIN_DIR="$SCCSOS_HOME/hermes-agent/venv/bin"
export PATH="$HERMES_BIN_DIR:$PATH"
# ── ──
RC_EOF
  echo "  ✅ 写入 $RC_FILE"
fi

# 立即导出到当前会话
export SCCSOS_HOME HERMES_HOME HERMES_CONFIG_PATH
export HERMES_INSTALL_DIR HERMES_BIN HERMES_BIN_DIR
export PATH="$HERMES_BIN_DIR:$PATH"

echo ""
echo "═══ Hermes 安装完成 ═══"
echo ""
echo "  下一步: source $RC_FILE && bash install-sccsos.sh"
