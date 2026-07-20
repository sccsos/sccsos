"""Billing — usage-based cost reporting and CSV export.

Generates billing reports from the audit_log table.
Supports date range filtering, per-tenant breakdown, and CSV export.

Usage:
    exporter = BillingExporter(db)
    
    # Get summary for a date range
    summary = exporter.summary("2026-07-01", "2026-07-31")
    
    # Export CSV
    csv_path = exporter.export_csv("2026-07-01", "2026-07-31", tenant_id="tenant-1")
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

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
                tenant_id: Optional[str] = None) -> BillingSummary:
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
