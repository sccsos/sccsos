# SCCS OS — Docker Image
# Stage 1: Build wheel
FROM python:3.11-slim AS builder

WORKDIR /build
COPY . .
RUN pip install --no-cache-dir build && \
    python3 -m build --wheel && \
    echo "Build complete"

# Stage 2: Runtime
FROM python:3.11-slim

LABEL org.sccsos.name="sccsos" \
      org.sccsos.version="0.16.0" \
      org.sccsos.description="SCCS OS — Smart Agent Runtime Platform"

# Install system dependencies (Hermes CLI needs git/curl/xz-utils for git-installer; curl for health)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /sccsos

# Copy built wheel from builder
COPY --from=builder /build/dist/*.whl /tmp/

# Install SCCS OS with API extras
RUN pip install --no-cache-dir /tmp/*.whl && \
    pip install --no-cache-dir "sccsos[api] @ file:///tmp/sccsos-0.16.0-py3-none-any.whl" && \
    rm /tmp/*.whl

# ── Hermes Agent：官方安装脚本（root FHS 布局） ─────────────────────
# curl → install.sh 使用 --no-venv（复用系统 Python）、
# --skip-setup（跳过交互配置）、--skip-browser（浏览器工具非必须）
RUN curl -fsSL https://hermes-agent.nousresearch.com/install.sh | \
    bash -s -- --no-venv --skip-setup --skip-browser && \
    hermes --version && \
    echo "Hermes installed via official install script"

# ── Hermes HOME：拷贝预配置的数据目录（profile/skills/配置） ─────
ENV HERMES_HOME=/sccsos/hermes
COPY deploy/hermes-home/ ${HERMES_HOME}/

# 调整路径：将 config.yaml 中的宿主路径替换为容器路径
RUN sed -i "s|cwd: /.*|cwd: /sccsos|" ${HERMES_HOME}/profiles/sccsos/config.yaml 2>/dev/null || true

# Create default directories
RUN mkdir -p /sccsos/data /sccsos/logs /sccsos/traces \
             /sccsos/agents /sccsos/workflows /sccsos/personalities \
             /sccsos/config

# Copy default config
COPY sccsos.yaml /sccsos/sccsos.yaml
COPY personalities/ /sccsos/personalities/
COPY workflows/ /sccsos/workflows/

# Volume for persistent data
VOLUME ["/sccsos/data", "/sccsos/logs", "/sccsos/traces", "/sccsos/hermes"]

# Expose API port
EXPOSE 8765

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -m sccsos health || exit 1

# Default: start API server (auto-detects FastAPI)
CMD ["python3", "-m", "sccsos", "serve", "--host", "0.0.0.0", "--port", "8765"]
