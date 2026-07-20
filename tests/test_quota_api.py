"""Tests for quota API routes — especially quota update."""
from __future__ import annotations

import pytest
import tempfile
from pathlib import Path


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

    app = create_app()
    with TestClient(app) as c:
        yield c

    runtime.close()


class TestQuotaAPI:
    """Integration tests for quota API routes."""

    def test_get_defaults(self, client):
        """GET /api/v1/quotas/default returns default limits."""
        resp = client.get("/api/v1/quotas/default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == "default"
        assert data["max_agents"] == 10
        assert data["max_tokens_per_day"] == 500000
        assert data["max_cost_per_day"] > 0

    def test_update_quota(self, client):
        """POST /api/v1/quotas/default updates limits."""
        resp = client.post(
            "/api/v1/quotas/default",
            json={"max_agents": 20, "max_tokens_per_day": 1000000},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"

        # Verify persisted
        resp2 = client.get("/api/v1/quotas/default")
        assert resp2.json()["max_agents"] == 20
        assert resp2.json()["max_tokens_per_day"] == 1000000

    def test_update_partial(self, client):
        """POST with partial fields only updates those fields."""
        resp = client.post(
            "/api/v1/quotas/default",
            json={"max_cost_per_day": 50.0},
        )
        assert resp.status_code == 200
        # Previous values preserved
        data = client.get("/api/v1/quotas/default").json()
        assert data["max_agents"] == 20  # from previous test
        assert data["max_cost_per_day"] == 50.0
