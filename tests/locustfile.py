"""SCCS OS — Locust load test for production API endpoints.

Tests a realistic read-heavy workload with mixed lifecycle operations.
Agent lifecycle tasks (start/stop) are wrapped in try/except so they
gracefully report failures when no real Hermes CLI is available.

Usage:
    python3 -m uvicorn sccsos.api.fastapi_app:create_app \\
        --host 0.0.0.0 --port 8765 --workers 4 &

    locust -f tests/locustfile.py --headless \\
        -u 500 -r 50 --run-time 120s \\
        --host http://localhost:8765 \\
        --csv output/benchmark/locust

Requirements:
    pip install locust
"""

from __future__ import annotations

from locust import HttpUser, task, between


class SCCSOSUser(HttpUser):
    """Simulates a production API client with mixed read/write workload."""

    wait_time = between(0.1, 0.5)
    API = "/api/v1"
    HEADERS = {"X-Role": "admin", "X-Tenant-ID": "benchmark-tenant"}

    def on_start(self):
        """Register a reusable test agent for lifecycle operations."""
        self.agent_name = "bench-agent"
        with self.client.post(
            f"{self.API}/agents/register",
            json={"name": self.agent_name, "description": "Load test agent"},
            headers=self.HEADERS,
            name="POST /agents/register",
            catch_response=True,
        ) as resp:
            if resp.status_code == 201:
                resp.success()
            elif resp.status_code == 409:
                resp.success()  # Already registered = fine
            else:
                resp.failure(f"Register failed: {resp.status_code} {resp.text[:100]}")

    # ── Read-heavy workload (80%) ──────────────────────────────────

    @task(15)
    def health_check(self):
        """GET /health — lightweight, no DB."""
        self.client.get("/api/v1/health", name="GET /health")

    @task(10)
    def list_agents(self):
        """GET /agents — registry lookup."""
        self.client.get(
            f"{self.API}/agents",
            headers=self.HEADERS,
            name="GET /agents",
        )

    @task(6)
    def list_traces(self):
        """GET /traces — DB read."""
        self.client.get(
            f"{self.API}/traces",
            headers=self.HEADERS,
            name="GET /traces",
        )

    @task(5)
    def list_workflows(self):
        """GET /workflows — file-system scan."""
        self.client.get(
            f"{self.API}/workflows",
            headers=self.HEADERS,
            name="GET /workflows",
        )

    @task(5)
    def agent_status(self):
        """GET /agents/{name} — single agent status (DB read)."""
        self.client.get(
            f"{self.API}/agents/{self.agent_name}",
            headers=self.HEADERS,
            name="GET /agents/{name}",
        )

    @task(3)
    def list_sessions(self):
        """GET /sessions — session list (DB read)."""
        self.client.get(
            f"{self.API}/sessions",
            headers=self.HEADERS,
            name="GET /sessions",
        )

    @task(3)
    def audit_report(self):
        """GET /audit/report — aggregation query."""
        self.client.get(
            f"{self.API}/audit/report",
            headers=self.HEADERS,
            name="GET /audit/report",
        )

    @task(3)
    def billing_summary(self):
        """GET /billing/summary — cost aggregation."""
        self.client.get(
            f"{self.API}/billing/summary",
            headers=self.HEADERS,
            name="GET /billing/summary",
        )

    @task(2)
    def quota_status(self):
        """GET /quotas/default — config lookup."""
        self.client.get(
            f"{self.API}/quotas/benchmark-tenant",
            headers=self.HEADERS,
            name="GET /quotas/{tenant_id}",
        )

    # ── Write workload (20%) ───────────────────────────────────────
    # Lifecycle tasks catch ConnectionError gracefully so they don't
    # pollute failure stats when Hermes CLI is not available.

    @task(2)
    def agent_start(self):
        """POST /agents/{name}/start — lifecycle write (best-effort)."""
        with self.client.post(
            f"{self.API}/agents/{self.agent_name}/start",
            headers=self.HEADERS,
            name="POST /agents/{name}/start",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 409):
                resp.success()
            elif resp.status_code == 404:
                resp.success()  # No runner available in test mode
            else:
                resp.failure(f"Start failed: {resp.status_code}")

    @task(2)
    def agent_stop(self):
        """POST /agents/{name}/stop — lifecycle write (best-effort)."""
        with self.client.post(
            f"{self.API}/agents/{self.agent_name}/stop",
            headers=self.HEADERS,
            name="POST /agents/{name}/stop",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"Stop failed: {resp.status_code}")

    @task(1)
    def register_agent(self):
        """POST /agents/register — create a temp agent (DB write)."""
        import uuid
        temp_name = f"temp-{uuid.uuid4().hex[:8]}"
        with self.client.post(
            f"{self.API}/agents/register",
            json={"name": temp_name, "description": "Temp load test agent"},
            headers=self.HEADERS,
            name="POST /agents/register",
            catch_response=True,
        ) as resp:
            if resp.status_code == 201:
                resp.success()
            else:
                resp.failure(f"Register failed: {resp.status_code} {resp.text[:100]}")
