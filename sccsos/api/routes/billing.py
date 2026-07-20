"""Billing API routes — usage summary and CSV export."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import Depends, APIRouter, Query
from fastapi.responses import StreamingResponse

from sccsos.security.rbac import require_permission
from sccsos.core.agent_runtime import get_runtime
from sccsos.observability.billing import BillingExporter, SubscriptionManager, SubscriptionPlan, PricingTier
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


def _today_utc() -> str:
    """Return today's date in UTC, matching audit_log timestamp convention."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@router.get("/summary")
async def billing_summary(
    _: None = Depends(require_permission("billing:read")),
    start: str = Query(default_factory=_today_utc),
    end: str = Query(default_factory=_today_utc),
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
    _: None = Depends(require_permission("billing:export")),
    start: str = Query(default_factory=_today_utc),
    end: str = Query(default_factory=_today_utc),
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

    csv_headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers=csv_headers,
    )


# ── Subscription endpoints ─────────────────────────────────────


class PlanRequest(BaseModel):
    """Request body for creating/updating a subscription plan."""
    tenant_id: str = "default"
    tier: str = "pay_per_token"
    monthly_fee: float = 0.0
    flat_fee_per_call: float = 0.01
    model_rates: dict[str, float] | None = None
    active: bool = True


@router.get("/plans")
async def list_plans(
    _: None = Depends(require_permission("billing:read")),
):
    """List all configured subscription plans."""
    runtime = get_runtime()
    mgr = SubscriptionManager(runtime.db)
    return {"plans": [
        {
            "tenant_id": p.tenant_id,
            "tier": p.tier.value,
            "monthly_fee": p.monthly_fee,
            "flat_fee_per_call": p.flat_fee_per_call,
            "model_rates": p.model_rates,
            "active": p.active,
        }
        for p in mgr.list_plans()
    ]}


@router.get("/plans/{tenant_id}")
async def get_plan(
    tenant_id: str,
    _: None = Depends(require_permission("billing:read")),
):
    """Get a tenant's subscription plan."""
    runtime = get_runtime()
    mgr = SubscriptionManager(runtime.db)
    p = mgr.get_plan(tenant_id)
    return {
        "tenant_id": p.tenant_id,
        "tier": p.tier.value,
        "monthly_fee": p.monthly_fee,
        "flat_fee_per_call": p.flat_fee_per_call,
        "model_rates": p.model_rates,
        "active": p.active,
    }


@router.post("/plans")
async def set_plan(
    plan: PlanRequest,
    _: None = Depends(require_permission("billing:export")),
):
    """Create or update a tenant's subscription plan."""
    runtime = get_runtime()
    mgr = SubscriptionManager(runtime.db)
    sp = SubscriptionPlan(
        tenant_id=plan.tenant_id,
        tier=PricingTier(plan.tier),
        monthly_fee=plan.monthly_fee,
        flat_fee_per_call=plan.flat_fee_per_call,
        model_rates=plan.model_rates or SubscriptionPlan().model_rates,
        active=plan.active,
    )
    updated = mgr.set_plan(sp)
    return {
        "status": "updated",
        "tenant_id": updated.tenant_id,
        "tier": updated.tier.value,
    }


@router.delete("/plans/{tenant_id}")
async def reset_plan(
    tenant_id: str,
    _: None = Depends(require_permission("billing:export")),
):
    """Reset a tenant's plan to defaults."""
    runtime = get_runtime()
    mgr = SubscriptionManager(runtime.db)
    mgr.reset_plan(tenant_id)
    return {"status": "reset", "tenant_id": tenant_id}
