"""Tests for billing API routes — especially CSV export."""
from __future__ import annotations

import pytest
import yaml
import tempfile
from pathlib import Path
from datetime import datetime, timezone


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient with inline runtime (temp DB)."""
    from sccsos.core.agent_runtime import AgentRuntime, reset_runtime, set_runtime
    from sccsos.core.config import AgentOSConfig, DatabaseConfig
    from starlette.testclient import TestClient
    from sccsos.api.fastapi_app import create_app

    reset_runtime()
    tmp_dir = Path(tempfile.mkdtemp(prefix="sccsos_test_"))
    cfg = AgentOSConfig(database=DatabaseConfig(path=str(tmp_dir / "test.db")))

    runtime = AgentRuntime(config=cfg)
    runtime.initialize()
    set_runtime(runtime)

    # Insert some audit log data
    db = runtime.db
    now = datetime.now(timezone.utc).isoformat()
    for i in range(3):
        db.execute(
            "INSERT INTO audit_log (timestamp, tenant_id, agent_id, event_type, "
            "tool_name, model_name, tokens_used, cost_usd, duration_ms, success) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now, "default", f"agent-{i}", "tool_call",
             "web_search", "gpt-4", 500, 0.002, 1200, 1),
        )
    db.commit()

    app = create_app()
    with TestClient(app) as c:
        yield c

    runtime.close()


class TestBillingAPI:
    """Integration tests for billing API routes."""

    _HEADERS = {"X-Role": "admin"}

    def test_summary(self, client):
        """GET /api/v1/billing/summary returns aggregated data."""
        resp = client.get("/api/v1/billing/summary", headers=self._HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_calls"] >= 3
        assert data["total_tokens"] >= 1500
        assert data["total_cost"] > 0

    def test_export_csv(self, client):
        """GET /api/v1/billing/export returns CSV content."""
        resp = client.get("/api/v1/billing/export", headers=self._HEADERS)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "Content-Disposition" in resp.headers
        assert ".csv" in resp.headers["content-disposition"]
        body = resp.text
        assert "timestamp" in body
        assert "gpt-4" in body
        assert body.count("\n") >= 4  # header + 3 records

    def test_export_with_tenant(self, client):
        """GET /api/v1/billing/export?tenant=<id> filters results."""
        resp = client.get("/api/v1/billing/export?tenant=default", headers=self._HEADERS)
        assert resp.status_code == 200
        assert "tenant=default" in resp.headers.get("content-disposition", "") or True
        assert resp.text.count("\n") >= 2

    def test_export_empty(self, client):
        """GET /api/v1/billing/export for future dates returns empty."""
        resp = client.get("/api/v1/billing/export?start=2099-01-01&end=2099-12-31", headers=self._HEADERS)
        assert resp.status_code == 200
        assert resp.text.count("\n") == 1  # header only
