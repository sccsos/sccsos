#!/usr/bin/env bash
# SCCS OS + Hermes Agent 一键安装脚本 (Ubuntu / Python 3.12)
# Usage: bash <(curl -fsSL https://raw.githubusercontent.com/sccsos/sccsos/v0.20.10/scripts/install-ubuntu.sh)
set -euo pipefail

SCCSOS_HOME="${SCCSOS_HOME:-$HOME/sccsos}"
HERMES_VERSION="${HERMES_VERSION:-0.20.10}"
SCCSOS_VERSION="${SCCSOS_VERSION:-0.20.10}"
PYTHON="${PYTHON:-python3.12}"

echo "═══ SCCS OS + Hermes Agent 一键安装 ═══"
echo "  Target:  $SCCSOS_HOME"
echo "  Python:  $PYTHON"
echo ""

# ── 1. 系统依赖 + Python 3.12 ──
echo "1️⃣ 安装系统依赖 + Python 3.12..."
sudo apt-get update -qq
# Ubuntu 24.04+ 自带 python3.12；更早版本需 deadsnakes PPA
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
echo "2️⃣ 创建目录结构..."
mkdir -p "$SCCSOS_HOME"/{agents,workflows,personalities,wiki,config,data/{logs,traces},hermes,uv-cache}
mkdir -p "$SCCSOS_HOME"/hermes/profiles/sccsos

# ── 3. sccsos.yaml ──
echo ""
echo "3️⃣ 生成 sccsos.yaml..."
cat > "$SCCSOS_HOME/sccsos.yaml" << YAML
project:
  name: sccsos
  version: $SCCSOS_VERSION
hermes:
  profile: sccsos
  binary: $SCCSOS_HOME/hermes-agent/venv/bin/hermes
  home: $SCCSOS_HOME/hermes
  install_dir: $SCCSOS_HOME/hermes-agent
  adapter: subprocess
  setup:
    provider: deepseek
    model: deepseek-v4-flash
    api_key: "\${DEEPSEEK_API_KEY}"
    base_url: "https://api.deepseek.com/v1"
database:
  driver: sqlite
  path: $SCCSOS_HOME/data/sccsos.db
defaults:
  hermes_profile: sccsos
logging:
  level: INFO
  format: json
  directory: $SCCSOS_HOME/data/logs
agents:
  path: $SCCSOS_HOME/agents
  wiki_path: $SCCSOS_HOME/wiki
  personalities_path: $SCCSOS_HOME/personalities
  knowledge:
    mode: local
    vector_backend: tfidf
pricing:
  path: $SCCSOS_HOME/config/pricing.json
YAML

# ── 4. 安装 Hermes Agent ──
echo ""
echo "4️⃣ 安装 Hermes Agent (Python 3.12)..."
if [ -d "$SCCSOS_HOME/hermes-agent" ]; then
  echo "  ↪ Hermes Agent 已存在，更新..."
  cd "$SCCSOS_HOME/hermes-agent" && git pull
else
  git clone --depth 1 --branch v$HERMES_VERSION \
    https://github.com/NousResearch/hermes-agent.git \
    "$SCCSOS_HOME/hermes-agent"
fi

"$PYTHON" -m venv "$SCCSOS_HOME/hermes-agent/venv"
source "$SCCSOS_HOME/hermes-agent/venv/bin/activate"
pip install --quiet -e "$SCCSOS_HOME/hermes-agent"
deactivate
echo "  ✅ Hermes CLI: $SCCSOS_HOME/hermes-agent/venv/bin/hermes"

# ── 5. Hermes config + pricing ──
echo ""
echo "5️⃣ 配置 Hermes + 定价表..."
cat > "$SCCSOS_HOME/hermes/config.yaml" << 'HERMES_YAML'
model:
  default: deepseek-v4-flash
  provider: deepseek
  base_url: "https://api.deepseek.com/v1"
HERMES_YAML

cat > "$SCCSOS_HOME/config/pricing.json" << 'PRICING'
{
  "models": {
    "deepseek-v4-flash": [0.14, 0.28],
    "deepseek-v4-pro": [0.44, 0.87],
    "gpt-4o": [2.50, 10.00],
    "claude-sonnet-4": [3.00, 15.00]
  },
  "default_input_price": 0.50,
  "default_output_price": 2.00,
  "version": 1
}
PRICING

# ── 6. Shell 环境变量 ──
echo ""
echo "6️⃣ 配置 Shell 环境变量..."
detect_rc() {
  case "${SHELL:-bash}" in
    *zsh) echo "${ZDOTDIR:-$HOME}/.zshrc" ;;
    *bash) echo "$HOME/.bashrc" ;;
    *) echo "$HOME/.profile" ;;
  esac
}
RC_FILE="$(detect_rc)"

HERMES_BIN="$SCCSOS_HOME/hermes-agent/venv/bin/hermes"
HERMES_BIN_DIR="$SCCSOS_HOME/hermes-agent/venv/bin"

if grep -q "SCCSOS_HOME" "$RC_FILE" 2>/dev/null; then
  echo "  ⏭  环境变量已在 $RC_FILE 中存在，跳过"
else
  cat >> "$RC_FILE" << RC_EOF

# ── SCCS OS + Hermes Agent ──
export SCCSOS_HOME="$SCCSOS_HOME"
export HERMES_HOME="\$SCCSOS_HOME/hermes"
export HERMES_CONFIG_PATH="\$SCCSOS_HOME/hermes"
export HERMES_INSTALL_DIR="\$SCCSOS_HOME/hermes-agent"
export HERMES_BIN="\$SCCSOS_HOME/hermes-agent/venv/bin/hermes"
export HERMES_BIN_DIR="\$SCCSOS_HOME/hermes-agent/venv/bin"
export PATH="\$HERMES_BIN_DIR:\$PATH"
# ── ──
RC_EOF
  echo "  ✅ 已写入 $RC_FILE"
fi

export SCCSOS_HOME HERMES_HOME HERMES_CONFIG_PATH
export HERMES_INSTALL_DIR HERMES_BIN HERMES_BIN_DIR
export PATH="$HERMES_BIN_DIR:$PATH"

# ── 7. 安装 SCCS OS ──
echo ""
echo "7️⃣ 安装 SCCS OS..."
"$PYTHON" -m pip install --quiet "sccsos[api]" 2>/dev/null || \
  pip3 install --quiet "sccsos[api]"
echo "  ✅ SCCS OS $SCCSOS_VERSION"

# ── 8. 验证 ──
echo ""
echo "8️⃣ 验证..."
echo -n "  python:  "; $PYTHON --version
echo -n "  sccsos:  "; python3 -m sccsos --version 2>/dev/null || echo "source $RC_FILE"
echo -n "  hermes:  "; "$HERMES_BIN" --version 2>/dev/null || echo "see above"

echo ""
echo "═══ 安装完成 ═══"
echo ""
echo "  加载环境变量:  source $RC_FILE"
echo "  配置 API Key:  export DEEPSEEK_API_KEY=\"sk-***\""
echo "  同步配置:      cd ~/sccsos && sccsos hermes config-sync"
echo "  启动服务:      cd ~/sccsos && python3 -m sccsos serve"
echo "  测试:          curl http://localhost:8765/api/v1/health"
