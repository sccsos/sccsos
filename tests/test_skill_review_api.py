"""Tests for the skill review API routes (FastAPI)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient with mock runtime and populated skill market.

    Uses a unique temp database to avoid SQLite locking from other
    module-scoped fixtures sharing the default ``./data/sccsos.db``.
    """
    from sccsos.core.agent_runtime import AgentRuntime, reset_runtime, set_runtime
    from sccsos.core.hermes_adapter import create_adapter
    from sccsos.core.config import AgentOSConfig, DatabaseConfig
    from starlette.testclient import TestClient
    from sccsos.api.fastapi_app import create_app

    reset_runtime()

    # Temp DB file to avoid locking with other module-scoped fixtures
    tmp_dir = Path(tempfile.mkdtemp(prefix="sccsos_test_"))
    db_path = str(tmp_dir / "test.db")
    cfg = AgentOSConfig(database=DatabaseConfig(path=db_path))

    runtime = AgentRuntime(config=cfg)
    runtime.initialize()
    set_runtime(runtime)  # inject into global registry for create_app()

    runtime._core._adapter = create_adapter("mock")
    if runtime._core._runner is not None:
        runtime._core._runner._adapter = runtime._core._adapter
        runtime._core._runner.stop_all()
    if runtime._obs and runtime._obs._tracer:
        runtime._obs._tracer._export_path = None

    # Register skills in the market for testing
    db = runtime.db
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    valid_yaml = yaml.dump({
        "name": "test-agent",
        "system_prompt": "You are a test agent.",
        "model": "gpt-4",
    })
    db.execute(
        "INSERT INTO skill_market (name, version, type, description, author, "
        "filename, content, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("test-review-agent", "1.0", "personality",
         "A test agent for review", "tester",
         "test-review-agent.yaml", valid_yaml, "draft", now, now),
    )

    # Also add one already pending
    db.execute(
        "INSERT INTO skill_market (name, version, type, description, author, "
        "filename, content, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("pending-agent", "1.0", "personality",
         "Already pending review", "tester",
         "pending-agent.yaml", valid_yaml, "pending_review", now, now),
    )
    db.commit()

    app = create_app()
    with TestClient(app) as c:
        yield c

    runtime.close()


class TestSkillReviewAPI:
    """Integration tests for /api/v1/skills/reviews endpoints."""

    def test_list_reviews_empty_status(self, client):
        """GET /api/v1/skills/reviews?status=approved returns empty."""
        resp = client.get("/api/v1/skills/reviews?status=approved")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_list_reviews_draft(self, client):
        """GET /api/v1/skills/reviews?status=draft returns draft skills."""
        resp = client.get("/api/v1/skills/reviews?status=draft")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["status"] == "draft"

    def test_list_reviews_pending(self, client):
        """GET /api/v1/skills/reviews?status=pending_review."""
        resp = client.get("/api/v1/skills/reviews?status=pending_review")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["status"] == "pending_review"

    def test_list_reviews_all(self, client):
        """GET /api/v1/skills/reviews?status=all returns all."""
        resp = client.get("/api/v1/skills/reviews?status=all")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2

    def test_get_review_found(self, client):
        """GET /api/v1/skills/{name}/review returns review details."""
        resp = client.get("/api/v1/skills/test-review-agent/review")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test-review-agent"
        assert data["status"] == "draft"

    def test_get_review_not_found(self, client):
        """GET /api/v1/skills/{name}/review returns 404 for unknown."""
        resp = client.get("/api/v1/skills/nonexistent/review")
        assert resp.status_code == 404

    def test_submit_for_review(self, client):
        """POST /api/v1/skills/{name}/submit transitions to pending_review."""
        resp = client.post("/api/v1/skills/test-review-agent/submit")
        assert resp.status_code == 200
        assert resp.json()["status"] == "submitted"

        # Verify status changed
        resp2 = client.get("/api/v1/skills/test-review-agent/review")
        assert resp2.json()["status"] == "pending_review"

    def test_submit_already_pending(self, client):
        """POST submit on already-pending skill returns 400."""
        resp = client.post("/api/v1/skills/pending-agent/submit")
        assert resp.status_code == 400

    def test_approve_valid(self, client):
        """POST /api/v1/skills/{name}/approve with valid content."""
        # First submit
        client.post("/api/v1/skills/test-review-agent/submit")

        # Then approve
        resp = client.post(
            "/api/v1/skills/test-review-agent/approve",
            params={"reviewer": "architect"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
        assert resp.json()["reviewer"] == "architect"

    def test_approve_invalid(self, client):
        """POST approve on skill with invalid content returns 400."""
        from sccsos.core.agent_runtime import get_runtime
        rt = get_runtime()
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        rt.db.execute(
            "INSERT INTO skill_market (name, version, type, description, author, "
            "filename, content, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("invalid-skill", "1.0", "personality",
             "Broken skill", "tester",
             "invalid.yaml", "{invalid: yaml: broken", "draft", now, now),
        )
        rt.db.commit()

        client.post("/api/v1/skills/invalid-skill/submit")
        resp = client.post("/api/v1/skills/invalid-skill/approve",
                           params={"reviewer": "test"})
        assert resp.status_code == 400
        assert "validation" in resp.json()["detail"].lower()

    def test_reject(self, client):
        """POST /api/v1/skills/{name}/reject rejects with reason."""
        resp = client.post(
            "/api/v1/skills/pending-agent/reject",
            params={"reason": "Missing license field"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"
        assert resp.json()["reason"] == "Missing license field"

    def test_reject_no_reason(self, client):
        """POST reject without reason returns 422."""
        resp = client.post(
            "/api/v1/skills/pending-agent/reject",
        )
        assert resp.status_code == 422

    def test_reject_not_found(self, client):
        """POST reject on non-existent skill returns 400."""
        resp = client.post(
            "/api/v1/skills/nonexistent/reject",
            params={"reason": "No reason needed"},
        )
        assert resp.status_code == 400
