"""Billing — multi-tier cost reporting with token / subscription / per-call pricing.

Supports three billing tiers:
  1. **pay_per_token**: Cost = tokens_used × model_rate (current default)
  2. **per_call**: Cost = calls × flat_fee_per_call
  3. **subscription**: Fixed monthly fee (regardless of usage)

Usage:
    exporter = BillingExporter(db)

    # Get summary for a date range
    summary = exporter.summary("2026-07-01", "2026-07-31",
                               tenant_id="tenant-1", tier="pay_per_token")

    # Or with subscription pricing
    summary = exporter.summary("2026-07-01", "2026-07-31",
                               tenant_id="tenant-1", tier="subscription")
"""

from __future__ import annotations

import csv
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from sccsos.core.db import Database

logger = logging.getLogger("sccsos.billing")


@dataclass
class BillingRecord:
    """A single billable event from the audit log."""
    timestamp: str
    tenant_id: str
    agent_id: str
    event_type: str
    tool_name: str
    model_name: str
    tokens_used: int
    cost_usd: float
    duration_ms: int
    success: bool


@dataclass
class BillingSummary:
    """Aggregated billing summary."""
    total_tokens: int = 0
    total_cost: float = 0.0
    total_calls: int = 0
    total_duration_ms: int = 0
    by_agent: dict[str, float] = field(default_factory=dict)
    by_model: dict[str, float] = field(default_factory=dict)
    by_day: dict[str, float] = field(default_factory=dict)
    by_tool: dict[str, int] = field(default_factory=dict)


CSV_HEADERS = [
    "timestamp", "tenant_id", "agent_id", "event_type",
    "tool_name", "model_name", "tokens_used", "cost_usd",
    "duration_ms", "success",
]


# ── Pricing tiers ──────────────────────────────────────────────


class PricingTier(str, Enum):
    """Supported billing tiers."""
    PAY_PER_TOKEN = "pay_per_token"   # cost = tokens × model_rate
    PER_CALL = "per_call"             # cost = calls × flat_fee
    SUBSCRIPTION = "subscription"     # fixed monthly fee


@dataclass
class SubscriptionPlan:
    """A tenant's subscription plan.

    Persisted to the ``subscriptions`` DB table.
    """
    id: str = ""
    tenant_id: str = "default"
    tier: PricingTier = PricingTier.PAY_PER_TOKEN
    monthly_fee: float = 0.0           # USD / month (subscription tier)
    flat_fee_per_call: float = 0.01    # USD / call (per_call tier)
    model_rates: dict[str, float] = field(default_factory=lambda: {
        "gpt-4": 0.03,
        "gpt-3.5": 0.002,
        "claude-3": 0.015,
        "deepseek": 0.002,
        "default": 0.01,
    })
    active: bool = True
    created_at: str = ""
    updated_at: str = ""


