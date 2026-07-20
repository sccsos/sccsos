"""FastAPI-based HTTP API Server for sccsos.

Replaces the previous ``http.server`` implementation with an async
FastAPI application that provides:

- Non-blocking request handling (uvicorn async workers)
- WebSocket endpoint for real-time workflow progress
- Auto-generated OpenAPI documentation at ``/docs``
- Higher concurrency for multiple simultaneous requests

Usage:
    python -m sccsos.api.fastapi_app --port 8080

Or via CLI:
    sccsos serve          # auto-detect: FastAPI if available, else legacy
    sccsos serve --legacy # force legacy http.server
"""

from __future__ import annotations

from typing import Any

# ── Optional dependency handling ───────────────────────────────────
try:
    from fastapi import FastAPI, WebSocket
except ImportError:
    raise ImportError(
        "sccsos[api] extras are required for the FastAPI server. "
        "Install with: pip install sccsos[api]"
    )

from sccsos.core.agent_runtime import AgentRuntime, get_runtime as _get_runtime
from sccsos.observability.logger import get_logger

from sccsos.api.routes.health import router as health_router
from sccsos.api.routes.agents import router as agents_router
from sccsos.api.routes.workflows import router as workflows_router
from sccsos.api.routes.sessions import router as sessions_router
from sccsos.api.routes.traces import router as traces_router
from sccsos.api.routes.audit import router as audit_router
from sccsos.api.routes.ws import websocket_handler, wire_eventbus
from sccsos.api.routes.skills import router as skills_router
from sccsos.api.routes.billing import router as billing_router
from sccsos.api.routes.quotas import router as quotas_router
from sccsos.api.routes.maintenance import router as maintenance_router
from sccsos.api.routes.webhooks import router as webhooks_router

logger = get_logger()


# ── Runtime helper ─────────────────────────────────────────────────


def get_runtime() -> AgentRuntime:
    """Get the shared AgentRuntime singleton (shared with CLI)."""
    runtime = _get_runtime()
    if not runtime.is_initialized:
        runtime.initialize()
    return runtime


# ── App factory ────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from sccsos._version import __version__ as sccsos_version
    app = FastAPI(
        title="sccsos API",
        version=sccsos_version,
        description="SCCS Operating System — Smart Agent Runtime API",
        docs_url="/docs",
    )

    API_V1 = "/api/v1"

    # ── Include routers (all mounted under /api/v1) ────────────────
    # Each router's prefix is defined in its own module; all share
    # the /api/v1 namespace.  When introducing v2, create a new set
    # of route modules under api/routes/v2/ and include them here
    # with a separate API_V2 prefix.
    app.include_router(health_router)
    app.include_router(agents_router)
    app.include_router(workflows_router)
    app.include_router(sessions_router)
    app.include_router(traces_router)
    app.include_router(audit_router)
    app.include_router(skills_router)
    app.include_router(billing_router)
    app.include_router(quotas_router)
    app.include_router(maintenance_router)
    app.include_router(webhooks_router)

    # ── WebSocket ────────────────────────────────────────────────
    @app.websocket(f"{API_V1}/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket_handler(websocket)

    # ── Admin console — Vue SPA ──────────────────────────────────
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles

    _static_dir = Path(__file__).parent / "static"
    if _static_dir.exists():
        app.mount("/admin", StaticFiles(directory=str(_static_dir), html=True), name="admin")
        logger.info("Vue admin console mounted at /admin (static: %s)", _static_dir)

    # Legacy single-page admin fallback
    _admin_html = Path(__file__).parent / "admin.html"
    if _admin_html.exists() and not _static_dir.exists():
        admin_content = _admin_html.read_text(encoding="utf-8")

        @app.get("/")
        @app.get("/admin")
        async def admin_page():
            from fastapi.responses import HTMLResponse
            return HTMLResponse(content=admin_content)

    # Wire EventBus → WebSocket broadcast
    wire_eventbus()

    return app


# ── Main entry point ────────────────────────────────────────────────


def run_server(host: str = "0.0.0.0", port: int = 8765, log_level: str = "info"):
    """Start the FastAPI server using uvicorn."""
    import uvicorn
    app = create_app()
    logger.info("sccsos FastAPI server running on http://%s:%s", host, port)
    logger.info("  API docs: http://%s:%s/docs", host, port)
    logger.info("  WebSocket: ws://%s:%s/ws", host, port)
    uvicorn.run(app, host=host, port=port, log_level=log_level)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="sccsos FastAPI Server")
    parser.add_argument("--port", "-p", type=int, default=8765, help="Port (default: 8765)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--log-level", default="info", help="Log level (default: info)")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, log_level=args.log_level)
