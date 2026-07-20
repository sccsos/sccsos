"""Skill marketplace and review API routes.

Endpoints:
  Market:
  - GET   /api/v1/skills            — List/search skills (supports ?type=&tag=&q=)
  - POST  /api/v1/skills            — Publish a new skill
  - GET   /api/v1/skills/installed  — List installed skills
  - POST  /api/v1/skills/{name}/install — Install a published skill
  - DELETE /api/v1/skills/installed/{name} — Remove installed skill

  Review:
  - GET   /api/v1/skills/reviews         — List reviews by status
  - GET   /api/v1/skills/{name}/review   — Get review status
  - POST  /api/v1/skills/{name}/submit   — Submit for review
  - POST  /api/v1/skills/{name}/approve  — Approve a skill
  - POST  /api/v1/skills/{name}/reject   — Reject a skill
  - GET   /api/v1/skills/verify          — Verify skill YAML validity
  - POST  /api/v1/skills/prune           — Prune stale skills
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from sccsos.core.agent_runtime import AgentRuntime, get_runtime as _get_runtime
from sccsos.security.rbac import require_permission, P

router = APIRouter(prefix="/api/v1", tags=["skills"])


def get_runtime() -> AgentRuntime:
    rt = _get_runtime()
    if not rt.is_initialized:
        rt.initialize()
    return rt


# ── Market endpoints ────────────────────────────────────────────────


@router.get("/skills")
def list_skills(
    status: str = Query("", description="Filter by status (draft/published/archived)"),
    ftype: str = Query("", alias="type", description="Filter by type (personality/agent/workflow)"),
    tag: str = Query("", description="Filter by tag"),
    q: str = Query("", description="Full-text search in name/description"),
    runtime: AgentRuntime = Depends(get_runtime),
):
    """List skills in the marketplace with optional filters."""
    from sccsos.skill_market import SkillMarket

    market = SkillMarket(runtime.db)
    skills = market.list_skills(
        status=status or None,
        ftype=ftype or None,
        tag=tag or None,
        query=q or None,
    )
    return [
        {
            "name": s.name,
            "version": s.version,
            "type": s.type,
            "description": s.description[:200],
            "author": s.author,
            "tags": s.tags,
            "status": s.status,
            "source_url": s.source_url,
        }
        for s in skills
    ]


@router.post("/skills", status_code=201)
def publish_skill(
    name: str = Query(..., description="Skill name"),
    ftype: str = Query("personality", alias="type", pattern="^(personality|agent|workflow)$"),
    author: str = Query("", description="Author name"),
    content: str = Query("", description="YAML content (inline)"),
    tags: str = Query("", description="Comma-separated tags"),
    auto_approve: bool = Query(False, description="Skip review if True"),
    runtime: AgentRuntime = Depends(get_runtime),
):
    """Publish a new skill to the marketplace."""
    from sccsos.skill_market import SkillMarket, SkillEntry

    market = SkillMarket(runtime.db)

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    entry = market.create_skill(
        name=name,
        ftype=ftype,
        author=author,
        content=content,
        tags=tag_list,
        auto_approve=auto_approve,
    )
    return {
        "name": entry.name,
        "version": entry.version,
        "type": entry.type,
        "status": entry.status,
        "author": entry.author,
    }


@router.get("/skills/installed")
def list_installed(runtime: AgentRuntime = Depends(get_runtime)):
    """List all installed skills."""
    from sccsos.skill_market import SkillMarket

    market = SkillMarket(runtime.db)
    installed = market.list_installed()
    return [
        {
            "name": s.name,
            "version": s.version,
            "type": s.type,
            "installed_at": s.installed_at,
        }
        for s in installed
    ]


@router.post("/skills/{name}/install")
def install_skill(
    name: str,
    version: str = Query("", description="Version (latest if empty)"),
    target_dir: str = Query(".", description="Target project directory"),
    runtime: AgentRuntime = Depends(get_runtime),
):
    """Install a published skill into the local project."""
    from sccsos.skill_market import SkillMarket

    market = SkillMarket(runtime.db)
    try:
        path = market.install(
            name,
            version=version or None,
            target_dir=target_dir,
        )
        return {"status": "installed", "name": name, "path": path}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/skills/installed/{name}")
def remove_installed_skill(name: str, runtime: AgentRuntime = Depends(get_runtime)):
    """Remove an installed skill record (does not delete the file)."""
    from sccsos.skill_market import SkillMarket

    market = SkillMarket(runtime.db)
    market.remove(name)
    return {"status": "removed", "name": name}


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
                  runtime: AgentRuntime = Depends(get_runtime),
                  _: None = Depends(require_permission(P.SKILLS_APPROVE))):
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
                 runtime: AgentRuntime = Depends(get_runtime),
                 _: None = Depends(require_permission(P.SKILLS_APPROVE))):
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


# ── Review Comments ────────────────────────────────────────────────


@router.post("/skills/{name}/comments")
def add_review_comment(
    name: str,
    comment: str = Query(..., min_length=1, description="Comment text"),
    reviewer: str = Query("", description="Who is commenting"),
    version: str = Query("1.0"),
    parent_id: int = Query(0, ge=0, description="Reply to existing comment"),
    runtime: AgentRuntime = Depends(get_runtime),
):
    """Add a review comment to a skill submission."""
    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)
    c = mgr.add_comment(name, reviewer=reviewer, comment=comment,
                        version=version, parent_id=parent_id)
    if not c:
        raise HTTPException(status_code=404,
                            detail=f"Skill '{name}' v{version} not found")
    return {
        "id": c.id,
        "skill_name": c.skill_name,
        "version": c.skill_version,
        "reviewer": c.reviewer,
        "comment": c.comment,
        "parent_id": c.parent_id,
        "created_at": c.created_at,
    }


@router.get("/skills/{name}/comments")
def list_review_comments(
    name: str,
    version: str = Query("1.0"),
    runtime: AgentRuntime = Depends(get_runtime),
):
    """List all review comments for a skill, threaded."""
    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)
    comments = mgr.list_comments(name, version=version)
    return [
        {
            "id": c.id,
            "reviewer": c.reviewer,
            "comment": c.comment,
            "parent_id": c.parent_id,
            "created_at": c.created_at,
        }
        for c in comments
    ]


# ── Review History ─────────────────────────────────────────────────


@router.get("/skills/{name}/history")
def get_review_history(
    name: str,
    version: str = Query("1.0"),
    runtime: AgentRuntime = Depends(get_runtime),
):
    """Get the full review audit trail for a skill."""
    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)
    history = mgr.get_history(name, version=version)
    return [
        {
            "id": h.id,
            "action": h.action,
            "reviewer": h.reviewer,
            "old_status": h.old_status,
            "new_status": h.new_status,
            "detail": h.detail,
            "created_at": h.created_at,
        }
        for h in history
    ]


# ── Version Diff ────────────────────────────────────────────────────


@router.get("/skills/{name}/diff")
def skill_version_diff(
    name: str,
    old_version: str = Query(..., description="Older version"),
    new_version: str = Query(..., description="Newer version"),
    runtime: AgentRuntime = Depends(get_runtime),
):
    """Compare two versions of a skill."""
    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)
    diff = mgr.version_diff(name, old_version, new_version)
    if not diff:
        raise HTTPException(
            status_code=404,
            detail=f"Skill '{name}' versions {old_version} vs {new_version} not found",
        )
    return {
        "old_version": diff.old_version,
        "new_version": diff.new_version,
        "fields_changed": diff.fields_changed,
        "content_diff": diff.content_diff,
    }


# ── Skill Ratings ──────────────────────────────────────────────────


@router.post("/skills/{name}/rate")
def rate_skill(
    name: str,
    score: int = Query(..., ge=1, le=5, description="Star rating (1-5)"),
    user_id: str = Query(..., min_length=1, description="Who is rating"),
    comment: str = Query("", description="Optional review comment"),
    version: str = Query("1.0"),
    runtime: AgentRuntime = Depends(get_runtime),
):
    """Rate a skill (1-5 stars). Re-rates if already rated by same user."""
    from sccsos.skill_rating import SkillRatingManager

    mgr = SkillRatingManager(runtime.db)
    rating = mgr.rate(name, user_id=user_id, score=score,
                      comment=comment, version=version)
    if not rating:
        raise HTTPException(status_code=404,
                            detail=f"Skill '{name}' v{version} not found")
    return {
        "skill_name": rating.skill_name,
        "version": rating.skill_version,
        "user_id": rating.user_id,
        "score": rating.score,
        "comment": rating.comment,
    }


@router.get("/skills/{name}/rating")
def get_skill_rating(
    name: str,
    version: str = Query("1.0"),
    runtime: AgentRuntime = Depends(get_runtime),
):
    """Get aggregated rating statistics for a skill."""
    from sccsos.skill_rating import SkillRatingManager

    mgr = SkillRatingManager(runtime.db)
    stats = mgr.get_rating(name, version=version)
    if not stats:
        return {
            "skill_name": name,
            "version": version,
            "avg_score": 0.0,
            "total_ratings": 0,
            "distribution": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
        }
    return {
        "skill_name": stats.skill_name,
        "version": stats.skill_version,
        "avg_score": stats.avg_score,
        "total_ratings": stats.total_ratings,
        "distribution": stats.distribution,
    }


@router.get("/skills/{name}/user-rating")
def get_user_skill_rating(
    name: str,
    user_id: str = Query(..., min_length=1),
    version: str = Query("1.0"),
    runtime: AgentRuntime = Depends(get_runtime),
):
    """Get a specific user's rating for a skill."""
    from sccsos.skill_rating import SkillRatingManager

    mgr = SkillRatingManager(runtime.db)
    rating = mgr.get_user_rating(name, user_id, version=version)
    if not rating:
        return {"score": 0, "comment": ""}
    return {
        "score": rating.score,
        "comment": rating.comment,
        "created_at": rating.created_at,
    }


