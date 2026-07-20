"""Skill marketplace and review API routes.

Endpoints:

- GET  /api/v1/skills            — List all skills
- GET  /api/v1/skills/reviews    — List reviews by status
- GET  /api/v1/skills/{name}/review — Get review status for a skill
- POST /api/v1/skills/{name}/submit — Submit for review
- POST /api/v1/skills/{name}/approve — Approve a skill
- POST /api/v1/skills/{name}/reject  — Reject a skill with reason
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from sccsos.core.agent_runtime import AgentRuntime, get_runtime as _get_runtime

router = APIRouter(prefix="/api/v1", tags=["skills"])


def get_runtime() -> AgentRuntime:
    rt = _get_runtime()
    if not rt.is_initialized:
        rt.initialize()
    return rt


@router.get("/skills")
def list_skills(runtime: AgentRuntime = Depends(get_runtime)):
    """List all skills in the marketplace."""
    from sccsos.skill_market import SkillMarket
    market = SkillMarket(runtime.db)
    skills = market.list_skills()
    return [{"name": s.name, "version": s.version, "type": s.type,
             "status": s.status, "author": s.author,
             "description": s.description[:100]} for s in skills]


# ── Review endpoints ───────────────────────────────────────────────


@router.get("/skills/reviews")
def list_reviews(
    status: str = Query("pending_review",
                        pattern="^(draft|pending_review|approved|rejected|all)$"),
    runtime: AgentRuntime = Depends(get_runtime),
):
    """List skills in the review pipeline, filtered by status."""
    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)
    if status == "all":
        items = mgr.list_all()
    else:
        items = mgr.list_all(status=status)

    return [{
        "name": s.name,
        "version": s.version,
        "type": s.type,
        "status": s.status,
        "author": s.author,
        "description": s.description[:200],
        "review_notes": s.review_notes,
        "tags": s.tags,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
    } for s in items]


@router.get("/skills/{name}/review")
def get_review(name: str, version: str = Query("1.0"),
               runtime: AgentRuntime = Depends(get_runtime)):
    """Get the review status for a specific skill version."""
    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)
    review = mgr.get_review(name, version)
    if not review:
        raise HTTPException(status_code=404,
                            detail=f"Skill '{name}' v{version} not found")
    return {
        "name": review.name,
        "version": review.version,
        "type": review.type,
        "status": review.status,
        "author": review.author,
        "description": review.description,
        "review_notes": review.review_notes,
        "tags": review.tags,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
    }


@router.post("/skills/{name}/submit")
def submit_skill(name: str, version: str = Query("1.0"),
                 runtime: AgentRuntime = Depends(get_runtime)):
    """Submit a skill for review (draft → pending_review)."""
    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)
    ok = mgr.submit_for_review(name, version)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=f"Skill '{name}' v{version} could not be submitted. "
                   "Check it exists and is in 'draft' status.",
        )
    return {"status": "submitted", "name": name, "version": version}


@router.post("/skills/{name}/approve")
def approve_skill(name: str, version: str = Query("1.0"),
                  reviewer: str = Query("", alias="reviewer"),
                  runtime: AgentRuntime = Depends(get_runtime)):
    """Approve a skill (pending_review → approved)."""
    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)

    # Validate first
    validation = mgr.validate(name, version)
    if not validation.valid:
        raise HTTPException(
            status_code=400,
            detail=f"Validation failed: {'; '.join(validation.errors)}",
        )

    ok = mgr.approve(name, version, reviewer=reviewer)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=f"Skill '{name}' v{version} could not be approved.",
        )
    return {"status": "approved", "name": name, "version": version,
            "reviewer": reviewer or "system"}


@router.post("/skills/{name}/reject")
def reject_skill(name: str, reason: str = Query(..., min_length=1),
                 version: str = Query("1.0"),
                 runtime: AgentRuntime = Depends(get_runtime)):
    """Reject a skill with a reason (pending_review → rejected)."""
    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)
    ok = mgr.reject(name, version, reason=reason)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=f"Skill '{name}' v{version} could not be rejected. "
                   "Check it exists and is pending review.",
        )
    return {"status": "rejected", "name": name, "version": version,
            "reason": reason}


@router.get("/skills/verify")
def verify_skills(runtime: AgentRuntime = Depends(get_runtime)):
    """Verify all published/approved skills for YAML validity."""
    from sccsos.skill_market import SkillMarket
    market = SkillMarket(runtime.db)
    result = market.verify_all()
    return result


@router.post("/skills/prune")
def prune_skills(
    days: int = Query(90, ge=1, description="Age threshold in days"),
    runtime: AgentRuntime = Depends(get_runtime),
):
    """Delete stale draft/rejected skills not updated in N days."""
    from sccsos.skill_market import SkillMarket
    market = SkillMarket(runtime.db)
    result = market.prune_stale(days=days)
    return {"pruned": result, "total": sum(result.values())}
