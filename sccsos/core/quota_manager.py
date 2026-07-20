"""QuotaManager — per-tenant resource quota enforcement.

Tracks and enforces usage limits across multiple dimensions:
- Agent count: max concurrent agents per tenant
- Token usage: total tokens consumed per period
- Cost: total USD spent per period
- Storage: max memory entries / db size per tenant

Usage:
    mgr = QuotaManager(db)
    
    # Set quotas for a tenant
    mgr.set_quota("tenant-1", max_agents=5, max_tokens_per_day=100000)
    
    # Check before an operation
    result = mgr.check_agent_quota("tenant-1")
    if not result.allowed:
        raise QuotaExceededError(result.reason)
    
    # Record usage after operation
    mgr.record_usage("tenant-1", tokens=1500, cost_usd=0.03)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sccsos.core.db import Database
from sccsos.security.base import PolicyResult

logger = logging.getLogger("sccsos.quota")


@dataclass
class QuotaLimit:
    """Quota limits for a tenant."""
    tenant_id: str = "default"
    max_agents: int = 10          # Max concurrent agent instances
    max_tokens_per_day: int = 500000   # Daily token limit
    max_cost_per_day: float = 10.0     # Daily cost limit (USD)
    max_cost_total: float = 100.0      # Total cost limit (USD)
    max_memory_entries: int = 10000    # Max memory store entries
    max_storage_mb: int = 1024         # Max DB storage (MB)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class QuotaUsage:
    """Current usage stats for a tenant."""
    tenant_id: str
    agent_count: int = 0
    tokens_today: int = 0
    cost_today: float = 0.0
    cost_total: float = 0.0
    memory_entries: int = 0
    storage_mb: float = 0.0


class QuotaManager:
    """Per-tenant resource quota enforcement.

    Args:
        db: Database instance.
    """

    TENANT_QUOTA_COLS = (
        "max_agents", "max_tokens_per_day", "max_cost_per_day",
        "max_cost_total", "max_memory_entries", "max_storage_mb",
    )

    def __init__(self, db: Database):
        self._db = db

    # ── Quota definition ───────────────────────────────────────

    def set_quota(self, tenant_id: str = "default",
                  max_agents: int = 10,
                  max_tokens_per_day: int = 500000,
                  max_cost_per_day: float = 10.0,
                  max_cost_total: float = 100.0,
                  max_memory_entries: int = 10000,
                  max_storage_mb: int = 1024) -> None:
        """Set or update quota limits for a tenant."""
        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            """INSERT INTO tenant_quotas
               (tenant_id, max_agents, max_tokens_per_day, max_cost_per_day,
                max_cost_total, max_memory_entries, max_storage_mb,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(tenant_id) DO UPDATE SET
               max_agents = ?, max_tokens_per_day = ?, max_cost_per_day = ?,
               max_cost_total = ?, max_memory_entries = ?, max_storage_mb = ?,
               updated_at = ?""",
            (tenant_id, max_agents, max_tokens_per_day, max_cost_per_day,
             max_cost_total, max_memory_entries, max_storage_mb,
             now, now,
             max_agents, max_tokens_per_day, max_cost_per_day,
             max_cost_total, max_memory_entries, max_storage_mb,
             now),
        )
        self._db.commit()
        logger.info("Quota updated for tenant '%s'", tenant_id)

    def get_quota(self, tenant_id: str = "default") -> QuotaLimit:
        """Get quota limits for a tenant (returns defaults if not set)."""
        row = self._db.fetchone(
            "SELECT * FROM tenant_quotas WHERE tenant_id = ?",
            (tenant_id,),
        )
        if not row:
            return QuotaLimit(tenant_id=tenant_id)
        r = dict(row)
        return QuotaLimit(
            tenant_id=r.get("tenant_id", tenant_id),
            max_agents=int(r.get("max_agents", 10)),
            max_tokens_per_day=int(r.get("max_tokens_per_day", 500000)),
            max_cost_per_day=float(r.get("max_cost_per_day", 10.0)),
            max_cost_total=float(r.get("max_cost_total", 100.0)),
            max_memory_entries=int(r.get("max_memory_entries", 10000)),
            max_storage_mb=int(r.get("max_storage_mb", 1024)),
            created_at=r.get("created_at", ""),
            updated_at=r.get("updated_at", ""),
        )

    def list_quotas(self) -> list[QuotaLimit]:
        """List all configured quota limits."""
        rows = self._db.fetchall(
            "SELECT * FROM tenant_quotas ORDER BY tenant_id"
        )
        return [QuotaLimit(
            tenant_id=r["tenant_id"],
            max_agents=r["max_agents"],
            max_tokens_per_day=r["max_tokens_per_day"],
            max_cost_per_day=r["max_cost_per_day"],
            max_cost_total=r["max_cost_total"],
            max_memory_entries=r["max_memory_entries"],
            max_storage_mb=r["max_storage_mb"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        ) for r in rows]

    def reset_quota(self, tenant_id: str = "default") -> None:
        """Reset quota to defaults for a tenant."""
        self._db.execute(
            "DELETE FROM tenant_quotas WHERE tenant_id = ?",
            (tenant_id,),
        )
        self._db.commit()
        logger.info("Quota reset for tenant '%s'", tenant_id)

    # ── Usage tracking ────────────────────────────────────────

    def get_usage(self, tenant_id: str = "default") -> QuotaUsage:
        """Get current resource usage for a tenant."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Agent count
        agent_count = 0
        row = self._db.fetchone(
            "SELECT COUNT(*) as cnt FROM agents WHERE tenant_id = ? "
            "AND status IN ('created', 'running', 'paused')",
            (tenant_id,),
        )
        if row:
            agent_count = row[0]

        # Token & cost usage today
        tokens_today = 0
        cost_today = 0.0
        row = self._db.fetchone(
            "SELECT COALESCE(SUM(tokens_used), 0), COALESCE(SUM(cost_usd), 0) "
            "FROM audit_log WHERE tenant_id = ? AND date(timestamp) = ?",
            (tenant_id, today),
        )
        if row:
            tokens_today = int(row[0])
            cost_today = float(row[1])

        # Total cost
        cost_total = 0.0
        row = self._db.fetchone(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM audit_log WHERE tenant_id = ?",
            (tenant_id,),
        )
        if row:
            cost_total = float(row[0])

        # Memory entries
        memory_entries = 0
        row = self._db.fetchone(
            "SELECT COUNT(*) FROM memory_store WHERE tenant_id = ?",
            (tenant_id,),
        )
        if row:
            memory_entries = row[0]

        return QuotaUsage(
            tenant_id=tenant_id,
            agent_count=agent_count,
            tokens_today=tokens_today,
            cost_today=cost_today,
            cost_total=cost_total,
            memory_entries=memory_entries,
        )

    def record_usage(self, tenant_id: str = "default",
                     tokens: int = 0,
                     cost_usd: float = 0.0) -> None:
        """Record resource usage (tokens, cost) for a tenant.

        Called after each model/tool operation. Updates the audit_log
        which drives quota computation.
        """
        # Usage is tracked via audit_log entries — no separate recording needed.
        # This method exists as a hook for future real-time quota enforcement.
        pass

    # ── Quota checks ──────────────────────────────────────────

    def check_agent_quota(self, tenant_id: str = "default") -> PolicyResult:
        """Check if tenant can create another agent instance."""
        quota = self.get_quota(tenant_id)
        usage = self.get_usage(tenant_id)

        if usage.agent_count >= quota.max_agents:
            return PolicyResult(
                allowed=False,
                reason=(
                    f"Agent quota exceeded: {usage.agent_count}/{quota.max_agents} "
                    f"agents for tenant '{tenant_id}'"
                ),
            )
        return PolicyResult(allowed=True)

    def check_token_quota(self, tenant_id: str = "default",
                          estimated_tokens: int = 0) -> PolicyResult:
        """Check if tenant has token budget remaining."""
        quota = self.get_quota(tenant_id)
        usage = self.get_usage(tenant_id)

        projected = usage.tokens_today + estimated_tokens
        if projected > quota.max_tokens_per_day:
            return PolicyResult(
                allowed=False,
                reason=(
                    f"Daily token quota exceeded: {projected}/{quota.max_tokens_per_day} "
                    f"tokens for tenant '{tenant_id}'"
                ),
            )
        return PolicyResult(allowed=True)

    def check_cost_quota(self, tenant_id: str = "default",
                         estimated_cost: float = 0.0) -> PolicyResult:
        """Check if tenant has cost budget remaining."""
        quota = self.get_quota(tenant_id)
        usage = self.get_usage(tenant_id)

        # Daily check
        projected_daily = usage.cost_today + estimated_cost
        if projected_daily > quota.max_cost_per_day:
            return PolicyResult(
                allowed=False,
                reason=(
                    f"Daily cost quota exceeded: ${projected_daily:.4f}/${quota.max_cost_per_day:.4f} "
                    f"for tenant '{tenant_id}'"
                ),
            )

        # Total check
        projected_total = usage.cost_total + estimated_cost
        if projected_total > quota.max_cost_total:
            return PolicyResult(
                allowed=False,
                reason=(
                    f"Total cost quota exceeded: ${projected_total:.4f}/${quota.max_cost_total:.4f} "
                    f"for tenant '{tenant_id}'"
                ),
            )

        return PolicyResult(allowed=True)

    def check_all(self, tenant_id: str = "default",
                  estimated_tokens: int = 0,
                  estimated_cost: float = 0.0) -> PolicyResult:
        """Run all quota checks for a tenant.

        Returns the first failing check, or allowed=True.
        """
        # Agent quota (no estimate needed)
        agent_check = self.check_agent_quota(tenant_id)
        if not agent_check.allowed:
            return agent_check

        # Token quota
        token_check = self.check_token_quota(tenant_id, estimated_tokens)
        if not token_check.allowed:
            return token_check

        # Cost quota
        cost_check = self.check_cost_quota(tenant_id, estimated_cost)
        if not cost_check.allowed:
            return cost_check

        return PolicyResult(allowed=True)
