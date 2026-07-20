"""Workflow routes — sccsos API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sccsos.core.agent_runtime import get_runtime
from sccsos.core.workflow import WorkflowDef
from sccsos.api.models import RunWorkflowRequest, ValidateWorkflowRequest

router = APIRouter(prefix="/api/v1", tags=["workflows"])


@router.get("/workflows")
async def list_workflows():
    runtime = get_runtime()
    runs = runtime.engine.list_runs(limit=20)
    return {"runs": runs, "count": len(runs)}


@router.post("/workflows/run", status_code=201)
async def run_workflow(req: RunWorkflowRequest):
    runtime = get_runtime()
    try:
        wf = WorkflowDef.from_yaml(req.file)
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail=f"Workflow file not found: {req.file}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid workflow: {e}")
    run_id = runtime.engine.execute(wf, input_data=req.input)
    status = runtime.engine.get_run_status(run_id)
    return {"run_id": run_id, "status": status["status"]}


@router.post("/workflows/validate")
async def validate_workflow(req: ValidateWorkflowRequest):
    runtime = get_runtime()
    try:
        wf = WorkflowDef.from_yaml(req.file)
        warnings = runtime.engine.validate(wf)
        return {
            "valid": len(warnings) == 0,
            "workflow": wf.name,
            "version": wf.version,
            "steps": len(wf.steps),
            "warnings": warnings,
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


@router.get("/workflows/visualize")
async def visualize_workflow(file: str = Query(...)):
    try:
        wf = WorkflowDef.from_yaml(file)
        mermaid = wf.to_mermaid()
        return {"workflow": wf.name, "mermaid": mermaid}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/workflows/{run_id}")
async def workflow_status(run_id: str):
    runtime = get_runtime()
    try:
        return runtime.engine.get_run_status(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")


@router.post("/workflows/{run_id}/cancel")
async def cancel_workflow(run_id: str):
    runtime = get_runtime()
    try:
        runtime.engine.get_run_status(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    runtime.engine.cancel_run(run_id)
    return {"cancelled": run_id}
