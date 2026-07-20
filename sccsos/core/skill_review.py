"""Skill Review Manager — approval workflow for skill/personality submissions.

Manages the lifecycle of skills submitted to the skill market through
a review pipeline: draft → pending_review → approved (or rejected).

Emits EventBus events on status changes:
- skill.submitted   → {name, version}
- skill.approved    → {name, version, reviewer}
- skill.rejected    → {name, version, reason}
- skill.reset       → {name, version}

Usage:
    mgr = SkillReviewManager(db)

    # Submit a skill for review
    mgr.submit_for_review("agent-architect")

    # List pending reviews
    pending = mgr.list_pending()

    # Validate a skill before approving
    mgr.validate("agent-architect")

    # Approve or reject
    mgr.approve("agent-architect", reviewer="architect")
    mgr.reject("agent-architect", reason="Missing system_prompt field")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from sccsos.core.db import Database

logger = logging.getLogger("sccsos.skill.review")

# EventBus for status change notifications
_SKILL_EVENT_PREFIX = "skill."


def _emit_skill_event(event: str, **data) -> None:
    """Emit a skill lifecycle event on the EventBus (best-effort)."""
    try:
        from sccsos.core.event_bus import get_bus
        get_bus().emit(f"{_SKILL_EVENT_PREFIX}{event}", **data)
    except Exception:
        logger.debug("Failed to emit skill event '%s'", event, exc_info=True)


@dataclass
class SkillReview:
    """A skill submission with review status."""
    name: str
    version: str
    type: str
    description: str
    author: str
    tags: list[str] = field(default_factory=list)
    filename: str = ""
    content: str = ""  # Full skill content (YAML)
    status: str = "draft"  # draft, pending_review, approved, rejected
    review_notes: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ValidationResult:
    """Result of skill content validation."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SkillReviewManager:
    """Manages the skill review/approval pipeline.

    Args:
        db: Database instance for persistence.
    """

    VALID_STATUSES = ("draft", "pending_review", "approved", "rejected")
    REQUIRED_FIELDS = ("name", "system_prompt")

    def __init__(self, db: Database):
        self._db = db

    # ── Lifecycle API ───────────────────────────────────────────

    def submit_for_review(self, name: str, version: str = "1.0") -> bool:
        """Submit a skill for review (draft → pending_review).

        Returns:
            True if submitted, False if not found or already in review.
        """
        current = self._get_skill(name, version)
        if not current:
            logger.warning("Skill '%s' v%s not found", name, version)
            return False
        if current["status"] not in ("draft",):
            logger.info(
                "Skill '%s' already in status '%s'", name, current["status"]
            )
            return False

        self._db.execute(
            "UPDATE skill_market SET status = 'pending_review', "
            "updated_at = ? WHERE name = ? AND version = ?",
            (datetime.now(timezone.utc).isoformat(), name, version),
        )
        self._db.commit()
        _emit_skill_event("submitted", name=name, version=version)
        logger.info("Skill '%s' submitted for review", name)
        return True

    def approve(self, name: str, version: str = "1.0",
                reviewer: str = "",
                notes: str = "") -> bool:
        """Approve a skill (pending_review → approved).

        Performs auto-validation before approving.
        """
        validation = self.validate(name, version)
        if not validation.valid:
            errors = "; ".join(validation.errors)
            logger.warning(
                "Skill '%s' validation failed: %s", name, errors
            )
            return False

        now = datetime.now(timezone.utc).isoformat()
        notes_str = f"Approved by {reviewer}: {notes}" if notes else f"Approved by {reviewer}"
        self._db.execute(
            "UPDATE skill_market SET status = 'approved', review_notes = ?, "
            "updated_at = ? WHERE name = ? AND version = ?",
            (notes_str, now, name, version),
        )
        self._db.commit()

        # Record as installed
        current = self._get_skill(name, version)
        if current:
            self._db.execute(
                "INSERT OR IGNORE INTO installed_skills (name, version, type) "
                "VALUES (?, ?, ?)",
                (name, version, current.get("type", "personality")),
            )
            self._db.commit()

        _emit_skill_event("approved", name=name, version=version,
                          reviewer=reviewer)
        logger.info("Skill '%s' approved by '%s'", name, reviewer or "system")
        return True

    def reject(self, name: str, version: str = "1.0",
               reason: str = "") -> bool:
        """Reject a skill (pending_review → rejected).

        Args:
            reason: Required rejection reason.
        """
        if not reason:
            logger.warning("Rejection reason required for '%s'", name)
            return False

        current = self._get_skill(name, version)
        if not current:
            logger.warning("Skill '%s' v%s not found", name, version)
            return False
        if current["status"] != "pending_review":
            logger.info(
                "Skill '%s' is in status '%s', cannot reject",
                name, current["status"],
            )
            return False

        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "UPDATE skill_market SET status = 'rejected', review_notes = ?, "
            "updated_at = ? WHERE name = ? AND version = ?",
            (f"Rejected: {reason}", now, name, version),
        )
        self._db.commit()
        _emit_skill_event("rejected", name=name, version=version, reason=reason)
        logger.info("Skill '%s' rejected: %s", name, reason)
        return True

    def reset_to_draft(self, name: str, version: str = "1.0") -> bool:
        """Reset a rejected skill back to draft for re-submission."""
        current = self._get_skill(name, version)
        if not current or current["status"] != "rejected":
            return False

        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "UPDATE skill_market SET status = 'draft', review_notes = '', "
            "updated_at = ? WHERE name = ? AND version = ?",
            (now, name, version),
        )
        self._db.commit()
        _emit_skill_event("reset", name=name, version=version)
        return True

    # ── Validation ─────────────────────────────────────────────

    def validate(self, name: str, version: str = "1.0") -> ValidationResult:
        """Validate a skill's content for safety and completeness.

        Checks:
        - YAML parseability
        - Required fields present
        - System prompt safety (basic injection patterns)
        """
        result = ValidationResult(valid=True, errors=[], warnings=[])

        current = self._get_skill(name, version)
        if not current:
            result.valid = False
            result.errors.append(f"Skill '{name}' v{version} not found")
            return result

        # Check content
        content = current.get("content", "")
        if not content.strip():
            result.valid = False
            result.errors.append("Skill content is empty")
            return result

        # YAML validation
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            result.valid = False
            result.errors.append(f"YAML parse error: {e}")
            return result

        if not isinstance(data, dict):
            result.valid = False
            result.errors.append("Content is not a valid YAML mapping")
            return result

        # Required fields
        for field_name in self.REQUIRED_FIELDS:
            if field_name not in data:
                result.valid = False
                result.errors.append(f"Missing required field: '{field_name}'")

        # Safety checks — detect potentially dangerous patterns
        system_prompt = str(data.get("system_prompt", ""))
        dangerous = [
            ("ignore all previous instructions", "Prompt injection risk: override instruction"),
            ("you are now", "Prompt injection risk: role override"),
            ("system override", "Prompt injection risk: system override pattern"),
            ("<|im_start|>", "Prompt injection risk: token injection"),
        ]
        for pattern, warning in dangerous:
            if pattern.lower() in system_prompt.lower():
                result.warnings.append(warning)

        return result

    # ── Queries ────────────────────────────────────────────────

    def list_pending(self) -> list[SkillReview]:
        """List all skills pending review."""
        return self._list_by_status("pending_review")

    def list_drafts(self) -> list[SkillReview]:
        """List all draft skills."""
        return self._list_by_status("draft")

    def list_approved(self) -> list[SkillReview]:
        """List all approved skills."""
        return self._list_by_status("approved")

    def list_rejected(self) -> list[SkillReview]:
        """List all rejected skills."""
        return self._list_by_status("rejected")

    def list_all(self, status: Optional[str] = None) -> list[SkillReview]:
        """List all skills, optionally filtered by status."""
        if status:
            return self._list_by_status(status)
        return self._get_all_reviews()

    def get_review(self, name: str,
                   version: str = "1.0") -> Optional[SkillReview]:
        """Get the review status for a specific skill version."""
        row = self._db.fetchone(
            "SELECT * FROM skill_market WHERE name = ? AND version = ?",
            (name, version),
        )
        if not row:
            return None
        return self._row_to_review(dict(row))

    # ── Internal ───────────────────────────────────────────────

    def _get_skill(self, name: str, version: str) -> Optional[dict]:
        row = self._db.fetchone(
            "SELECT * FROM skill_market WHERE name = ? AND version = ?",
            (name, version),
        )
        return dict(row) if row else None

    def _list_by_status(self, status: str) -> list[SkillReview]:
        rows = self._db.fetchall(
            "SELECT * FROM skill_market WHERE status = ? ORDER BY updated_at DESC",
            (status,),
        )
        return [self._row_to_review(dict(r)) for r in rows]

    def _get_all_reviews(self) -> list[SkillReview]:
        rows = self._db.fetchall(
            "SELECT * FROM skill_market ORDER BY updated_at DESC"
        )
        return [self._row_to_review(dict(r)) for r in rows]

    def _row_to_review(self, r: dict) -> SkillReview:
        tags = []
        raw_tags = r.get("tags", "[]")
        if isinstance(raw_tags, str):
            try:
                tags = json.loads(raw_tags)
            except (json.JSONDecodeError, TypeError):
                tags = []
        return SkillReview(
            name=r.get("name", ""),
            version=r.get("version", "1.0"),
            type=r.get("type", "personality"),
            description=r.get("description", ""),
            author=r.get("author", ""),
            tags=tags,
            filename=r.get("filename", ""),
            content=r.get("content", ""),
            status=r.get("status", "draft"),
            review_notes=r.get("review_notes", "") or "",
            created_at=r.get("created_at", ""),
            updated_at=r.get("updated_at", ""),
        )
