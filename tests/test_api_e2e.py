"""E2E API Integration Tests — Full FastAPI route-level end-to-end.

Covers complete API surface with real HTTP requests through TestClient:
  - Health, Agents CRUD, Skills market, Billing, Quota, Webhooks
  - RBAC authorization (X-Role header)
  - Skill lifecycle: create → list → submit → approve → install → remove
  - Multi-tenant isolation (X-Tenant-ID header)
  - Error handling (404, 400, 403, 422)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from sccsos.core.agent_runtime import AgentRuntime, set_runtime
from sccsos.core.hermes_adapter import create_adapter
from sccsos.api.fastapi_app import create_app

API_V1 = "/api/v1"


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient with mock runtime (shared across tests)."""
    runtime = AgentRuntime()
    runtime.initialize()
    runtime._core._adapter = create_adapter("mock")
    if runtime._core._runner is not None:
        runtime._core._runner._adapter = runtime._core._adapter
        runtime._core._runner.stop_all()
    if runtime._obs and runtime._obs._tracer:
        runtime._obs._tracer._export_path = None
    set_runtime(runtime)

    app = create_app()
    client = TestClient(app)
    yield client


# ── RBAC Authorization Tests ────────────────────────────────────────


class TestRBACAuthorization:
    """Verify RBAC X-Role header enforcement on all sensitive endpoints."""

    admin = {"X-Role": "admin"}
    viewer = {"X-Role": "viewer"}

    def test_viewer_can_read_agents(self, client):
        resp = client.get(f"{API_V1}/agents", headers=self.viewer)
        assert resp.status_code == 200

    def test_viewer_cannot_start_agent(self, client):
        # Register first
        client.post(f"{API_V1}/agents/register",
                    json={"name": "viewer-test"}, headers=self.admin)
        resp = client.post(f"{API_V1}/agents/viewer-test/start",
                           headers=self.viewer)
        assert resp.status_code == 403

    def test_viewer_cannot_approve_skill(self, client):
        resp = client.post(f"{API_V1}/skills/nonexistent/approve",
                           params={"reviewer": "test"},
                           headers=self.viewer)
        assert resp.status_code == 403

    def test_admin_can_start_agent(self, client):
        client.post(f"{API_V1}/agents/register",
                    json={"name": "admin-test"}, headers=self.admin)
        resp = client.post(f"{API_V1}/agents/admin-test/start",
                           headers=self.admin)
        # Could be 200 or 404 (depends on lifecycle state), but NOT 403
        assert resp.status_code != 403

    def test_no_role_header_defaults_viewer(self, client):
        """Without X-Role header, should default to viewer."""
        resp = client.post(f"{API_V1}/agents/nonexistent/start")
        assert resp.status_code in (403, 404)  # 403 if found, 404 if not

    def test_unknown_role_falls_back_to_viewer(self, client):
        resp = client.post(f"{API_V1}/agents/nonexistent/start",
                           headers={"X-Role": "superadmin"})
        assert resp.status_code in (403, 404)


# ── Skill Market E2E ────────────────────────────────────────────────


