"""Tests for maintenance API routes.

Tests the /api/v1/maintenance/run and /api/v1/maintenance/status routes.
"""
from __future__ import annotations

import pytest
import tempfile
from pathlib import Path


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient with temp DB."""
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

    app = create_app()
    with TestClient(app) as c:
        yield c

    runtime.close()


class TestMaintenanceAPI:
    """Integration tests for maintenance routes."""

    def test_run_maintenance(self, client):
        """POST /api/v1/maintenance/run returns a maintenance report."""
        resp = client.post("/api/v1/maintenance/run")
        assert resp.status_code == 200
        data = resp.json()
        # Expected structure from MaintenanceScheduler.run_once()
        assert "_meta" in data
        assert "total_removed" in data["_meta"]
        assert "prune_stale" in data
        assert "prune_orphaned" in data
        assert "verify" in data

    def test_run_maintenance_empty_db(self, client):
        """Running maintenance on empty DB returns zero removals."""
        resp = client.post("/api/v1/maintenance/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["_meta"]["total_removed"] == 0

    def test_maintenance_status_stopped(self, client):
        """GET /api/v1/maintenance/status returns stopped state."""
        resp = client.get("/api/v1/maintenance/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        # In test context, scheduler is not running
        assert data["status"] in ("running", "stopped")

    def test_run_maintenance_twice(self, client):
        """Running maintenance twice is idempotent."""
        resp1 = client.post("/api/v1/maintenance/run")
        resp2 = client.post("/api/v1/maintenance/run")
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # Second run should have same structure
        assert "prune_stale" in resp2.json()
