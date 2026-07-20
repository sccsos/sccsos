"""Tests for QuotaManager — per-tenant resource quota enforcement."""

from __future__ import annotations

import os
import tempfile

import pytest

from sccsos.core.db import Database
from sccsos.core.quota_manager import QuotaManager, QuotaLimit, QuotaUsage
from sccsos.security.base import PolicyResult


@pytest.fixture
def db():
    """Temporary SQLite database."""
    tmp = tempfile.mktemp(suffix=".db")
    database = Database(db_path=tmp)
    database.initialize()
    yield database
    database.close()
    os.unlink(tmp)


@pytest.fixture
def mgr(db):
    """QuotaManager with fresh DB."""
    return QuotaManager(db)


@pytest.fixture
def seeded_db(db):
    """DB with some audit_log entries for usage tracking."""
    # Add some agents
    for i in range(3):
        db.execute(
            "INSERT INTO agents (id, tenant_id, name, spec, status) "
            "VALUES (?, ?, ?, '{}', ?)",
            (f"agent-{i}", "tenant-1", f"Agent {i}", "running"),
        )
    # Add audit entries for today
    import datetime
    today = datetime.datetime.now().isoformat()
    db.execute(
        "INSERT INTO audit_log (tenant_id, agent_id, event_type, tokens_used, "
        "cost_usd, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        ("tenant-1", "agent-0", "llm_call", 5000, 0.15, today),
    )
    db.execute(
        "INSERT INTO audit_log (tenant_id, agent_id, event_type, tokens_used, "
        "cost_usd, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        ("tenant-1", "agent-1", "llm_call", 3000, 0.09, today),
    )
    db.execute(
        "INSERT INTO memory_store (tenant_id, agent_name, key, value) "
        "VALUES (?, ?, ?, ?)",
        ("tenant-1", "agent-0", "k1", "v1"),
    )
    db.execute(
        "INSERT INTO memory_store (tenant_id, agent_name, key, value) "
        "VALUES (?, ?, ?, ?)",
        ("tenant-1", "agent-0", "k2", "v2"),
    )
    db.commit()
    return db


@pytest.fixture
def mgr_seeded(seeded_db):
    """Manager with seeded data."""
    return QuotaManager(seeded_db)


class TestQuotaManagerSetGet:
    """Quota set/get/reset operations."""

    def test_get_default_quota(self, mgr):
        """get_quota returns defaults when not set."""
        q = mgr.get_quota("default")
        assert q.tenant_id == "default"
        assert q.max_agents == 10
        assert q.max_tokens_per_day == 500000
        assert q.max_cost_per_day == 10.0
        assert q.max_cost_total == 100.0

    def test_custom_tenant_defaults(self, mgr):
        """Custom tenant gets defaults too."""
        q = mgr.get_quota("custom-tenant")
        assert q.tenant_id == "custom-tenant"
        assert q.max_agents == 10

    def test_set_quota(self, mgr):
        """set_quota persists values."""
        mgr.set_quota("prod", max_agents=5, max_tokens_per_day=100000,
                      max_cost_per_day=50.0, max_cost_total=500.0,
                      max_memory_entries=5000, max_storage_mb=2048)

        q = mgr.get_quota("prod")
        assert q.max_agents == 5
        assert q.max_tokens_per_day == 100000
        assert q.max_cost_per_day == 50.0
        assert q.max_cost_total == 500.0
        assert q.max_memory_entries == 5000
        assert q.max_storage_mb == 2048

    def test_update_quota(self, mgr):
        """Updating quota overwrites all fields (full replacement)."""
        mgr.set_quota("test", max_agents=3, max_tokens_per_day=50000)
        mgr.set_quota("test", max_tokens_per_day=200000)  # full overwrite

        q = mgr.get_quota("test")
        assert q.max_agents == 10  # Reset to default (full overwrite)
        assert q.max_tokens_per_day == 200000  # Explicitly set

    def test_list_quotas(self, mgr):
        """list_quotas returns configured quotas."""
        mgr.set_quota("a", max_agents=2)
        mgr.set_quota("b", max_agents=5)

        quotas = mgr.list_quotas()
        assert len(quotas) == 2
        assert quotas[0].tenant_id in ("a", "b")

    def test_reset_quota(self, mgr):
        """reset_quota removes custom config."""
        mgr.set_quota("test", max_agents=3)
        mgr.reset_quota("test")

        q = mgr.get_quota("test")
        assert q.max_agents == 10  # Back to default


