"""Tests for webhook API routes."""
from __future__ import annotations

import os
import pytest
import tempfile
import yaml
from pathlib import Path


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient with temp DB + temp sccsos.yaml for webhook config."""
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

    # Create a temp sccsos.yaml with webhooks section
    config_path = tmp_dir / "sccsos.yaml"
    config_path.write_text(yaml.dump({
        "webhooks": {
            "enabled": True,
            "endpoints": [
                {"url": "https://hooks.example.com/test", "events": ["*"]},
            ],
        },
    }))
    os.environ["AGENTOS_CONFIG"] = str(config_path)

    # Force config reload so the route handlers see the new config
    from sccsos.core.config import reload_config
    reload_config()

    app = create_app()
    with TestClient(app) as c:
        yield c

    runtime.close()
    os.environ.pop("AGENTOS_CONFIG", None)


class TestWebhookAPI:
    """Integration tests for webhook API routes."""

    def test_list_endpoints(self, client):
        """GET /api/v1/webhooks lists configured endpoints."""
        resp = client.get("/api/v1/webhooks")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "endpoints" in data
        assert isinstance(data["endpoints"], list)
        assert len(data["endpoints"]) >= 1

    def test_list_requires_no_auth(self, client):
        """GET webhooks works without X-Role header (defaults to viewer)."""
        resp = client.get("/api/v1/webhooks")
        assert resp.status_code == 200

    def test_toggle_enable(self, client):
        """POST /api/v1/webhooks/toggle enables/disables."""
        resp = client.post(
            "/api/v1/webhooks/toggle?enabled=False",
            headers={"X-Role": "admin"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "updated"
        assert data["enabled"] is False

    def test_toggle_enable_back(self, client):
        """Toggle back to enabled."""
        resp = client.post(
            "/api/v1/webhooks/toggle?enabled=True",
            headers={"X-Role": "admin"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True

    def test_toggle_requires_write_permission(self, client):
        """Toggle without admin role returns 403."""
        resp = client.post(
            "/api/v1/webhooks/toggle?enabled=False",
            headers={"X-Role": "viewer"},
        )
        assert resp.status_code == 403

    def test_add_webhook(self, client):
        """POST /api/v1/webhooks adds a new endpoint."""
        resp = client.post(
            "/api/v1/webhooks",
            json={"url": "https://hooks.example.com/new", "events": ["workflow.completed"]},
            headers={"X-Role": "admin"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "added"

    def test_add_duplicate_webhook(self, client):
        """Adding a duplicate URL returns 400."""
        resp = client.post(
            "/api/v1/webhooks",
            json={"url": "https://hooks.example.com/new", "events": ["*"]},
            headers={"X-Role": "admin"},
        )
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    def test_add_webhook_requires_write_permission(self, client):
        """Add without write permission returns 403."""
        resp = client.post(
            "/api/v1/webhooks",
            json={"url": "https://hooks.example.com/no-perm"},
            headers={"X-Role": "viewer"},
        )
        assert resp.status_code == 403

    def test_remove_webhook(self, client):
        """DELETE /api/v1/webhooks removes an endpoint."""
        resp = client.delete(
            "/api/v1/webhooks?url=https://hooks.example.com/test",
            headers={"X-Role": "admin"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "removed"

    def test_remove_nonexistent_webhook(self, client):
        """Removing a non-existent URL returns 404."""
        resp = client.delete(
            "/api/v1/webhooks?url=https://hooks.example.com/nonexistent",
            headers={"X-Role": "admin"},
        )
        assert resp.status_code == 404

    def test_remove_webhook_requires_write_permission(self, client):
        """Remove without write permission returns 403."""
        resp = client.delete(
            "/api/v1/webhooks?url=https://hooks.example.com/test",
            headers={"X-Role": "viewer"},
        )
        assert resp.status_code == 403

    def test_full_lifecycle(self, client):
        """Full add/list/remove lifecycle."""
        # Add
        resp = client.post(
            "/api/v1/webhooks",
            json={"url": "https://hooks.example.com/lifecycle", "events": ["*"]},
            headers={"X-Role": "admin"},
        )
        assert resp.status_code == 200

        # List
        resp = client.get("/api/v1/webhooks")
        assert resp.status_code == 200
        urls = [ep["url"] for ep in resp.json()["endpoints"]]
        assert "https://hooks.example.com/lifecycle" in urls

        # Remove
        resp = client.delete(
            "/api/v1/webhooks?url=https://hooks.example.com/lifecycle",
            headers={"X-Role": "admin"},
        )
        assert resp.status_code == 200

        # Verify removed
        resp = client.get("/api/v1/webhooks")
        urls = [ep["url"] for ep in resp.json()["endpoints"]]
        assert "https://hooks.example.com/lifecycle" not in urls