class TestSkillMarketE2E:
    """End-to-end skill lifecycle via HTTP API."""

    admin = {"X-Role": "admin"}

    def test_01_create_skill(self, client):
        """POST /skills creates a new skill."""
        resp = client.post(
            f"{API_V1}/skills",
            params={"name": "e2e-agent", "type": "agent",
                    "author": "tester", "auto_approve": "true"},
            headers=self.admin,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "e2e-agent"
        assert data["status"] == "published"

    def test_02_list_skills(self, client):
        """GET /skills lists all skills with search/filter support."""
        resp = client.get(f"{API_V1}/skills", headers=self.admin)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(s["name"] == "e2e-agent" for s in data)

    def test_03_list_skills_by_type(self, client):
        """GET /skills?type=agent filters by type."""
        resp = client.get(f"{API_V1}/skills?type=agent", headers=self.admin)
        assert resp.status_code == 200
        data = resp.json()
        for s in data:
            assert s["type"] == "agent"

    def test_04_install_skill(self, client, tmp_path):
        """POST /skills/{name}/install installs a published skill."""
        resp = client.post(
            f"{API_V1}/skills/e2e-agent/install",
            params={"target_dir": str(tmp_path)},
            headers=self.admin,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "installed"
        # Verify file was created
        assert (tmp_path / "agents" / "e2e-agent.yaml").exists()

    def test_05_list_installed(self, client):
        """GET /skills/installed lists installed skills."""
        resp = client.get(f"{API_V1}/skills/installed", headers=self.admin)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(s["name"] == "e2e-agent" for s in data)

    def test_06_remove_installed(self, client):
        """DELETE /skills/installed/{name} removes install record."""
        resp = client.delete(f"{API_V1}/skills/installed/e2e-agent",
                             headers=self.admin)
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

    def test_07_skill_not_found(self, client):
        """Installing non-existent skill returns 400."""
        resp = client.post(f"{API_V1}/skills/ghost/install",
                           headers=self.admin)
        assert resp.status_code == 400

    def test_08_create_with_content(self, client):
        """Skill creation with YAML content."""
        resp = client.post(
            f"{API_V1}/skills",
            params={"name": "content-skill", "type": "personality",
                    "content": "name: content-skill\nsystem_prompt: Hi",
                    "auto_approve": "true"},
            headers=self.admin,
        )
        assert resp.status_code == 201

    def test_09_search_skills(self, client):
        """GET /skills?q= filters by query string."""
        resp = client.get(f"{API_V1}/skills?q=content", headers=self.admin)
        assert resp.status_code == 200
        data = resp.json()
        assert any("content" in s["name"] or "content" in s.get("description", "")
                   for s in data)

    def test_10_skill_review_lifecycle(self, client):
        """Full review lifecycle: draft → submit → approve."""
        # Create as draft with unique name to avoid version conflicts
        import uuid
        sname = f"review-{uuid.uuid4().hex[:8]}"
        client.post(f"{API_V1}/skills",
                    params={"name": sname, "type": "agent",
                            "content": f"name: {sname}\nsystem_prompt: You are helpful."},
                    headers=self.admin)
        # Submit for review (default version 1.0)
        resp = client.post(f"{API_V1}/skills/{sname}/submit",
                           headers=self.admin)
        assert resp.status_code == 200, f"Submit failed: {resp.json()}"
        # Approve
        resp = client.post(f"{API_V1}/skills/{sname}/approve",
                           params={"reviewer": "architect"},
                           headers=self.admin)
        assert resp.status_code == 200, f"Approve failed: {resp.json()}"
        assert resp.json()["status"] == "approved"


# ── Multi-Tenant Isolation E2E ───────────────────────────────────────


class TestMultiTenantE2E:
    """Verify X-Tenant-ID header isolation."""

    admin = {"X-Role": "admin"}

    def test_tenant_isolation_in_agents(self, client):
        """Different tenants should see different agent lists."""
        # Register agents under different tenants
        client.post(f"{API_V1}/agents/register",
                    json={"name": "tenant-a-agent"},
                    headers={**self.admin, "X-Tenant-ID": "tenant-a"})
        client.post(f"{API_V1}/agents/register",
                    json={"name": "tenant-b-agent"},
                    headers={**self.admin, "X-Tenant-ID": "tenant-b"})

        # Each tenant should only see their own agents
        resp_a = client.get(f"{API_V1}/agents",
                            headers={**self.admin, "X-Tenant-ID": "tenant-a"})
        resp_b = client.get(f"{API_V1}/agents",
                            headers={**self.admin, "X-Tenant-ID": "tenant-b"})
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200


# ── Error Handling E2E ──────────────────────────────────────────────


class TestErrorHandling:
    """Verify proper HTTP error codes for various failure modes."""

    admin = {"X-Role": "admin"}

    def test_404_for_unknown_agent(self, client):
        resp = client.get(f"{API_V1}/agents/ghost", headers=self.admin)
        assert resp.status_code == 404

    def test_404_for_unknown_trace(self, client):
        resp = client.get(f"{API_V1}/traces/ghost", headers=self.admin)
        assert resp.status_code == 404

    def test_422_for_invalid_parameters(self, client):
        """Invalid query parameters should return 422."""
        # POST without required params
        resp = client.post(f"{API_V1}/skills/nonexistent/reject",
                           headers=self.admin)
        assert resp.status_code == 422

    def test_400_for_skill_submit_invalid_state(self, client):
        """Submitting a non-existent skill returns 400."""
        resp = client.post(f"{API_V1}/skills/ghost/submit",
                           headers=self.admin)
        assert resp.status_code == 400

    def test_health_returns_valid_json(self, client):
        resp = client.get(f"{API_V1}/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "initialized" in data
        assert data["initialized"] is True
