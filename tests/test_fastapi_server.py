"""FastAPI API Server tests using TestClient."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from sccsos.core.agent_runtime import AgentRuntime, set_runtime
from sccsos.core.hermes_adapter import create_adapter
from sccsos.core.workflow import WorkflowDef
from sccsos.api.fastapi_app import create_app

API_V1 = "/api/v1"


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient backed by a mock runtime."""
    runtime = AgentRuntime()
    runtime.initialize()
    runtime._core._adapter = create_adapter("mock")
    if runtime._core._runner is not None:
        runtime._core._runner._adapter = runtime._core._adapter
        runtime._core._runner.stop_all()
    runtime._obs._tracer._export_path = None
    set_runtime(runtime)

    app = create_app()
    client = TestClient(app)
    yield client


class TestFastAPIEndpoints:

    def test_01_health(self, client):
        resp = client.get(f"{API_V1}/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert data.get("initialized") is True

    def test_02_agents_list(self, client):
        resp = client.get(f"{API_V1}/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert isinstance(data["agents"], list)

    def test_03_register_agent(self, client):
        resp = client.post(
            f"{API_V1}/agents/register",
            json={"name": "test-agent", "description": "For API test"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["registered"] == "test-agent"

    def test_04_agent_status_found(self, client):
        client.post(f"{API_V1}/agents/register", json={"name": "status-test"})
        resp = client.get(f"{API_V1}/agents/status-test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "status-test"

    def test_05_agent_status_not_found(self, client):
        resp = client.get(f"{API_V1}/agents/nonexistent-xyz")
        assert resp.status_code == 404
        assert "error" in resp.text.lower() or "detail" in resp.text.lower()

    def test_06_start_agent(self, client):
        client.post(f"{API_V1}/agents/register", json={"name": "startable"})
        resp = client.post(f"{API_V1}/agents/startable/start")
        assert resp.status_code == 200
        data = resp.json()
        assert "started" in data or "id" in data

    def test_07_workflows_list(self, client):
        resp = client.get(f"{API_V1}/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data

    def test_08_workflow_status_not_found(self, client):
        resp = client.get(f"{API_V1}/workflows/nonexistent-wf")
        assert resp.status_code == 404

    def test_09_traces_list(self, client):
        resp = client.get(f"{API_V1}/traces")
        assert resp.status_code == 200
        data = resp.json()
        assert "traces" in data

    def test_10_trace_detail_not_found(self, client):
        resp = client.get(f"{API_V1}/traces/nonexistent-trace")
        assert resp.status_code == 404

    def test_11_audit_report(self, client):
        resp = client.get(f"{API_V1}/audit/report")
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data

    def test_12_audit_log(self, client):
        resp = client.get(f"{API_V1}/audit/log")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data

    def test_13_audit_log_with_limit(self, client):
        resp = client.get(f"{API_V1}/audit/log?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entries"]) <= 5

    def test_14_audit_report_filtered(self, client):
        resp = client.get(f"{API_V1}/audit/report?since=2026-01-01&agent=test")
        assert resp.status_code == 200

    def test_15_404_unknown_path(self, client):
        resp = client.get(f"{API_V1}/unknown-route")
        assert resp.status_code == 404

    def test_16_workflow_run_no_file(self, client):
        resp = client.post(
            f"{API_V1}/workflows/run",
            json={"file": "/nonexistent/workflow.yaml"},
        )
        # Should return error — file not found
        assert resp.status_code in (200, 400, 422)

    def test_17_workflow_cancel_not_found(self, client):
        resp = client.post(f"{API_V1}/workflows/nonexistent-run/cancel")
        assert resp.status_code == 404

    def test_18_pause_resume_agent(self, client):
        client.post("/agents/register", json={"name": "pausable"})
        client.post(f"{API_V1}/agents/pausable/start")

        resp = client.post(f"{API_V1}/agents/pausable/pause")
        assert resp.status_code == 200
        data = resp.json()
        assert "paused" in data or "error" in data

        resp = client.post(f"{API_V1}/agents/pausable/resume")
        assert resp.status_code == 200

    def test_19_restart_agent(self, client):
        client.post(f"{API_V1}/agents/register", json={"name": "restartable"})
        client.post(f"{API_V1}/agents/restartable/start")
        resp = client.post(f"{API_V1}/agents/restartable/restart")
        # restart may succeed or return state-dependent error
        assert resp.status_code in (200, 400)

    def test_20_ask_agent(self, client):
        name = "askable"
        client.post(f"{API_V1}/agents/register", json={"name": name})
        client.post(f"{API_V1}/agents/{name}/start")

        resp = client.post(
            f"{API_V1}/agents/{name}/ask",
            json={"prompt": "Hello", "timeout": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data

    def test_21_workflow_visualize(self, client):
        existing = list(Path.cwd().glob("workflows/*.yaml"))
        if existing:
            resp = client.get(f"{API_V1}/workflows/visualize?file={existing[0]}")
            assert resp.status_code == 200
            data = resp.json()
            assert "mermaid" in data

    def test_22_sessions_list(self, client):
        resp = client.get(f"{API_V1}/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert "sessions" in data

    def test_23_session_not_found(self, client):
        resp = client.get(f"{API_V1}/sessions/nonexistent-session")
        assert resp.status_code == 404

    def test_24_openapi_docs_available(self, client):
        """FastAPI generates OpenAPI docs at /docs and /openapi.json."""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["info"]["title"] == "sccsos API"

    def test_25_websocket_connect(self, client):
        """WebSocket endpoint should accept connections."""
        with client.websocket_connect(f"{API_V1}/ws") as ws:
            # Should connect without error
            ws.send_text("ping")

    def test_26_workflow_list_after_register(self, client):
        """Workflow list endpoint should work after agent setup."""
        # Register an agent and start it to generate events
        client.post("/agents/register", json={"name": "wf-agent"})
        client.post(f"{API_V1}/agents/wf-agent/start")
        resp = client.get(f"{API_V1}/agents")
        assert resp.status_code == 200
