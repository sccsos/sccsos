"""Trace routes — sccsos API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from sccsos.security.rbac import require_permission, P
from sccsos.core.agent_runtime import get_runtime

router = APIRouter(prefix="/api/v1", tags=["traces"])


@router.get("/traces")
async def list_traces(
    _: None = Depends(require_permission(P.TRACES_READ)),
):
    runtime = get_runtime()
    tracer = runtime.tracer
    traces = tracer.list_traces(limit=20)
    return {"traces": traces, "count": len(traces)}


@router.get("/traces/{trace_id}")
async def trace_detail(
    trace_id: str,
    _: None = Depends(require_permission(P.TRACES_READ)),
):
    runtime = get_runtime()
    tracer = runtime.tracer
    spans = tracer.get_trace(trace_id)
    if not spans:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found")
    return {"trace_id": trace_id, "spans": spans}
