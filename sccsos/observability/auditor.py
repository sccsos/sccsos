"""Auditor — Token usage auditing and cost accounting.

Tracks all LLM calls and tool invocations with token counts
and cost estimates. Uses standard pricing for known models
and estimates for unknown ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sccsos.core.database import Database
from sccsos.observability.pricing import PricingTable


# ── Default pricing (used when no PricingTable is configured) ────────

DEFAULT_INPUT_PRICE = 0.50
DEFAULT_OUTPUT_PRICE = 2.00


@dataclass
class AuditEntry:
    """A single auditable event."""
    agent_id: str
    event_type: str  # 'llm_call' | 'tool_call' | 'workflow_step'
    tenant_id: str = "default"
    tool_name: str = ""
    model_name: str = "deepseek-v4-flash"
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    success: bool = True
    detail: str = ""


class Auditor:
    """Records and queries audit events with cost tracking."""

    def __init__(self, db: Database, pricing: PricingTable):
        self._db = db
        self._pricing = pricing

    def record(self, entry: AuditEntry) -> int:
        """Record an audit entry. Returns entry ID."""
        cursor = self._db.execute(
            """INSERT INTO audit_log
               (tenant_id, agent_id, event_type, tool_name, model_name,
                tokens_used, cost_usd, duration_ms, success, detail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                getattr(entry, 'tenant_id', 'default'),
                entry.agent_id,
                entry.event_type,
                entry.tool_name,
                entry.model_name,
                entry.tokens_input + entry.tokens_output,
                entry.cost_usd,
                entry.duration_ms,
                1 if entry.success else 0,
                entry.detail[:500],
            ),
        )
        self._db.commit()
        return cursor.lastrowid

    def record_llm_call(self, agent_id: str, model: str,
                        tokens_input: int, tokens_output: int,
                        duration_ms: int = 0,
                        success: bool = True,
                        tenant_id: str = "default") -> int:
        """Record an LLM API call with cost estimation."""
        cost = self._pricing.estimate_cost(model, tokens_input, tokens_output)
        entry = AuditEntry(
            agent_id=agent_id,
            event_type="llm_call",
            tenant_id=tenant_id,
            model_name=model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost_usd=cost,
            duration_ms=duration_ms,
            success=success,
            detail=f"LLM call: {model} ({tokens_input}+{tokens_output} tokens, ${cost:.6f})",
        )
        return self.record(entry)

    def record_tool_call(self, agent_id: str, tool: str,
                         duration_ms: int = 0,
                         success: bool = True,
                         tenant_id: str = "default") -> int:
        """Record a tool invocation."""
        entry = AuditEntry(
            agent_id=agent_id,
            event_type="tool_call",
            tenant_id=tenant_id,
            tool_name=tool,
            duration_ms=duration_ms,
            success=success,
            detail=f"Tool: {tool}",
        )
        return self.record(entry)

    def generate_report(self, since: Optional[str] = None,
                        agent_id: Optional[str] = None) -> dict:
        """Generate an audit summary report.

        Args:
            since: ISO datetime string (e.g. '2026-07-01')
            agent_id: Filter by agent ID

        Returns:
            Report dict with totals and breakdowns.
        """
        conditions = []
        params = []
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        # Summary
        summary = self._db.execute(
            f"""SELECT
                   COUNT(*) as total_calls,
                   COALESCE(SUM(tokens_used), 0) as total_tokens,
                   COALESCE(SUM(cost_usd), 0) as total_cost,
                   COALESCE(AVG(duration_ms), 0) as avg_duration_ms,
                   SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
                   SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as fail_count
               FROM audit_log {where}""",
            params,
        ).fetchone()

        # By event type
        by_type = self._db.execute(
            f"""SELECT event_type,
                       COUNT(*) as count,
                       COALESCE(SUM(tokens_used), 0) as tokens,
                       COALESCE(SUM(cost_usd), 0) as cost
               FROM audit_log {where}
               GROUP BY event_type ORDER BY cost DESC""",
            params,
        ).fetchall()

        # By model
        by_model = self._db.execute(
            f"""SELECT model_name,
                       COUNT(*) as count,
                       COALESCE(SUM(tokens_used), 0) as tokens,
                       COALESCE(SUM(cost_usd), 0) as cost
               FROM audit_log {where}
               WHERE event_type = 'llm_call'
               GROUP BY model_name ORDER BY cost DESC""",
            params,
        ).fetchall()

        # Cost over time (daily)
        by_day = self._db.execute(
            f"""SELECT date(timestamp) as day,
                       COALESCE(SUM(cost_usd), 0) as cost
               FROM audit_log {where}
               GROUP BY day ORDER BY day""",
            params,
        ).fetchall()

        return {
            "summary": dict(summary),
            "by_event_type": [dict(r) for r in by_type],
            "by_model": [dict(r) for r in by_model],
            "cost_by_day": [dict(r) for r in by_day],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def list_recent(self, limit: int = 50,
                    agent_id: Optional[str] = None) -> list[dict]:
        """List recent audit entries."""
        if agent_id:
            rows = self._db.execute(
                """SELECT * FROM audit_log
                   WHERE agent_id = ? ORDER BY timestamp DESC LIMIT ?""",
                (agent_id, limit),
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
