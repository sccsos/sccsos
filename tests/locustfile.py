"""SCCS OS — Locust performance benchmark.

Usage:
    # Install locust
    pip install locust

    # Start SCCS OS API server in background
    python -m sccsos.api.fastapi_app --port 8765 &

    # Run locust (headless with HTML report)
    locust -f locustfile.py --headless -u 10 -r 2 --run-time 60s \
        --host http://localhost:8765 --html benchmark-report.html

    # Or interactive web UI
    locust -f locustfile.py --host http://localhost:8765
"""

import random
from locust import HttpUser, task, between


class SCCSOSUser(HttpUser):
    """Simulates an API consumer with typical workload patterns."""

    # Wait 1-3 seconds between tasks (simulate human/agent thinking time)
    wait_time = between(1, 3)

    def on_start(self):
        """Each simulated user gets a unique tenant and registers an agent."""
        self.tenant_id = f"bench-{random.randint(10000, 99999)}"
        self.headers = {
            "X-Tenant-ID": self.tenant_id,
            "X-Role": "admin",
            "Content-Type": "application/json",
        }
        self.agent_name = f"bench-agent-{random.randint(1000, 9999)}"

        # Register an agent
        with self.client.post(
            "/api/v1/agents/register",
            json={"name": self.agent_name, "description": "Benchmark agent"},
            headers=self.headers,
            catch_response=True,
        ) as resp:
            if resp.status_code == 201:
                resp.success()
            else:
                resp.failure(f"Agent registration failed: {resp.status_code}")

    # ── Read-heavy tasks (weight: 60%) ────────────────────────────

    @task(3)
    def health_check(self):
        """GET /api/v1/health — most frequent call."""
        with self.client.get(
            "/api/v1/health",
            headers=self.headers,
            name="health",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Health check failed: {resp.status_code}")

    @task(2)
    def list_agents(self):
        """GET /api/v1/agents."""
        with self.client.get(
            "/api/v1/agents",
            headers=self.headers,
            name="agents_list",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"List agents failed: {resp.status_code}")

    @task(2)
    def list_skills(self):
        """GET /api/v1/skills."""
        with self.client.get(
            "/api/v1/skills",
            headers=self.headers,
            name="skills_list",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"List skills failed: {resp.status_code}")

    @task(1)
    def billing_summary(self):
        """GET /api/v1/billing/summary."""
        with self.client.get(
            "/api/v1/billing/summary",
            headers=self.headers,
            name="billing_summary",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Billing summary failed: {resp.status_code}")

    @task(1)
    def quota_status(self):
        """GET /api/v1/quotas/{tenant}."""
        with self.client.get(
            f"/api/v1/quotas/{self.tenant_id}",
            headers=self.headers,
            name="quota_status",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Quota check failed: {resp.status_code}")

    @task(1)
    def list_traces(self):
        """GET /api/v1/traces."""
        with self.client.get(
            "/api/v1/traces",
            headers=self.headers,
            name="traces_list",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"List traces failed: {resp.status_code}")

    # ── Write-heavy tasks (weight: 40%) ──────────────────────────

    @task(1)
    def register_agent(self):
        """POST /api/v1/agents/register."""
        name = f"tmp-{random.randint(10000, 99999)}"
        with self.client.post(
            "/api/v1/agents/register",
            json={"name": name, "description": "Temp agent"},
            headers=self.headers,
            name="agent_register",
            catch_response=True,
        ) as resp:
            if resp.status_code == 201:
                resp.success()
            else:
                resp.failure(f"Register failed: {resp.status_code}")

    @task(1)
    def create_skill(self):
        """POST /api/v1/skills with auto_approve."""
        name = f"bench-skill-{random.randint(10000, 99999)}"
        with self.client.post(
            "/api/v1/skills",
            params={
                "name": name,
                "type": "personality",
                "content": f"name: {name}\nsystem_prompt: Benchmark skill.",
                "auto_approve": "true",
            },
            headers=self.headers,
            name="skill_create",
            catch_response=True,
        ) as resp:
            if resp.status_code == 201:
                resp.success()
            else:
                resp.failure(f"Create skill failed: {resp.status_code}")

    @task(1)
    def install_skill(self):
        """POST /api/v1/skills/{name}/install."""
        import tempfile
        name = f"install-{random.randint(10000, 99999)}"
        # Create a skill first
        self.client.post(
            "/api/v1/skills",
            params={"name": name, "type": "personality",
                    "content": f"name: {name}", "auto_approve": "true"},
            headers=self.headers,
        )
        # Then install
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.client.post(
                f"/api/v1/skills/{name}/install",
                params={"target_dir": tmpdir},
                headers=self.headers,
                name="skill_install",
                catch_response=True,
            ) as resp:
                if resp.status_code == 200:
                    resp.success()
                else:
                    resp.failure(f"Install failed: {resp.status_code}")

    @task(1)
    def update_quota(self):
        """POST /api/v1/quotas/{tenant}."""
        with self.client.post(
            f"/api/v1/quotas/{self.tenant_id}",
            json={"max_agents": 10, "max_llm_calls": 1000},
            headers=self.headers,
            name="quota_update",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Quota update failed: {resp.status_code}")

    def on_stop(self):
        """Cleanup: remove test agent."""
        self.client.post(
            f"/api/v1/agents/{self.agent_name}/stop",
            headers=self.headers,
            name="agent_stop",
        )