class TestQuotaUsage:
    """Usage tracking queries."""

    def test_usage_agent_count(self, mgr_seeded):
        """get_usage counts running agents."""
        u = mgr_seeded.get_usage("tenant-1")
        assert u.agent_count >= 3

    def test_usage_tokens(self, mgr_seeded):
        """get_usage sums today's tokens."""
        u = mgr_seeded.get_usage("tenant-1")
        assert u.tokens_today == 8000  # 5000 + 3000

    def test_usage_cost(self, mgr_seeded):
        """get_usage sums today's costs."""
        u = mgr_seeded.get_usage("tenant-1")
        assert u.cost_today == 0.24  # 0.15 + 0.09

    def test_usage_memory(self, mgr_seeded):
        """get_usage counts memory entries."""
        u = mgr_seeded.get_usage("tenant-1")
        assert u.memory_entries == 2

    def test_empty_tenant(self, mgr):
        """get_usage returns zeros for unused tenant."""
        u = mgr.get_usage("empty-tenant")
        assert u.agent_count == 0
        assert u.tokens_today == 0
        assert u.cost_today == 0.0
        assert u.memory_entries == 0


class TestQuotaChecks:
    """Quota enforcement checks."""

    def test_agent_quota_ok(self, mgr):
        """check_agent_quota passes within limit."""
        result = mgr.check_agent_quota("default")
        assert result.allowed

    def test_agent_quota_exceeded(self, mgr_seeded, seeded_db):
        """check_agent_quota fails when over limit."""
        mgr_seeded.set_quota("tenant-1", max_agents=2)
        result = mgr_seeded.check_agent_quota("tenant-1")
        assert not result.allowed
        assert "quota" in result.reason.lower()

    def test_token_quota_ok(self, mgr_seeded):
        """check_token_quota passes within limit."""
        result = mgr_seeded.check_token_quota("tenant-1", estimated_tokens=1000)
        assert result.allowed

    def test_token_quota_exceeded(self, mgr_seeded):
        """check_token_quota fails when over limit."""
        mgr_seeded.set_quota("tenant-1", max_tokens_per_day=5000)
        result = mgr_seeded.check_token_quota("tenant-1", estimated_tokens=1000)
        # Actual: 8000 used + 1000 estimated = 9000 > 5000
        assert not result.allowed

    def test_cost_quota_ok(self, mgr_seeded):
        """check_cost_quota passes within limit."""
        result = mgr_seeded.check_cost_quota("tenant-1", estimated_cost=0.01)
        assert result.allowed

    def test_cost_quota_daily_exceeded(self, mgr_seeded):
        """check_cost_quota fails on daily limit."""
        mgr_seeded.set_quota("tenant-1", max_cost_per_day=0.20)
        result = mgr_seeded.check_cost_quota("tenant-1", estimated_cost=0.01)
        # Actual: 0.24 + 0.01 = 0.25 > 0.20
        assert not result.allowed
        assert "daily" in result.reason.lower()

    def test_cost_quota_total_exceeded(self, mgr_seeded):
        """check_cost_quota fails on total limit."""
        mgr_seeded.set_quota("tenant-1", max_cost_total=0.20, max_cost_per_day=100)
        result = mgr_seeded.check_cost_quota("tenant-1", estimated_cost=0.01)
        # Total: 0.24 + 0.01 = 0.25 > 0.20
        assert not result.allowed
        assert "total" in result.reason.lower()

    def test_check_all_passes(self, mgr):
        """check_all passes when within all limits."""
        result = mgr.check_all("default")
        assert result.allowed

    def test_check_all_agent_fails_first(self, mgr_seeded):
        """check_all returns agent quota failure first."""
        mgr_seeded.set_quota("tenant-1", max_agents=1)
        result = mgr_seeded.check_all("tenant-1")
        assert not result.allowed
        assert "agent" in result.reason.lower()
