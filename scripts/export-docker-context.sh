#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# SCCS OS — 导出 Docker 构建上下文
#
# 根据 Dockerfile 的实际依赖（COPY / python -m build），
# 将最小必要文件复制到 dist/docker-build/，用于构建容器镜像。
#
# 用法：
#   ./scripts/export-docker-context.sh
#
# 构建：
#   cd dist/docker-build/
#   docker build -t sccsos:0.15.5 .
#   docker build -t sccsos:0.15.5-slim -f Dockerfile.slim .
#   docker build -t sccsos-hermes:0.15.5 -f Dockerfile.hermes .
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="${ROOT}/dist/docker-build"

echo "📦 导出 Docker 构建上下文 → ${DIST}/"
rm -rf "$DIST"
mkdir -p "$DIST"

# ── Dockerfile（3 份） ──────────────────────────────────────────────
cp "$ROOT/Dockerfile"         "$DIST/"
cp "$ROOT/Dockerfile.slim"    "$DIST/"
cp "$ROOT/Dockerfile.hermes"  "$DIST/"
cp "$ROOT/.dockerignore"      "$DIST/"

# ── WHL 文件（预构建，替代 sccsos 源码） ────────────────────────────
WHL=$(ls "$ROOT"/dist/sccsos-*-py3-none-any.whl 2>/dev/null | sort -V | tail -1)
if [ -z "$WHL" ]; then
    echo "❌ 未找到 dist/sccsos-*.whl，请先构建：python -m build --wheel"
    exit 1
fi
cp "$WHL" "$DIST/sccsos-0.15.5-py3-none-any.whl"

# ── Hermes Agent：构建时通过官方 install.sh 在线安装 ──────────────────
# 镜像内通过 curl ... install.sh | bash 安装，无需本地源码复制
echo "   Hermes Agent 将在 Docker build 时通过官方 install.sh 安装"

# ── Hermes 预配置数据目录 ──────────────────────────────────────────
mkdir -p "$DIST/deploy"
cp -R "$ROOT/deploy/hermes-home" "$DIST/deploy/hermes-home"

# ── 运行时 COPY 进镜像：配置 / 角色 / 工作流 ─────────────────────────
cp "$ROOT/sccsos.yaml"        "$DIST/"
cp -R "$ROOT/personalities"   "$DIST/personalities"
cp -R "$ROOT/workflows"       "$DIST/workflows"

# ── 清理 __pycache__ ───────────────────────────────────────────────
find "$DIST" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
find "$DIST" -name '*.pyc' -delete

echo "✅ 完成  ($(du -sh "$DIST" | cut -f1))"
echo ""
echo "构建命令："
echo "  cd ${DIST}/"
echo "  docker build -t sccsos:0.15.5 ."
echo "  docker build -t sccsos:0.15.5-slim -f Dockerfile.slim ."
echo "  docker build -t sccsos-hermes:0.15.5 -f Dockerfile.hermes ."
