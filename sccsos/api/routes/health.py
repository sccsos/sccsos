"""Health route — sccsos API."""
from __future__ import annotations

from fastapi import APIRouter
from sccsos.core.agent_runtime import get_runtime

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
async def health():
    runtime = get_runtime()
    return runtime.health()
