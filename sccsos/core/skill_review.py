"""Skill Review Manager — approval workflow for skill/personality submissions.

Manages the lifecycle of skills submitted to the skill market through
a review pipeline: draft → pending_review → approved (or rejected).

Features:
- Multi-reviewer comments (threaded)
- Review audit history trail
- Version diff comparison
- Validation (YAML, safety, required fields)

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

    # Add review comment
    mgr.add_comment("agent-architect", reviewer="senior-dev", comment="Needs license field")
    mgr.add_comment("agent-architect", reviewer="architect",
                     comment="Added license", parent_id=1)

    # Get review history
    history = mgr.get_history("agent-architect")

    # Compare versions
    diff = mgr.version_diff("agent-architect", "1.0", "1.1")
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
class ReviewComment:
    """A single review comment on a skill submission."""
    id: int = 0
    skill_name: str = ""
    skill_version: str = ""
    reviewer: str = ""
    comment: str = ""
    parent_id: int = 0
    created_at: str = ""


@dataclass
class ReviewHistoryEntry:
    """A single entry in the review audit trail."""
    id: int = 0
    skill_name: str = ""
    skill_version: str = ""
    action: str = ""
    reviewer: str = ""
    old_status: str = ""
    new_status: str = ""
    detail: str = ""
    created_at: str = ""


@dataclass
class VersionDiff:
    """Result of comparing two skill versions."""
    old_version: str = ""
    new_version: str = ""
    fields_changed: list[dict] = field(default_factory=list)
    content_diff: str = ""


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

        old_status = current["status"]
        self._db.execute(
            "UPDATE skill_market SET status = 'pending_review', "
            "updated_at = ? WHERE name = ? AND version = ?",
            (datetime.now(timezone.utc).isoformat(), name, version),
        )
        self._db.commit()
        self._record_history(name, version, "submit", "",
                             old_status, "pending_review")
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

        current = self._get_skill(name, version)
        old_status = current["status"] if current else ""

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

        self._record_history(name, version, "approve", reviewer,
                             old_status, "approved", notes)
        _emit_skill_event("approved", name=name, version=version,
                          reviewer=reviewer)
        logger.info("Skill '%s' approved by '%s'", name, reviewer or "system")
        return True

    def reject(self, name: str, version: str = "1.0",
               reason: str = "",
               reviewer: str = "") -> bool:
        """Reject a skill (pending_review → rejected).

        Args:
            reason: Required rejection reason.
            reviewer: Who rejected it.
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

        old_status = current["status"]
        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "UPDATE skill_market SET status = 'rejected', review_notes = ?, "
            "updated_at = ? WHERE name = ? AND version = ?",
            (f"Rejected by {reviewer}: {reason}", now, name, version),
        )
        self._db.commit()
        self._record_history(name, version, "reject", reviewer,
                             old_status, "rejected", reason)
        _emit_skill_event("rejected", name=name, version=version, reason=reason)
        logger.info("Skill '%s' rejected by '%s': %s", name, reviewer, reason)
        return True

    def reset_to_draft(self, name: str, version: str = "1.0",
                       reviewer: str = "") -> bool:
        """Reset a rejected skill back to draft for re-submission."""
        current = self._get_skill(name, version)
        if not current or current["status"] != "rejected":
            return False

        old_status = current["status"]
        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "UPDATE skill_market SET status = 'draft', review_notes = '', "
            "updated_at = ? WHERE name = ? AND version = ?",
            (now, name, version),
        )
        self._db.commit()
        self._record_history(name, version, "reset", reviewer,
                             old_status, "draft")
        _emit_skill_event("reset", name=name, version=version)
        return True

    # ── Review Comments ─────────────────────────────────────────

    def add_comment(self, name: str, reviewer: str = "",
                    comment: str = "", version: str = "1.0",
                    parent_id: int = 0) -> Optional[ReviewComment]:
        """Add a review comment to a skill submission.

        Args:
            name: Skill name.
            reviewer: Who is commenting.
            comment: Comment text.
            version: Skill version.
            parent_id: If set, reply to an existing comment (threaded).

        Returns:
            The created ReviewComment, or None if skill not found.
        """
        current = self._get_skill(name, version)
        if not current:
            logger.warning("Skill '%s' v%s not found for comment", name, version)
            return None
        if parent_id and not self._get_comment_by_id(parent_id):
            logger.warning("Parent comment %d not found", parent_id)
            return None

        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "INSERT INTO review_comments "
            "(skill_name, skill_version, reviewer, comment, parent_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, version, reviewer, comment, parent_id, now),
        )
        self._db.commit()

        row = self._db.fetchone(
            "SELECT * FROM review_comments WHERE id = last_insert_rowid()"
        )
        if not row:
            return None
        return self._row_to_comment(dict(row))

    def list_comments(self, name: str, version: str = "1.0") -> list[ReviewComment]:
        """List all comments for a skill, threaded by parent_id."""
        rows = self._db.fetchall(
            "SELECT * FROM review_comments "
            "WHERE skill_name = ? AND skill_version = ? "
            "ORDER BY parent_id ASC, id ASC",
            (name, version),
        )
        return [self._row_to_comment(dict(r)) for r in rows]

    # ── Review History ──────────────────────────────────────────

    def get_history(self, name: str, version: str = "1.0") -> list[ReviewHistoryEntry]:
        """Get full review audit trail for a skill.

        Returns chronological list of actions (submit/approve/reject/reset).
        """
        rows = self._db.fetchall(
            "SELECT * FROM review_history "
            "WHERE skill_name = ? AND skill_version = ? "
            "ORDER BY created_at DESC",
            (name, version),
        )
        return [self._row_to_history(dict(r)) for r in rows]

    # ── Version Diff ────────────────────────────────────────────

    def version_diff(self, name: str, old_version: str,
                     new_version: str) -> Optional[VersionDiff]:
        """Compare two versions of a skill and return differences.

        Args:
            name: Skill name.
            old_version: Older version to compare.
            new_version: Newer version to compare.

        Returns:
            VersionDiff with changed fields and content diff, or None.
        """
        old = self._get_skill(name, old_version)
        new = self._get_skill(name, new_version)
        if not old or not new:
            return None

        diff = VersionDiff(old_version=old_version, new_version=new_version)

        # Parse both YAML contents
        try:
            old_data = yaml.safe_load(old.get("content", "")) or {}
            new_data = yaml.safe_load(new.get("content", "")) or {}
        except yaml.YAMLError:
            # Fall back to raw string comparison
            diff.content_diff = self._str_diff(
                old.get("content", ""), new.get("content", "")
            )
            return diff

        # Compare field-by-field
        all_keys = set(list(old_data.keys()) + list(new_data.keys()))
        for key in sorted(all_keys):
            old_val = old_data.get(key)
            new_val = new_data.get(key)
            if old_val != new_val:
                diff.fields_changed.append({
                    "field": key,
                    "old": str(old_val) if old_val is not None else "",
                    "new": str(new_val) if new_val is not None else "",
                })

        # Raw content diff
        diff.content_diff = self._str_diff(
            old.get("content", ""), new.get("content", "")
        )

        return diff

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

    def _record_history(self, name: str, version: str, action: str,
                        reviewer: str, old_status: str, new_status: str,
                        detail: str = "") -> None:
        """Record a review audit trail entry."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            self._db.execute(
                "INSERT INTO review_history "
                "(skill_name, skill_version, action, reviewer, "
                "old_status, new_status, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, version, action, reviewer,
                 old_status, new_status, detail, now),
            )
            self._db.commit()
        except Exception as e:
            logger.warning("Failed to record review history: %s", e)

    def _get_comment_by_id(self, comment_id: int) -> Optional[dict]:
        row = self._db.fetchone(
            "SELECT * FROM review_comments WHERE id = ?", (comment_id,)
        )
        return dict(row) if row else None

    @staticmethod
    def _row_to_comment(r: dict) -> ReviewComment:
        return ReviewComment(
            id=r.get("id", 0),
            skill_name=r.get("skill_name", ""),
            skill_version=r.get("skill_version", "1.0"),
            reviewer=r.get("reviewer", ""),
            comment=r.get("comment", ""),
            parent_id=r.get("parent_id", 0),
            created_at=r.get("created_at", ""),
        )

    @staticmethod
    def _row_to_history(r: dict) -> ReviewHistoryEntry:
        return ReviewHistoryEntry(
            id=r.get("id", 0),
            skill_name=r.get("skill_name", ""),
            skill_version=r.get("skill_version", "1.0"),
            action=r.get("action", ""),
            reviewer=r.get("reviewer", ""),
            old_status=r.get("old_status", ""),
            new_status=r.get("new_status", ""),
            detail=r.get("detail", ""),
            created_at=r.get("created_at", ""),
        )

    @staticmethod
    def _str_diff(old: str, new: str) -> str:
        """Simple line-by-line diff between two strings.

        Returns a compact diff summary (not a full unified diff).
        """
        old_lines = old.splitlines()
        new_lines = new.splitlines()
        added = len(new_lines) - len(old_lines)
        changed = sum(
            1 for i in range(min(len(old_lines), len(new_lines)))
            if old_lines[i] != new_lines[i]
        )
        parts = []
        if changed:
            parts.append(f"{changed} lines changed")
        if added > 0:
            parts.append(f"+{added} lines added")
        elif added < 0:
            parts.append(f"{added} lines removed")
        parts.append(f"({len(old_lines)} → {len(new_lines)} lines)")
        return ", ".join(parts) if parts else "identical"
