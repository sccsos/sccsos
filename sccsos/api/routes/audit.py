"""Audit routes — sccsos API."""
from __future__ import annotations

from fastapi import APIRouter
from sccsos.core.agent_runtime import get_runtime

router = APIRouter(prefix="/api/v1", tags=["audit"])


@router.get("/audit/report")
async def audit_report(since: str = "", agent: str = ""):
    runtime = get_runtime()
    report = runtime.auditor.generate_report(
        since=since if since else None,
        agent_id=agent if agent else None,
    )
    return report


@router.get("/audit/log")
async def audit_log(limit: int = 20, agent: str = ""):
    runtime = get_runtime()
    entries = runtime.auditor.list_recent(
        limit=limit,
        agent_id=agent if agent else None,
    )
    return {"entries": entries, "count": len(entries)}
