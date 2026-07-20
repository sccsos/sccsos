"""Session routes — sccsos API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sccsos.core.agent_runtime import get_runtime

router = APIRouter(prefix="/api/v1", tags=["sessions"])


@router.get("/sessions")
async def list_sessions(
    agent: str = "",
    tenant_id: str = "default",
    status: str = "",
):
    runtime = get_runtime()
    sessions = runtime.session_manager.list_sessions(
        agent_name=agent if agent else None,
        tenant_id=tenant_id,
        status=status if status else None,
    )
    return {
        "sessions": [
            {
                "id": s.id,
                "agent_name": s.agent_name,
                "status": s.status,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "context_summary": s.context_summary,
            }
            for s in sessions
        ],
        "count": len(sessions),
    }


@router.get("/sessions/{session_id}")
async def session_detail(session_id: str):
    runtime = get_runtime()
    sessions = runtime.session_manager.list_sessions()
    session_obj = next((s for s in sessions if s.id == session_id), None)
    if session_obj is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return {
        "id": session_obj.id,
        "agent_name": session_obj.agent_name,
        "status": session_obj.status,
        "created_at": session_obj.created_at,
        "updated_at": session_obj.updated_at,
        "context_summary": session_obj.context_summary,
    }


@router.get("/sessions/{session_id}/messages")
async def session_messages(session_id: str):
    runtime = get_runtime()
    messages = runtime.session_manager.get_history(session_id, limit=50)
    return {
        "session_id": session_id,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "tokens": m.tokens,
                "created_at": m.created_at,
            }
            for m in messages
        ],
        "count": len(messages),
    }


@router.post("/sessions/{session_id}/close")
async def close_session(session_id: str):
    runtime = get_runtime()
    sessions = runtime.session_manager.list_sessions()
    session_obj = next((s for s in sessions if s.id == session_id), None)
    if session_obj is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    if session_obj.status == "closed":
        return {"closed": session_id}
    runtime.session_manager.close_session(session_id, new_status="closed")
    return {"closed": session_id}
