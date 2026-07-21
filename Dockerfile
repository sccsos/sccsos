# SCCS OS — Docker Image
# Stage 1: Build wheel
FROM python:3.11-slim AS builder

WORKDIR /build
COPY . .
RUN pip install --no-cache-dir build && \
    python3 -m build --wheel --sdist && \
    echo "Build complete"

# Stage 2: Runtime
FROM python:3.11-slim

LABEL org.sccsos.name="sccsos" \
      org.sccsos.version="0.14.2" \
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
    pip install --no-cache-dir "sccsos[api] @ file:///tmp/sccsos-0.14.2-py3-none-any.whl" && \
    rm /tmp/*.whl

# Install Hermes Agent CLI (so SCCS OS can delegate tasks inside the container)
RUN pip install --no-cache-dir hermes-agent && \
    hermes --version && \
    echo "Hermes Agent installed successfully"

# Set up Hermes HOME directory and default profile
ENV HERMES_HOME=/sccsos/hermes
RUN mkdir -p ${HERMES_HOME}/skills ${HERMES_HOME}/sessions ${HERMES_HOME}/memories ${HERMES_HOME}/cron \
    && hermes config set --profile sccsos provider deepseek \
    && hermes config set --profile sccsos model deepseek-v4-flash \
    || echo "Hermes profile init deferred (no API key in build)"

# Create default directories
RUN mkdir -p /sccsos/data /sccsos/logs /sccsos/traces \
             /sccsos/agents /sccsos/workflows /sccsos/personalities \
             /sccsos/config

# Copy default config
COPY sccsos.yaml /sccsos/sccsos.yaml
COPY personalities/ /sccsos/personalities/
COPY workflows/ /sccsos/workflows/

# Volume for persistent data
VOLUME ["/sccsos/data", "/sccsos/logs", "/sccsos/traces"]

# Expose API port
EXPOSE 8765

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -m sccsos health || exit 1

# Default: start API server (auto-detects FastAPI)
CMD ["python3", "-m", "sccsos", "serve", "--host", "0.0.0.0", "--port", "8765"]
