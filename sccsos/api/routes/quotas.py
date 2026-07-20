"""Quota API routes — resource quota status and configuration."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sccsos.core.agent_runtime import get_runtime
from sccsos.core.quota_manager import QuotaManager

router = APIRouter(prefix="/api/v1/quotas", tags=["quotas"])


class QuotaUpdateRequest(BaseModel):
    max_agents: Optional[int] = None
    max_tokens_per_day: Optional[int] = None
    max_cost_per_day: Optional[float] = None
    max_cost_total: Optional[float] = None
    max_memory_entries: Optional[int] = None


@router.get("/{tenant_id}")
async def quota_status(tenant_id: str = "default"):
    """Get current quota usage and limits for a tenant."""
    runtime = get_runtime()
    mgr = QuotaManager(runtime.db)

    limit = mgr.get_quota(tenant_id)
    usage = mgr.get_usage(tenant_id)

    return {
        "tenant_id": tenant_id,
        "max_agents": limit.max_agents,
        "max_tokens_per_day": limit.max_tokens_per_day,
        "max_cost_per_day": round(limit.max_cost_per_day, 4),
        "max_cost_total": round(limit.max_cost_total, 4),
        "max_memory_entries": limit.max_memory_entries,
        "current_agents": usage.agent_count,
        "tokens_today": usage.tokens_today,
        "cost_today": round(usage.cost_today, 6),
        "cost_total": round(usage.cost_total, 6),
        "memory_entries": usage.memory_entries,
    }


@router.post("/{tenant_id}")
async def quota_update(tenant_id: str, req: QuotaUpdateRequest):
    """Update quota limits for a tenant."""
    runtime = get_runtime()
    mgr = QuotaManager(runtime.db)

    current = mgr.get_quota(tenant_id)
    mgr.set_quota(
        tenant_id=tenant_id,
        max_agents=req.max_agents if req.max_agents is not None else current.max_agents,
        max_tokens_per_day=req.max_tokens_per_day if req.max_tokens_per_day is not None else current.max_tokens_per_day,
        max_cost_per_day=req.max_cost_per_day if req.max_cost_per_day is not None else current.max_cost_per_day,
        max_cost_total=req.max_cost_total if req.max_cost_total is not None else current.max_cost_total,
        max_memory_entries=req.max_memory_entries if req.max_memory_entries is not None else current.max_memory_entries,
    )
    return {"status": "updated", "tenant_id": tenant_id}
