"""SCCS OS — Locust load test for production API endpoints.

Usage:
    python3 -m sccsos.api.fastapi_app --port 8765 &
    locust -f tests/locustfile.py --headless \\
        -u 500 -r 50 --run-time 60s \\
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
    _HEADERS = {"X-Role": "admin", "X-Tenant-ID": "benchmark-tenant"}

    def on_start(self):
        """Register a test agent for lifecycle operations."""
        self.agent_name = "bench-agent"
        self.client.post(
            f"{self.API}/agents/register",
            json={"name": self.agent_name, "description": "Load test agent"},
            headers=self._HEADERS,
            name="POST /agents/register",
        )

    @task(15)
    def health_check(self):
        """GET /health — lightweight, fast."""
        self.client.get("/api/v1/health", name="GET /health")

    @task(10)
    def list_agents(self):
        """GET /agents — read-only list."""
        self.client.get(f"{self.API}/agents", headers=self._HEADERS, name="GET /agents")

    @task(5)
    def list_workflows(self):
        """GET /workflows — read-only list."""
        self.client.get(f"{self.API}/workflows", headers=self._HEADERS, name="GET /workflows")

    @task(6)
    def list_traces(self):
        """GET /traces — read-only list."""
        self.client.get(f"{self.API}/traces", headers=self._HEADERS, name="GET /traces")

    @task(3)
    def list_sessions(self):
        """GET /sessions — read-only list."""
        self.client.get(f"{self.API}/sessions", headers=self._HEADERS, name="GET /sessions")

    @task(3)
    def audit_report(self):
        """GET /audit/report — aggregation query."""
        self.client.get(f"{self.API}/audit/report", headers=self._HEADERS, name="GET /audit/report")

    @task(3)
    def billing_summary(self):
        """GET /billing/summary — cost aggregation."""
        self.client.get(f"{self.API}/billing/summary", headers=self._HEADERS, name="GET /billing/summary")

    @task(2)
    def quota_defaults(self):
        """GET /quotas/default — config lookup."""
        self.client.get(f"{self.API}/quotas/default", headers=self._HEADERS, name="GET /quotas/default")

    @task(5)
    def agent_status(self):
        """GET /agents/{name} — single agent status."""
        self.client.get(
            f"{self.API}/agents/{self.agent_name}",
            headers=self._HEADERS,
            name="GET /agents/{name}",
        )

    @task(2)
    def agent_start(self):
        """POST /agents/{name}/start — lifecycle write."""
        self.client.post(
            f"{self.API}/agents/{self.agent_name}/start",
            headers=self._HEADERS,
            name="POST /agents/{name}/start",
        )

    @task(2)
    def agent_stop(self):
        """POST /agents/{name}/stop — lifecycle write."""
        self.client.post(
            f"{self.API}/agents/{self.agent_name}/stop",
            headers=self._HEADERS,
            name="POST /agents/{name}/stop",
        )