@router.get("/skills/ratings/top")
def get_top_rated_skills(
    limit: int = Query(10, ge=1, le=100),
    min_ratings: int = Query(1, ge=1),
    runtime: AgentRuntime = Depends(get_runtime),
):
    """Get top-rated skills by average score."""
    from sccsos.skill_rating import SkillRatingManager

    mgr = SkillRatingManager(runtime.db)
    top = mgr.get_top_rated(limit=limit, min_ratings=min_ratings)
    return [
        {
            "name": s.name,
            "version": s.version,
            "type": s.type,
            "description": s.description[:200],
            "author": s.author,
            "tags": s.tags,
            "category": s.category,
            "avg_score": s.avg_score,
            "total_ratings": s.total_ratings,
            "install_count": s.install_count,
        }
        for s in top
    ]


@router.get("/skills/popular")
def get_popular_skills(
    limit: int = Query(10, ge=1, le=100),
    runtime: AgentRuntime = Depends(get_runtime),
):
    """Get popular skills (weighted by rating + install count)."""
    from sccsos.skill_rating import SkillRatingManager

    mgr = SkillRatingManager(runtime.db)
    popular = mgr.get_popular(limit=limit)
    return [
        {
            "name": s.name,
            "version": s.version,
            "type": s.type,
            "description": s.description[:200],
            "author": s.author,
            "tags": s.tags,
            "category": s.category,
            "avg_score": s.avg_score,
            "total_ratings": s.total_ratings,
            "install_count": s.install_count,
        }
        for s in popular
    ]


