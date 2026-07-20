"""Agent routes — sccsos API."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sccsos.core.agent_runtime import get_runtime
from sccsos.core.registry import AgentSpec
from sccsos.core.lifecycle import AgentStatus
from sccsos.api.models import RegisterAgentRequest, AskRequest

router = APIRouter(prefix="/api/v1", tags=["agents"])


@router.get("/agents")
async def list_agents(
    tenant_id: str = Query("default", alias="X-Tenant-ID"),
):
    runtime = get_runtime()
    agents = [
        {
            "name": a.name,
            "version": a.version,
            "description": a.description[:60],
            "tenant_id": getattr(a, "tenant_id", tenant_id),
        }
        for a in runtime.registry.list()
    ]
    return {"agents": agents, "count": len(agents), "tenant_id": tenant_id}


@router.post("/agents/register", status_code=201)
async def register_agent(req: RegisterAgentRequest):
    runtime = get_runtime()
    spec = AgentSpec(
        name=req.name,
        version=req.version,
        description=req.description,
        toolsets=req.toolsets,
        tags=req.tags,
        tenant_id=req.tenant_id,
    )
    runtime.register_agent(spec)
    runtime.lifecycle.create(spec)
    return {"registered": spec.name}


@router.get("/agents/{name}")
async def agent_status(name: str, tenant_id: str = "default"):
    runtime = get_runtime()
    record = runtime.db.get_agent_by_name(name, tenant_id=tenant_id)
    if record:
        events = runtime.db.get_events(record["id"], limit=5)
        return {
            "id": record["id"],
            "name": name,
            "tenant_id": record.get("tenant_id", tenant_id),
            "status": record["status"],
            "profile": record["hermes_profile"],
            "session_id": record.get("session_id", ""),
            "events": [
                {"event": e["event"], "detail": e.get("detail", "")}
                for e in events
            ],
        }
    spec = runtime.registry.find(name)
    if spec:
        return {
            "name": spec.name,
            "status": "registered",
            "version": spec.version,
            "description": spec.description,
        }
    raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")


@router.post("/agents/{name}/start")
async def start_agent(name: str):
    runtime = get_runtime()
    spec = runtime.registry.find(name)
    if not spec:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    instance = runtime.lifecycle.create(spec)
    runtime.lifecycle.start(instance.id)
    profile = spec.profile or "sccsos"
    runtime.runner.start_agent(
        name, profile=profile,
        policy_engine=runtime.policy_engine,
        model=spec.model,
    )
    return {"started": instance.spec.name, "id": instance.id}


@router.post("/agents/{name}/stop")
async def stop_agent(name: str):
    runtime = get_runtime()
    runtime.runner.stop_agent(name)
    for inst in runtime.lifecycle.list_instances():
        if inst.spec.name == name and inst.status in (
            AgentStatus.RUNNING, AgentStatus.PAUSED, AgentStatus.FAILED
        ):
            runtime.lifecycle.stop(inst.id)
            return {"stopped": name}
    raise HTTPException(status_code=404, detail=f"No running instance of '{name}'")


@router.post("/agents/{name}/pause")
async def pause_agent(name: str):
    runtime = get_runtime()
    for inst in runtime.lifecycle.list_instances():
        if inst.spec.name == name and inst.status == AgentStatus.RUNNING:
            runtime.lifecycle.pause(inst.id)
            runtime.runner.pause_agent(name)
            return {"paused": name, "id": inst.id}
    raise HTTPException(status_code=404, detail=f"No running instance of '{name}'")


@router.post("/agents/{name}/resume")
async def resume_agent(name: str):
    runtime = get_runtime()
    for inst in runtime.lifecycle.list_instances():
        if inst.spec.name == name and inst.status == AgentStatus.PAUSED:
            runtime.lifecycle.resume(inst.id)
            runtime.runner.resume_agent(name)
            return {"resumed": name, "id": inst.id}
    raise HTTPException(status_code=404, detail=f"No paused instance of '{name}'")


@router.post("/agents/{name}/restart")
async def restart_agent(name: str):
    runtime = get_runtime()
    for inst in runtime.lifecycle.list_instances():
        if inst.spec.name == name:
            if inst.status == AgentStatus.FAILED:
                runtime.lifecycle.restart(inst.id)
            elif inst.status == AgentStatus.RUNNING:
                runtime.lifecycle.fail(inst.id, "restart requested")
                runtime.lifecycle.restart(inst.id)
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot restart agent in '{inst.status.value}' state",
                )
            runtime.runner.stop_agent(name)
            profile = inst.spec.profile or "sccsos"
            runtime.runner.start_agent(
                name, profile=profile,
                policy_engine=runtime.policy_engine,
                model=inst.spec.model,
            )
            return {"restarted": name, "id": inst.id}
    raise HTTPException(status_code=404, detail=f"No instance of '{name}' found")


@router.post("/agents/{name}/ask")
async def ask_agent(name: str, req: AskRequest):
    runtime = get_runtime()
    result = runtime.runner.ask_agent(name, req.prompt, timeout=req.timeout)
    return {
        "response": result.response,
        "success": result.success,
        "error": result.error if not result.success else "",
    }