SUBSCRIPTION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL UNIQUE,
    tier TEXT NOT NULL DEFAULT 'pay_per_token',
    monthly_fee REAL DEFAULT 0.0,
    flat_fee_per_call REAL DEFAULT 0.01,
    model_rates TEXT DEFAULT '{}',
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT ''
);
"""


# ── Subscription Manager ────────────────────────────────────────


class SubscriptionManager:
    """Manages tenant subscription plans and tier-aware cost calculation.

    Args:
        db: Database instance (will create ``subscriptions`` table).
    """

    def __init__(self, db: Database):
        self._db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create subscriptions table if it doesn't exist."""
        self._db.execute(SUBSCRIPTION_TABLE_SQL)
        self._db.commit()

    # ── CRUD ────────────────────────────────────────────────────

    def get_plan(self, tenant_id: str = "default") -> SubscriptionPlan:
        """Get a tenant's subscription plan (returns defaults if not set)."""
        row = self._db.fetchone(
            "SELECT * FROM subscriptions WHERE tenant_id = ?",
            (tenant_id,),
        )
        if not row:
            return SubscriptionPlan(tenant_id=tenant_id)
        r = dict(row)
        import json
        return SubscriptionPlan(
            id=r.get("id", ""),
            tenant_id=r.get("tenant_id", tenant_id),
            tier=PricingTier(r.get("tier", "pay_per_token")),
            monthly_fee=float(r.get("monthly_fee", 0.0)),
            flat_fee_per_call=float(r.get("flat_fee_per_call", 0.01)),
            model_rates=json.loads(r.get("model_rates", "{}")) or SubscriptionPlan().model_rates,
            active=bool(r.get("active", True)),
            created_at=r.get("created_at", ""),
            updated_at=r.get("updated_at", ""),
        )

    def set_plan(self, plan: SubscriptionPlan) -> SubscriptionPlan:
        """Create or update a tenant's subscription plan."""
        now = datetime.now(timezone.utc).isoformat()
        if not plan.id:
            plan.id = str(uuid.uuid4())
        import json
        model_rates_json = json.dumps(plan.model_rates, ensure_ascii=False)
        self._db.execute(
            """INSERT INTO subscriptions
               (id, tenant_id, tier, monthly_fee, flat_fee_per_call,
                model_rates, active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(tenant_id) DO UPDATE SET
               tier = ?, monthly_fee = ?, flat_fee_per_call = ?,
               model_rates = ?, active = ?, updated_at = ?""",
            (plan.id, plan.tenant_id, plan.tier.value, plan.monthly_fee,
             plan.flat_fee_per_call, model_rates_json,
             1 if plan.active else 0, now, now,
             plan.tier.value, plan.monthly_fee, plan.flat_fee_per_call,
             model_rates_json, 1 if plan.active else 0, now),
        )
        self._db.commit()
        return self.get_plan(plan.tenant_id)

    def list_plans(self) -> list[SubscriptionPlan]:
        """List all configured subscription plans."""
        rows = self._db.fetchall("SELECT * FROM subscriptions ORDER BY tenant_id")
        import json
        result = []
        for r in rows:
            rd = dict(r)
            result.append(SubscriptionPlan(
                id=rd.get("id", ""),
                tenant_id=rd.get("tenant_id", ""),
                tier=PricingTier(rd.get("tier", "pay_per_token")),
                monthly_fee=float(rd.get("monthly_fee", 0.0)),
                flat_fee_per_call=float(rd.get("flat_fee_per_call", 0.01)),
                model_rates=json.loads(rd.get("model_rates", "{}")) or SubscriptionPlan().model_rates,
                active=bool(rd.get("active", True)),
                created_at=rd.get("created_at", ""),
                updated_at=rd.get("updated_at", ""),
            ))
        return result

    def reset_plan(self, tenant_id: str = "default") -> None:
        """Remove a tenant's custom plan (reverts to defaults)."""
        self._db.execute("DELETE FROM subscriptions WHERE tenant_id = ?", (tenant_id,))
        self._db.commit()

    # ── Cost calculation ────────────────────────────────────────

    def calculate_cost(self, tenant_id: str, tokens_used: int,
                       calls: int = 1, model: str = "default") -> float:
        """Calculate cost for a usage event based on the tenant's tier.

        Args:
            tenant_id: Tenant identifier.
            tokens_used: Number of tokens consumed.
            calls: Number of API calls (for per_call tier).
            model: Model name (for pay_per_token tier rate lookup).

        Returns:
            Cost in USD.
        """
        plan = self.get_plan(tenant_id)
        if not plan.active:
            return 0.0

        if plan.tier == PricingTier.SUBSCRIPTION:
            # Subscription tier: no per-event cost (already covered by monthly fee)
            return 0.0

        if plan.tier == PricingTier.PER_CALL:
            return calls * plan.flat_fee_per_call

        # Default: pay_per_token
        rate = plan.model_rates.get(model, plan.model_rates.get("default", 0.01))
        return tokens_used * rate / 1_000_000  # rate is per 1M tokens


