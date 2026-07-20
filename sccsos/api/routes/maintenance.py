"""Maintenance API routes — trigger cleanup and view status."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sccsos.core.agent_runtime import AgentRuntime, get_runtime as _get_runtime

router = APIRouter(prefix="/api/v1", tags=["maintenance"])


def get_runtime() -> AgentRuntime:
    rt = _get_runtime()
    if not rt.is_initialized:
        rt.initialize()
    return rt


@router.post("/maintenance/run")
def run_maintenance(runtime: AgentRuntime = Depends(get_runtime)):
    """Run a single maintenance pass (prune stale skills, verify)."""
    from sccsos.core.maintenance import MaintenanceScheduler
    scheduler = MaintenanceScheduler(runtime.db)
    results = scheduler.run_once()
    return results


@router.get("/maintenance/status")
def maintenance_status(runtime: AgentRuntime = Depends(get_runtime)):
    """Check maintenance scheduler status."""
    from sccsos.cli.maintenance_cmd import _scheduler
    if _scheduler and hasattr(_scheduler, '_thread') and \
       _scheduler._thread and _scheduler._thread.is_alive():
        return {"status": "running"}
    return {"status": "stopped"}
