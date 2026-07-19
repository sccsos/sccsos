"""sccsos HTTP API Server — built-in, zero external dependencies.

Exposes all sccsos functionality via a lightweight JSON HTTP API
using Python's built-in ``http.server`` module.

Endpoints:
  GET  /health          — System health
  GET  /agents          — List agents
  POST /agents/register — Register an agent (POST JSON body)
  GET  /agents/{name}   — Agent status
  POST /agents/{name}/start — Start an agent
  POST /agents/{name}/stop  — Stop an agent
  POST /agents/{name}/pause — Pause a running agent
  POST /agents/{name}/resume — Resume a paused agent
  POST /agents/{name}/restart — Restart a failed agent
  POST /agents/{name}/ask — Send a prompt to a running agent
  GET  /workflows       — List recent workflow runs
  POST /workflows/run   — Run a workflow (POST JSON body)
  POST /workflows/validate — Validate a workflow YAML file
  GET  /workflows/visualize — Render workflow as Mermaid flowchart
  GET  /workflows/{id}  — Get workflow run status
  POST /workflows/{id}/cancel — Cancel a workflow run
  GET  /traces          — List recent traces
  GET  /traces/{id}     — Get trace details
  GET  /audit/report    — Audit summary report
  GET  /audit/log       — Recent audit log entries

Usage:
    python -m sccsos.api.server --port 8080
"""

from __future__ import annotations

import json
import traceback
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

import yaml

from sccsos.core.agent_runtime import AgentRuntime, get_runtime as _get_runtime
from sccsos.core.registry import AgentSpec
from sccsos.core.orchestrator import WorkflowDef
from sccsos.core.lifecycle import AgentStatus


def get_runtime() -> AgentRuntime:
    """Get the shared AgentRuntime singleton (shared with CLI)."""
    runtime = _get_runtime()
    if not runtime.is_initialized:
        runtime.initialize()
    return runtime


class APIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for sccsos API."""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = dict(urllib.parse.parse_qsl(parsed.query))
        tenant_id = self.headers.get("X-Tenant-ID", "default")

        try:
            if path == "/health" or path == "":
                self._json_response(get_runtime().health())
            elif path == "/agents":
                self._handle_list_agents(tenant_id)
            elif path.startswith("/agents/") and path.endswith("/start"):
                name = path.split("/")[2]
                self._handle_start_agent(name)
            elif path.startswith("/agents/") and path.endswith("/stop"):
                name = path.split("/")[2]
                self._handle_stop_agent(name)
            elif path.startswith("/agents/"):
                name = path.split("/")[2]
                self._handle_agent_status(name, tenant_id=tenant_id)
            elif path == "/workflows":
                self._handle_list_workflows()
            elif path == "/workflows/visualize":
                self._handle_visualize_workflow(params)
            elif path.startswith("/workflows/") and path.endswith("/cancel"):
                run_id = path.split("/")[2]
                self._handle_cancel_workflow(run_id)
            elif path.startswith("/workflows/"):
                run_id = path.split("/")[2]
                self._handle_workflow_status(run_id)
            elif path == "/traces":
                self._handle_list_traces()
            elif path.startswith("/traces/"):
                trace_id = path.split("/")[2]
                self._handle_trace_detail(trace_id)
            elif path == "/audit/report":
                self._handle_audit_report(params)
            elif path == "/audit/log":
                self._handle_audit_log(params)
            else:
                self._json_response({"error": "Not found"}, 404)
        except Exception as e:
            self._json_response({"error": str(e), "traceback": traceback.format_exc()}, 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        data = json.loads(body) if body else {}
        tenant_id = data.get("tenant_id", self.headers.get("X-Tenant-ID", "default"))

        try:
            if path == "/agents/register":
                data["tenant_id"] = tenant_id
                self._handle_register_agent(data)
            elif path.startswith("/agents/") and path.endswith("/ask"):
                name = path.split("/")[2]
                self._handle_ask_agent(name, data)
            elif path.startswith("/agents/") and path.endswith("/start"):
                name = path.split("/")[2]
                self._handle_start_agent(name)
            elif path.startswith("/agents/") and path.endswith("/stop"):
                name = path.split("/")[2]
                self._handle_stop_agent(name)
            elif path.startswith("/agents/") and path.endswith("/pause"):
                name = path.split("/")[2]
                self._handle_pause_agent(name)
            elif path.startswith("/agents/") and path.endswith("/resume"):
                name = path.split("/")[2]
                self._handle_resume_agent(name)
            elif path.startswith("/agents/") and path.endswith("/restart"):
                name = path.split("/")[2]
                self._handle_restart_agent(name)
            elif path == "/workflows/run":
                self._handle_run_workflow(data)
            elif path == "/workflows/validate":
                self._handle_validate_workflow(data)
            else:
                self._json_response({"error": "Not found"}, 404)
        except Exception as e:
            self._json_response({"error": str(e), "traceback": traceback.format_exc()}, 500)

    # ── Handlers ───────────────────────────────────────────────

    def _handle_list_agents(self, tenant_id: str = "default"):
        runtime = get_runtime()
        agents = [
            {"name": a.name, "version": a.version, "description": a.description[:60],
             "tenant_id": getattr(a, 'tenant_id', tenant_id)}
            for a in runtime.registry.list()
        ]
        self._json_response({"agents": agents, "count": len(agents), "tenant_id": tenant_id})

    def _handle_agent_status(self, name: str, tenant_id: str = "default"):
        runtime = get_runtime()
        # Check DB first (lifecycle instances)
        record = runtime.db.get_agent_by_name(name, tenant_id=tenant_id)
        if record:
            events = runtime.db.get_events(record["id"], limit=5)
            self._json_response({
                "id": record["id"],
                "name": name,
                "tenant_id": record.get("tenant_id", tenant_id),
                "status": record["status"],
                "profile": record["hermes_profile"],
                "session_id": record.get("session_id", ""),
                "events": [{"event": e["event"], "detail": e.get("detail", "")}
                           for e in events],
            })
            return
        # Check registry (registered but not yet started)
        spec = runtime.registry.find(name)
        if spec:
            self._json_response({
                "name": spec.name,
                "status": "registered",
                "version": spec.version,
                "description": spec.description,
            })
            return
        self._json_response({"error": f"Agent '{name}' not found"}, 404)

    def _handle_register_agent(self, data: dict):
        spec = AgentSpec(
            name=data.get("name", "unnamed"),
            version=data.get("version", "1.0"),
            description=data.get("description", ""),
            toolsets=data.get("toolsets", []),
            tags=data.get("tags", []),
            tenant_id=data.get("tenant_id", "default"),
        )
        runtime = get_runtime()
        runtime.register_agent(spec)
        # Also create a lifecycle instance so API can manage state
        runtime.lifecycle.create(spec)
        self._json_response({"registered": spec.name}, 201)

    def _handle_start_agent(self, name: str):
        runtime = get_runtime()
        spec = runtime.registry.find(name)
        if not spec:
            self._json_response({"error": f"Agent '{name}' not found"}, 404)
            return
        instance = runtime.lifecycle.create(spec)
        runtime.lifecycle.start(instance.id)
        # Start background runner
        profile = spec.profile or "sccsos"
        runtime.runner.start_agent(
            name, profile=profile,
            policy_engine=runtime.policy_engine,
            model=spec.model,
        )
        self._json_response({"started": instance.spec.name, "id": instance.id})

    def _handle_stop_agent(self, name: str):
        runtime = get_runtime()
        # Stop background runner first
        runtime.runner.stop_agent(name)
        for inst in runtime.lifecycle.list_instances():
            if inst.spec.name == name and inst.status in (
                AgentStatus.RUNNING, AgentStatus.PAUSED, AgentStatus.FAILED
            ):
                runtime.lifecycle.stop(inst.id)
                self._json_response({"stopped": name})
                return
        self._json_response({"error": f"No running instance of '{name}'"}, 404)

    def _handle_pause_agent(self, name: str):
        """Pause a running agent: RUNNING → PAUSED."""
        runtime = get_runtime()
        for inst in runtime.lifecycle.list_instances():
            if inst.spec.name == name and inst.status == AgentStatus.RUNNING:
                runtime.lifecycle.pause(inst.id)
                runtime.runner.pause_agent(name)
                self._json_response({"paused": name, "id": inst.id})
                return
        self._json_response({"error": f"No running instance of '{name}'"}, 404)

    def _handle_resume_agent(self, name: str):
        """Resume a paused agent: PAUSED → RUNNING."""
        runtime = get_runtime()
        for inst in runtime.lifecycle.list_instances():
            if inst.spec.name == name and inst.status == AgentStatus.PAUSED:
                runtime.lifecycle.resume(inst.id)
                runtime.runner.resume_agent(name)
                self._json_response({"resumed": name, "id": inst.id})
                return
        self._json_response({"error": f"No paused instance of '{name}'"}, 404)

    def _handle_restart_agent(self, name: str):
        """Restart an agent from RUNNING or FAILED state."""
        runtime = get_runtime()
        for inst in runtime.lifecycle.list_instances():
            if inst.spec.name == name:
                if inst.status == AgentStatus.FAILED:
                    runtime.lifecycle.restart(inst.id)
                elif inst.status == AgentStatus.RUNNING:
                    runtime.lifecycle.fail(inst.id, "restart requested")
                    runtime.lifecycle.restart(inst.id)
                else:
                    self._json_response({"error": f"Cannot restart agent in '{inst.status.value}' state"}, 400)
                    return
                # Restart background runner
                runtime.runner.stop_agent(name)
                profile = inst.spec.profile or "sccsos"
                runtime.runner.start_agent(
                    name, profile=profile,
                    policy_engine=runtime.policy_engine,
                    model=inst.spec.model,
                )
                self._json_response({"restarted": name, "id": inst.id})
                return
        self._json_response({"error": f"No instance of '{name}' found"}, 404)

    def _handle_ask_agent(self, name: str, data: dict):
        """Send a prompt to a running agent and return the response."""
        prompt = data.get("prompt", "")
        if not prompt:
            self._json_response({"error": "Missing 'prompt' in request body"}, 400)
            return
        runtime = get_runtime()
        timeout = data.get("timeout", 300)
        result = runtime.runner.ask_agent(name, prompt, timeout=timeout)
        self._json_response({
            "response": result.response,
            "success": result.success,
            "error": result.error if not result.success else "",
        })

    def _handle_list_workflows(self):
        runtime = get_runtime()
        runs = runtime.engine.list_runs(limit=20)
        self._json_response({"runs": runs, "count": len(runs)})

    def _handle_run_workflow(self, data: dict):
        file_path = data.get("file", "")
        if not file_path:
            self._json_response({"error": "Missing 'file' in request body"}, 400)
            return
        wf = WorkflowDef.from_yaml(file_path)
        input_data = data.get("input")
        runtime = get_runtime()

        # ── Policy pre-flight check ──────────────────────────────
        pe = getattr(runtime.engine, '_policy_engine', None)
        if pe is not None:
            estimated_cost = max(0.001, len(yaml.dump(wf)) * 0.0001)
            from sccsos.security.policy import PolicyViolation
            result = pe.check_delegation(
                agent_name="api",
                model="deepseek-v4-flash",
                estimated_cost=estimated_cost,
            )
            if not result.allowed:
                self._json_response({"error": f"Policy rejected: {result.reason}"}, 403)
                return

        run_id = runtime.engine.execute(wf, input_data=input_data)
        status = runtime.engine.get_run_status(run_id)
        self._json_response({"run_id": run_id, "status": status["status"]}, 201)

    def _handle_validate_workflow(self, data: dict):
        """Validate a workflow YAML file."""
        file_path = data.get("file", "")
        if not file_path:
            self._json_response({"error": "Missing 'file' in request body"}, 400)
            return
        runtime = get_runtime()
        try:
            wf = WorkflowDef.from_yaml(file_path)
            warnings = runtime.engine.validate(wf)
            self._json_response({
                "valid": len(warnings) == 0,
                "workflow": wf.name,
                "version": wf.version,
                "steps": len(wf.steps),
                "warnings": warnings,
            })
        except Exception as e:
            self._json_response({"valid": False, "error": str(e)}, 400)

    def _handle_visualize_workflow(self, params: dict):
        """Render a workflow as a Mermaid flowchart."""
        file_path = params.get("file", "")
        if not file_path:
            self._json_response({"error": "Missing 'file' query parameter"}, 400)
            return
        try:
            wf = WorkflowDef.from_yaml(file_path)
            mermaid = wf.to_mermaid()
            self._json_response({
                "workflow": wf.name,
                "mermaid": mermaid,
            })
        except Exception as e:
            self._json_response({"error": str(e)}, 400)

    def _handle_workflow_status(self, run_id: str):
        runtime = get_runtime()
        try:
            status = runtime.engine.get_run_status(run_id)
            self._json_response(status)
        except KeyError:
            self._json_response({"error": f"Run '{run_id}' not found"}, 404)

    def _handle_cancel_workflow(self, run_id: str):
        runtime = get_runtime()
        # Verify run exists before cancelling
        try:
            runtime.engine.get_run_status(run_id)
        except KeyError:
            self._json_response({"error": f"Run '{run_id}' not found"}, 404)
            return
        runtime.engine.cancel_run(run_id)
        self._json_response({"cancelled": run_id})

    def _handle_list_traces(self):
        runtime = get_runtime()
        tracer = runtime.tracer
        traces = tracer.list_traces(limit=20)
        self._json_response({"traces": traces, "count": len(traces)})

    def _handle_trace_detail(self, trace_id: str):
        runtime = get_runtime()
        tracer = runtime.tracer
        spans = tracer.get_trace(trace_id)
        if not spans:
            self._json_response({"error": f"Trace '{trace_id}' not found"}, 404)
            return
        self._json_response({"trace_id": trace_id, "spans": spans})

    def _handle_audit_report(self, params: dict):
        runtime = get_runtime()
        auditor = runtime.auditor
        report = auditor.generate_report(
            since=params.get("since") or None,
            agent_id=params.get("agent") or None,
        )
        self._json_response(report)

    def _handle_audit_log(self, params: dict):
        runtime = get_runtime()
        auditor = runtime.auditor
        limit = int(params.get("limit", 20))
        entries = auditor.list_recent(
            limit=limit,
            agent_id=params.get("agent") or None,
        )
        self._json_response({"entries": entries, "count": len(entries)})

    # ── Response helpers ──────────────────────────────────────

    def _json_response(self, data, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))

    def log_message(self, format, *args):
        """Suppress default stderr logging (too noisy)."""
        pass


def run_server(host: str = "0.0.0.0", port: int = 8765):
    """Start the sccsos HTTP API server."""
    server = HTTPServer((host, port), APIHandler)
    print(f"sccsos API server running on http://{host}:{port}")
    print(f"  Endpoints: /health /agents /workflows /traces /audit")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="sccsos HTTP API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
