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
      org.sccsos.version="0.6.0" \
      org.sccsos.description="SCCS OS — Smart Agent Runtime Platform"

# Install system dependencies (hermes CLI needs git for some operations)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /sccsos

# Copy built wheel from builder
COPY --from=builder /build/dist/*.whl /tmp/

# Install SCCS OS
RUN pip install --no-cache-dir /tmp/*.whl && \
    rm /tmp/*.whl

# Create default directories
RUN mkdir -p /sccsos/data /sccsos/logs /sccsos/traces \
             /sccsos/agents /sccsos/workflows /sccsos/personalities

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

# Default: start API server
CMD ["python3", "-m", "sccsos.api.server", "--host", "0.0.0.0", "--port", "8765"]
