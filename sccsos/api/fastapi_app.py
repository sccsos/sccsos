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

from pathlib import Path
from typing import Any, Optional

# ── Optional dependency handling ───────────────────────────────────
try:
    from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
    from pydantic import BaseModel
except ImportError:
    raise ImportError(
        "sccsos[api] extras are required for the FastAPI server. "
        "Install with: pip install sccsos[api]"
    )

from sccsos.core.agent_runtime import AgentRuntime, get_runtime as _get_runtime
from sccsos.core.registry import AgentSpec
from sccsos.core.orchestrator import WorkflowDef
from sccsos.core.lifecycle import AgentStatus
from sccsos.core.event_bus import EventBus, WORKFLOW_STARTED, WORKFLOW_COMPLETED, WORKFLOW_FAILED
from sccsos.observability.logger import get_logger

logger = get_logger()


# ── Pydantic Models ────────────────────────────────────────────────


class RegisterAgentRequest(BaseModel):
    name: str
    version: str = "1.0"
    description: str = ""
    toolsets: list[str] = []
    tags: list[str] = []
    tenant_id: str = "default"


class AskRequest(BaseModel):
    prompt: str
    timeout: int = 300


class RunWorkflowRequest(BaseModel):
    file: str
    input: Optional[dict] = None


class ValidateWorkflowRequest(BaseModel):
    file: str


