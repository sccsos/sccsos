#!/usr/bin/env bash
# SCCS OS 安装脚本 (Ubuntu / Python 3.12)
# 必须在 install-hermes.sh 成功执行后运行
set -euo pipefail

SCCSOS_HOME="${SCCSOS_HOME:-$HOME/sccsos}"
SCCSOS_VERSION="${SCCSOS_VERSION:-0.20.11}"

echo "═══ SCCS OS 安装 ═══"
echo "  Target:  $SCCSOS_HOME"
echo ""

# ── 前置检查 ──
echo "0️⃣ 前置检查..."
if [ ! -f "$SCCSOS_HOME/hermes-agent/venv/bin/hermes" ]; then
  echo "  ❌ Hermes Agent 未安装。请先执行: bash install-hermes.sh"
  exit 1
fi
if [ ! -f "$SCCSOS_HOME/hermes/config.yaml" ]; then
  echo "  ❌ Hermes 配置缺失。请先执行: bash install-hermes.sh"
  exit 1
fi
echo "  ✅ Hermes Agent 已就绪"

# ── 1. sccsos.yaml ──
echo ""
echo "1️⃣ sccsos.yaml..."
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
echo "  ✅ $SCCSOS_HOME/sccsos.yaml"

# ── 2. 定价表 ──
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

# ── 3. 安装 SCCS OS ──
echo ""
echo "2️⃣ SCCS OS (pip)..."
pip3 install --quiet "sccsos[api]" 2>/dev/null || \
  python3 -m pip install --quiet "sccsos[api]"
echo "  ✅ SCCS OS $SCCSOS_VERSION"

# ── 4. config-sync ──
echo ""
echo "3️⃣ 配置同步..."
cd "$SCCSOS_HOME"
if sccsos hermes config-sync 2>/dev/null; then
  echo "  ✅ sccsos.yaml → Hermes Profile 同步完成"
else
  echo "  ⚠️  config-sync 跳过（需先设置 DEEPSEEK_API_KEY）"
  echo "     后续执行: cd ~/sccsos && export DEEPSEEK_API_KEY=*** && sccsos hermes config-sync"
fi

# ── 5. 验证 ──
echo ""
echo "4️⃣ 验证..."
echo -n "  sccsos: "; python3 -m sccsos --version 2>/dev/null || echo "(需 source ~/.bashrc)"
echo -n "  hermes: "; "$SCCSOS_HOME/hermes-agent/venv/bin/hermes" --version 2>/dev/null || echo "(需 source ~/.bashrc)"

echo ""
echo "═══ SCCS OS 安装完成 ═══"
echo ""
echo "  配置 API Key:  export DEEPSEEK_API_KEY=\"sk-***\" && sccsos hermes config-sync"
echo "  启动服务:      cd ~/sccsos && python3 -m sccsos serve"
echo "  测试:          curl http://localhost:8765/api/v1/health"
