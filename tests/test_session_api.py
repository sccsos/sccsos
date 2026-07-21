"""Tests for session API routes.

Tests /api/v1/sessions, /api/v1/sessions/{id}, /api/v1/sessions/{id}/messages,
and /api/v1/sessions/{id}/close.
"""
from __future__ import annotations

import pytest
import tempfile
from pathlib import Path


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient with temp DB and a session created."""
    from sccsos.core.agent_runtime import AgentRuntime, reset_runtime, set_runtime
    from sccsos.core.config import AgentOSConfig, DatabaseConfig
    from starlette.testclient import TestClient
    from sccsos.api.fastapi_app import create_app

    reset_runtime()
    tmp_dir = Path(tempfile.mkdtemp(prefix="sccsos_test_"))
    cfg = AgentOSConfig(database=DatabaseConfig(path=str(tmp_dir / "test.db")))

    runtime = AgentRuntime(config=cfg)
    runtime.initialize()

    # Create a session for testing
    session = runtime.session_manager.get_or_create("test-agent")
    runtime.session_manager.append_message(session.id, "user", "Hello")
    runtime.session_manager.append_message(session.id, "assistant", "Hi there!")

    set_runtime(runtime)

    app = create_app()
    with TestClient(app) as c:
        # Store the session_id for tests
        c._test_session_id = session.id
        yield c

    runtime.close()


class TestSessionAPI:
    """Integration tests for session routes."""

    def test_list_sessions(self, client):
        """GET /api/v1/sessions lists all sessions."""
        resp = client.get("/api/v1/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert "sessions" in data
        assert "count" in data
        assert data["count"] >= 1

    def test_list_sessions_filter_by_agent(self, client):
        """GET /api/v1/sessions?agent=test-agent filters correctly."""
        resp = client.get("/api/v1/sessions?agent=test-agent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        for s in data["sessions"]:
            assert s["agent_name"] == "test-agent"

    def test_list_sessions_filter_by_status(self, client):
        """GET /api/v1/sessions?status=active returns active only."""
        resp = client.get("/api/v1/sessions?status=active")
        assert resp.status_code == 200
        data = resp.json()
        for s in data["sessions"]:
            assert s["status"] == "active"

    def test_session_detail(self, client):
        """GET /api/v1/sessions/{id} returns session details."""
        session_id = client._test_session_id
        resp = client.get(f"/api/v1/sessions/{session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == session_id
        assert data["agent_name"] == "test-agent"
        assert "status" in data
        assert "created_at" in data

    def test_session_detail_not_found(self, client):
        """GET /api/v1/sessions/nonexistent returns 404."""
        resp = client.get("/api/v1/sessions/nonexistent")
        assert resp.status_code == 404

    def test_session_messages(self, client):
        """GET /api/v1/sessions/{id}/messages returns messages."""
        session_id = client._test_session_id
        resp = client.get(f"/api/v1/sessions/{session_id}/messages")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == session_id
        assert data["count"] >= 2
        roles = [m["role"] for m in data["messages"]]
        assert "user" in roles
        assert "assistant" in roles

    def test_session_messages_not_found(self, client):
        """Messages for nonexistent session returns empty."""
        resp = client.get("/api/v1/sessions/nonexistent/messages")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_close_session(self, client):
        """POST /api/v1/sessions/{id}/close closes the session."""
        session_id = client._test_session_id
        resp = client.post(
            f"/api/v1/sessions/{session_id}/close",
            headers={"X-Role": "admin"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["closed"] == session_id

    def test_close_already_closed_session(self, client):
        """Closing already closed session is idempotent."""
        session_id = client._test_session_id
        resp = client.post(
            f"/api/v1/sessions/{session_id}/close",
            headers={"X-Role": "admin"},
        )
        assert resp.status_code == 200
        assert resp.json()["closed"] == session_id

    def test_close_nonexistent_session(self, client):
        """Closing nonexistent session returns 404."""
        resp = client.post(
            "/api/v1/sessions/nonexistent/close",
            headers={"X-Role": "admin"},
        )
        assert resp.status_code == 404

    def test_list_sessions_with_tenant(self, client):
        """GET /api/v1/sessions?tenant_id=default works."""
        resp = client.get("/api/v1/sessions?tenant_id=default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