@router.get("/skills/most-installed")
def get_most_installed_skills(
    limit: int = Query(10, ge=1, le=100),
    runtime: AgentRuntime = Depends(get_runtime),
):
    """Get most-installed skills."""
    from sccsos.skill_rating import SkillRatingManager

    mgr = SkillRatingManager(runtime.db)
    installed = mgr.get_most_installed(limit=limit)
    return [
        {
            "name": s.name,
            "version": s.version,
            "type": s.type,
            "description": s.description[:200],
            "author": s.author,
            "tags": s.tags,
            "category": s.category,
            "install_count": s.install_count,
        }
        for s in installed
    ]


@router.get("/skills/categories")
def list_skill_categories(runtime: AgentRuntime = Depends(get_runtime)):
    """List all skill categories."""
    from sccsos.skill_rating import SkillRatingManager

    mgr = SkillRatingManager(runtime.db)
    return {"categories": mgr.list_categories()}


@router.get("/skills/categories/{category}")
def get_skills_by_category(
    category: str,
    runtime: AgentRuntime = Depends(get_runtime),
):
    """Get all skills in a category."""
    from sccsos.skill_rating import SkillRatingManager

    mgr = SkillRatingManager(runtime.db)
    skills = mgr.get_skills_by_category(category)
    return [
        {
            "name": s.name,
            "version": s.version,
            "type": s.type,
            "description": s.description[:200],
            "author": s.author,
            "tags": s.tags,
            "category": s.category,
            "avg_score": s.avg_score,
            "total_ratings": s.total_ratings,
            "install_count": s.install_count,
        }
        for s in skills
    ]