class BillingExporter:
    """Billing report generation and CSV export.

    Args:
        db: Database instance with audit_log table.
    """

    def __init__(self, db: Database):
        self._db = db

    # ── Queries ────────────────────────────────────────────────

    def query_records(self, start_date: str, end_date: str,
                      tenant_id: Optional[str] = None,
                      agent_id: Optional[str] = None,
                      limit: int = 50000) -> list[BillingRecord]:
        """Query audit log records within a date range.

        Args:
            start_date: ISO date string (e.g. ``"2026-07-01"``).
            end_date: ISO date string (e.g. ``"2026-07-31"``).
            tenant_id: Optional tenant filter.
            agent_id: Optional agent filter.
            limit: Max records (default 50000).

        Returns:
            List of BillingRecord.
        """
        conditions = ["date(timestamp) >= ?", "date(timestamp) <= ?"]
        params = [start_date, end_date]

        if tenant_id:
            conditions.append("tenant_id = ?")
            params.append(tenant_id)
        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)

        where = " AND ".join(conditions)
        rows = self._db.fetchall(
            f"SELECT timestamp, tenant_id, agent_id, event_type, "
            f"tool_name, model_name, tokens_used, cost_usd, "
            f"duration_ms, success "
            f"FROM audit_log WHERE {where} "
            f"ORDER BY timestamp DESC LIMIT ?",
            (*params, limit),
        )

        return [
            BillingRecord(
                timestamp=r["timestamp"],
                tenant_id=r["tenant_id"],
                agent_id=r["agent_id"],
                event_type=r["event_type"],
                tool_name=dict(r).get("tool_name", ""),
                model_name=dict(r).get("model_name", ""),
                tokens_used=int(dict(r).get("tokens_used", 0)),
                cost_usd=float(dict(r).get("cost_usd", 0.0)),
                duration_ms=int(dict(r).get("duration_ms", 0)),
                success=bool(dict(r).get("success", True)),
            )
            for r in rows
        ]

    def summary(self, start_date: str, end_date: str,
                tenant_id: Optional[str] = None,
                tier: Optional[str] = None) -> BillingSummary:
        """Get aggregated billing summary.

        Args:
            start_date: ISO date string.
            end_date: ISO date string.
            tenant_id: Optional tenant filter.

        Returns:
            BillingSummary with aggregations.
        """
        s = BillingSummary()
        records = self.query_records(start_date, end_date, tenant_id=tenant_id)

        for r in records:
            s.total_tokens += r.tokens_used
            s.total_cost += r.cost_usd
            s.total_calls += 1
            s.total_duration_ms += r.duration_ms

            # By agent
            s.by_agent[r.agent_id] = s.by_agent.get(r.agent_id, 0.0) + r.cost_usd

            # By model
            model = r.model_name or "unknown"
            s.by_model[model] = s.by_model.get(model, 0.0) + r.cost_usd

            # By day
            day = str(r.timestamp)[:10] if r.timestamp else "unknown"
            s.by_day[day] = s.by_day.get(day, 0.0) + r.cost_usd

            # By tool
            tool = r.tool_name or r.event_type or "unknown"
            s.by_tool[tool] = s.by_tool.get(tool, 0) + 1

        # If a pricing tier is specified, recalculate costs
        if tier and tier != "pay_per_token":
            mgr = SubscriptionManager(self._db)
            target_tenant = tenant_id or "default"
            for r in records:
                if tier == "subscription":
                    s.total_cost = 0.0
                    s.by_agent.clear()
                    s.by_model.clear()
                    s.by_day.clear()
                    break
                elif tier == "per_call":
                    cost = mgr.calculate_cost(
                        target_tenant, calls=1, tokens_used=0,
                        model=r.model_name,
                    )
                    s.total_cost += cost - r.cost_usd  # adjust from recorded cost
                    # Rebuild agent/model/day breakdown
                    s.by_agent[r.agent_id] = s.by_agent.get(r.agent_id, 0.0) + cost
                    s.by_model[r.model_name or "unknown"] = s.by_model.get(r.model_name or "unknown", 0.0) + cost
                    day = str(r.timestamp)[:10] if r.timestamp else "unknown"
                    s.by_day[day] = s.by_day.get(day, 0.0) + cost

        return s

    # ── CSV export ─────────────────────────────────────────────

    def export_csv(self, start_date: str, end_date: str,
                   tenant_id: Optional[str] = None,
                   output_path: Optional[str] = None) -> str:
        """Export billing records to CSV.

        Args:
            start_date: ISO date string.
            end_date: ISO date string.
            tenant_id: Optional tenant filter.
            output_path: Output file path. If omitted, generates one.

        Returns:
            Path to the generated CSV file.
        """
        records = self.query_records(start_date, end_date, tenant_id=tenant_id)

        if not output_path:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            tenant_suffix = f"_{tenant_id}" if tenant_id else ""
            output_path = f"billing_{start_date}_{end_date}{tenant_suffix}_{timestamp}.csv"

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)

            for record in records:
                writer.writerow([
                    record.timestamp,
                    record.tenant_id,
                    record.agent_id,
                    record.event_type,
                    record.tool_name,
                    record.model_name,
                    record.tokens_used,
                    f"{record.cost_usd:.6f}",
                    record.duration_ms,
                    1 if record.success else 0,
                ])

        logger.info("Billing CSV exported: %s (%d records)", output, len(records))
        return str(output)

    def export_summary_csv(self, start_date: str, end_date: str,
                           output_path: Optional[str] = None) -> str:
        """Export a summary CSV with daily costs per tenant.

        Args:
            start_date: ISO date string.
            end_date: ISO date string.
            output_path: Output file path.

        Returns:
            Path to the generated CSV file.
        """
        # Get daily cost per tenant
        rows = self._db.fetchall(
            """SELECT date(timestamp) as day, tenant_id,
               COUNT(*) as calls,
               SUM(tokens_used) as tokens,
               SUM(cost_usd) as cost
               FROM audit_log
               WHERE date(timestamp) >= ? AND date(timestamp) <= ?
               GROUP BY day, tenant_id
               ORDER BY day DESC, tenant_id""",
            (start_date, end_date),
        )

        if not output_path:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_path = f"billing_summary_{start_date}_{end_date}_{timestamp}.csv"

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "tenant_id", "calls", "tokens", "cost_usd"])

            for r in rows:
                writer.writerow([
                    r["day"],
                    r["tenant_id"],
                    r["calls"],
                    r["tokens"],
                    f"{float(r['cost']):.4f}" if r["cost"] else "0.0000",
                ])

        logger.info("Billing summary exported: %s", output)
        return str(output)