class ErrorResponse(BaseModel):
    error: str


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
    app = FastAPI(
        title="sccsos API",
        version="0.10.0",
        description="SCCS Operating System — Smart Agent Runtime API",
        docs_url="/docs",
    )

    # ── Health ───────────────────────────────────────────────────

    @app.get("/health")
    async def health():
        runtime = get_runtime()
        return runtime.health()

    # ── Agents ───────────────────────────────────────────────────

    @app.get("/agents")
    async def list_agents(
        tenant_id: str = Query("default", alias="X-Tenant-ID"),
    ):
        runtime = get_runtime()
        agents = [
            {
                "name": a.name,
                "version": a.version,
                "description": a.description[:60],
                "tenant_id": getattr(a, "tenant_id", tenant_id),
            }
            for a in runtime.registry.list()
        ]
        return {"agents": agents, "count": len(agents), "tenant_id": tenant_id}

    @app.post("/agents/register", status_code=201)
    async def register_agent(req: RegisterAgentRequest):
        runtime = get_runtime()
        spec = AgentSpec(
            name=req.name,
            version=req.version,
            description=req.description,
            toolsets=req.toolsets,
            tags=req.tags,
            tenant_id=req.tenant_id,
        )
        runtime.register_agent(spec)
        runtime.lifecycle.create(spec)
        return {"registered": spec.name}

    @app.get("/agents/{name}")
    async def agent_status(name: str, tenant_id: str = "default"):
        runtime = get_runtime()
        record = runtime.db.get_agent_by_name(name, tenant_id=tenant_id)
        if record:
            events = runtime.db.get_events(record["id"], limit=5)
            return {
                "id": record["id"],
                "name": name,
                "tenant_id": record.get("tenant_id", tenant_id),
                "status": record["status"],
                "profile": record["hermes_profile"],
                "session_id": record.get("session_id", ""),
                "events": [
                    {"event": e["event"], "detail": e.get("detail", "")}
                    for e in events
                ],
            }
        spec = runtime.registry.find(name)
        if spec:
            return {
                "name": spec.name,
                "status": "registered",
                "version": spec.version,
                "description": spec.description,
            }
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    @app.post("/agents/{name}/start")
    async def start_agent(name: str):
        runtime = get_runtime()
        spec = runtime.registry.find(name)
        if not spec:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        instance = runtime.lifecycle.create(spec)
        runtime.lifecycle.start(instance.id)
        profile = spec.profile or "sccsos"
        runtime.runner.start_agent(
            name, profile=profile,
            policy_engine=runtime.policy_engine,
            model=spec.model,
        )
        return {"started": instance.spec.name, "id": instance.id}

    @app.post("/agents/{name}/stop")
    async def stop_agent(name: str):
        runtime = get_runtime()
        runtime.runner.stop_agent(name)
        for inst in runtime.lifecycle.list_instances():
            if inst.spec.name == name and inst.status in (
                AgentStatus.RUNNING, AgentStatus.PAUSED, AgentStatus.FAILED
            ):
                runtime.lifecycle.stop(inst.id)
                return {"stopped": name}
        raise HTTPException(status_code=404, detail=f"No running instance of '{name}'")

    @app.post("/agents/{name}/pause")
    async def pause_agent(name: str):
        runtime = get_runtime()
        for inst in runtime.lifecycle.list_instances():
            if inst.spec.name == name and inst.status == AgentStatus.RUNNING:
                runtime.lifecycle.pause(inst.id)
                runtime.runner.pause_agent(name)
                return {"paused": name, "id": inst.id}
        raise HTTPException(status_code=404, detail=f"No running instance of '{name}'")

    @app.post("/agents/{name}/resume")
    async def resume_agent(name: str):
        runtime = get_runtime()
        for inst in runtime.lifecycle.list_instances():
            if inst.spec.name == name and inst.status == AgentStatus.PAUSED:
                runtime.lifecycle.resume(inst.id)
                runtime.runner.resume_agent(name)
                return {"resumed": name, "id": inst.id}
        raise HTTPException(status_code=404, detail=f"No paused instance of '{name}'")

    @app.post("/agents/{name}/restart")
    async def restart_agent(name: str):
        runtime = get_runtime()
        for inst in runtime.lifecycle.list_instances():
            if inst.spec.name == name:
                if inst.status == AgentStatus.FAILED:
                    runtime.lifecycle.restart(inst.id)
                elif inst.status == AgentStatus.RUNNING:
                    runtime.lifecycle.fail(inst.id, "restart requested")
                    runtime.lifecycle.restart(inst.id)
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot restart agent in '{inst.status.value}' state",
                    )
                runtime.runner.stop_agent(name)
                profile = inst.spec.profile or "sccsos"
                runtime.runner.start_agent(
                    name, profile=profile,
                    policy_engine=runtime.policy_engine,
                    model=inst.spec.model,
                )
                return {"restarted": name, "id": inst.id}
        raise HTTPException(status_code=404, detail=f"No instance of '{name}' found")

    @app.post("/agents/{name}/ask")
    async def ask_agent(name: str, req: AskRequest):
        runtime = get_runtime()
        result = runtime.runner.ask_agent(name, req.prompt, timeout=req.timeout)
        return {
            "response": result.response,
            "success": result.success,
            "error": result.error if not result.success else "",
        }

    # ── Workflows ───────────────────────────────────────────────

    @app.get("/workflows")
    async def list_workflows():
        runtime = get_runtime()
        runs = runtime.engine.list_runs(limit=20)
        return {"runs": runs, "count": len(runs)}

    @app.post("/workflows/run", status_code=201)
    async def run_workflow(req: RunWorkflowRequest):
        runtime = get_runtime()
        try:
            wf = WorkflowDef.from_yaml(req.file)
        except FileNotFoundError:
            raise HTTPException(status_code=400, detail=f"Workflow file not found: {req.file}")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid workflow: {e}")
        run_id = runtime.engine.execute(wf, input_data=req.input)
        status = runtime.engine.get_run_status(run_id)
        return {"run_id": run_id, "status": status["status"]}

    @app.post("/workflows/validate")
    async def validate_workflow(req: ValidateWorkflowRequest):
        runtime = get_runtime()
        try:
            wf = WorkflowDef.from_yaml(req.file)
            warnings = runtime.engine.validate(wf)
            return {
                "valid": len(warnings) == 0,
                "workflow": wf.name,
                "version": wf.version,
                "steps": len(wf.steps),
                "warnings": warnings,
            }
        except Exception as e:
            return {"valid": False, "error": str(e)}

    @app.get("/workflows/visualize")
    async def visualize_workflow(file: str = Query(...)):
        try:
            wf = WorkflowDef.from_yaml(file)
            mermaid = wf.to_mermaid()
            return {"workflow": wf.name, "mermaid": mermaid}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/workflows/{run_id}")
    async def workflow_status(run_id: str):
        runtime = get_runtime()
        try:
            return runtime.engine.get_run_status(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    @app.post("/workflows/{run_id}/cancel")
    async def cancel_workflow(run_id: str):
        runtime = get_runtime()
        try:
            runtime.engine.get_run_status(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        runtime.engine.cancel_run(run_id)
        return {"cancelled": run_id}

    # ── Traces ──────────────────────────────────────────────────

    @app.get("/traces")
    async def list_traces():
        runtime = get_runtime()
        tracer = runtime.tracer
        traces = tracer.list_traces(limit=20)
        return {"traces": traces, "count": len(traces)}

    @app.get("/traces/{trace_id}")
    async def trace_detail(trace_id: str):
        runtime = get_runtime()
        tracer = runtime.tracer
        spans = tracer.get_trace(trace_id)
        if not spans:
            raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found")
        return {"trace_id": trace_id, "spans": spans}

    # ── Audit ───────────────────────────────────────────────────

    @app.get("/audit/report")
    async def audit_report(since: str = "", agent: str = ""):
        runtime = get_runtime()
        report = runtime.auditor.generate_report(
            since=since if since else None,
            agent_id=agent if agent else None,
        )
        return report

    @app.get("/audit/log")
    async def audit_log(limit: int = 20, agent: str = ""):
        runtime = get_runtime()
        entries = runtime.auditor.list_recent(
            limit=limit,
            agent_id=agent if agent else None,
        )
        return {"entries": entries, "count": len(entries)}

    # ── Sessions ────────────────────────────────────────────────

    @app.get("/sessions")
    async def list_sessions(
        agent: str = "",
        tenant_id: str = "default",
        status: str = "",
    ):
        runtime = get_runtime()
        sessions = runtime.session_manager.list_sessions(
            agent_name=agent if agent else None,
            tenant_id=tenant_id,
            status=status if status else None,
        )
        return {
            "sessions": [
                {
                    "id": s.id,
                    "agent_name": s.agent_name,
                    "status": s.status,
                    "created_at": s.created_at,
                    "updated_at": s.updated_at,
                    "context_summary": s.context_summary,
                }
                for s in sessions
            ],
            "count": len(sessions),
        }

    @app.get("/sessions/{session_id}")
    async def session_detail(session_id: str):
        runtime = get_runtime()
        sessions = runtime.session_manager.list_sessions()
        session_obj = next((s for s in sessions if s.id == session_id), None)
        if session_obj is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        return {
            "id": session_obj.id,
            "agent_name": session_obj.agent_name,
            "status": session_obj.status,
            "created_at": session_obj.created_at,
            "updated_at": session_obj.updated_at,
            "context_summary": session_obj.context_summary,
        }

    @app.get("/sessions/{session_id}/messages")
    async def session_messages(session_id: str):
        runtime = get_runtime()
        messages = runtime.session_manager.get_history(session_id, limit=50)
        return {
            "session_id": session_id,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "tokens": m.tokens,
                    "created_at": m.created_at,
                }
                for m in messages
            ],
            "count": len(messages),
        }

    @app.post("/sessions/{session_id}/close")
    async def close_session(session_id: str):
        runtime = get_runtime()
        sessions = runtime.session_manager.list_sessions()
        session_obj = next((s for s in sessions if s.id == session_id), None)
        if session_obj is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        if session_obj.status == "closed":
            return {"closed": session_id}
        runtime.session_manager.close_session(session_id, new_status="closed")
        return {"closed": session_id}

    # ── WebSocket: Workflow Progress ──────────────────────────────

    connected_clients: set[WebSocket] = set()

    def _broadcast(event: str, **data: Any) -> None:
        """Broadcast a JSON message to all connected WebSocket clients."""
        import asyncio, json
        message = json.dumps({"event": event, **data}, ensure_ascii=False, default=str)
        for ws in list(connected_clients):
            try:
                # Schedule the send in the event loop
                asyncio.ensure_future(ws.send_text(message))
            except Exception:
                connected_clients.discard(ws)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        connected_clients.add(websocket)
        try:
            while True:
                await websocket.receive_text()  # Keep alive
        except WebSocketDisconnect:
            connected_clients.discard(websocket)

    # Wire EventBus → WebSocket broadcast
    bus = EventBus.get_instance()
    bus.on(WORKFLOW_STARTED, lambda **kw: _broadcast("workflow.started", **kw))
    bus.on(WORKFLOW_COMPLETED, lambda **kw: _broadcast("workflow.completed", **kw))
    bus.on(WORKFLOW_FAILED, lambda **kw: _broadcast("workflow.failed", **kw))

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
