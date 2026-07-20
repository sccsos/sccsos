"""Billing API routes — usage summary and CSV export."""
from __future__ import annotations

import csv
import io
from datetime import date
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from sccsos.core.agent_runtime import get_runtime
from sccsos.observability.billing import BillingExporter

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


@router.get("/summary")
async def billing_summary(
    start: str = Query(default_factory=lambda: date.today().isoformat()),
    end: str = Query(default_factory=lambda: date.today().isoformat()),
    tenant: Optional[str] = Query(default=None),
):
    """Get billing summary for a date range."""
    runtime = get_runtime()
    exporter = BillingExporter(runtime.db)
    s = exporter.summary(start, end, tenant_id=tenant)
    return {
        "total_calls": s.total_calls,
        "total_tokens": s.total_tokens,
        "total_cost": round(s.total_cost, 6),
        "total_duration_ms": s.total_duration_ms,
        "by_agent": s.by_agent,
        "by_model": s.by_model,
        "by_day": s.by_day,
        "by_tool": s.by_tool,
    }


@router.get("/export")
async def billing_export(
    start: str = Query(default_factory=lambda: date.today().isoformat()),
    end: str = Query(default_factory=lambda: date.today().isoformat()),
    tenant: Optional[str] = Query(default=None),
):
    """Export detailed billing records as CSV download."""
    runtime = get_runtime()
    exporter = BillingExporter(runtime.db)

    records = exporter.query_records(start, end, tenant_id=tenant)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "timestamp", "tenant_id", "agent_id", "event_type",
        "tool_name", "model_name", "tokens_used", "cost_usd",
        "duration_ms", "success",
    ])
    for r in records:
        writer.writerow([
            r.timestamp, r.tenant_id, r.agent_id, r.event_type,
            r.tool_name, r.model_name, r.tokens_used,
            f"{r.cost_usd:.6f}", r.duration_ms, 1 if r.success else 0,
        ])

    filename = f"billing_{start}_{end}"
    if tenant:
        filename += f"_{tenant}"
    filename += ".csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
