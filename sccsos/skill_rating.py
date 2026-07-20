"""Skill Rating — star ratings (1-5) and usage statistics for skills.

Provides:
  - Rate a skill (1-5 stars with optional comment)
  - Get average rating + distribution
  - Increment install count tracking
  - Top-rated / most-installed skill queries
  - Category-based grouping

Usage:
    mgr = SkillRatingManager(db)

    # Rate a skill
    mgr.rate("agent-architect", user_id="user-1", score=4)

    # Get average rating
    stats = mgr.get_rating("agent-architect")
    # -> {"avg": 4.2, "count": 5, "distribution": {1:0, 2:0, 3:1, 4:3, 5:1}}

    # Track install
    mgr.increment_install_count("agent-architect")

    # Top rated
    top = mgr.get_top_rated(limit=10)

    # Most installed
    popular = mgr.get_most_installed(limit=10)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("sccsos.skill.rating")


@dataclass
class SkillRating:
    """A single rating for a skill."""
    id: int = 0
    skill_name: str = ""
    skill_version: str = "1.0"
    user_id: str = ""
    score: int = 0
    comment: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class SkillRatingStats:
    """Aggregated rating statistics for a skill."""
    skill_name: str = ""
    skill_version: str = "1.0"
    avg_score: float = 0.0
    total_ratings: int = 0
    distribution: dict[int, int] | None = None

    def __post_init__(self):
        if self.distribution is None:
            self.distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}


@dataclass
class SkillPopularity:
    """Popularity info for a skill."""
    name: str = ""
    version: str = ""
    type: str = ""
    description: str = ""
    author: str = ""
    tags: list[str] | None = None
    category: str = ""
    avg_score: float = 0.0
    total_ratings: int = 0
    install_count: int = 0
    status: str = ""

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


class SkillRatingManager:
    """Manages skill ratings and usage statistics.

    Args:
        db: Database instance with skill_market, skill_ratings tables.
    """

    VALID_SCORES = (1, 2, 3, 4, 5)

    def __init__(self, db):
        self._db = db

    # ── Rating API ─────────────────────────────────────────────────

    def rate(self, skill_name: str, user_id: str, score: int,
             comment: str = "", version: str = "1.0") -> Optional[SkillRating]:
        """Rate a skill (1-5 stars).

        If the user has already rated this skill version, the rating
        is updated. Otherwise a new rating is created.

        Args:
            skill_name: Name of the skill.
            user_id: Who is rating.
            score: Star rating (1-5).
            comment: Optional comment.
            version: Skill version.

        Returns:
            The created/updated SkillRating, or None if skill not found.
        """
        if score not in self.VALID_SCORES:
            logger.warning("Invalid score %d (must be 1-5)", score)
            return None

        # Verify skill exists
        existing = self._db.fetchone(
            "SELECT id FROM skill_market WHERE name = ? AND version = ?",
            (skill_name, version),
        )
        if not existing:
            logger.warning("Skill '%s' v%s not found", skill_name, version)
            return None

        now = datetime.now(timezone.utc).isoformat()

        # Upsert: INSERT OR REPLACE
        self._db.execute(
            "INSERT OR REPLACE INTO skill_ratings "
            "(skill_name, skill_version, user_id, score, comment, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, "
            "  COALESCE((SELECT created_at FROM skill_ratings "
            "    WHERE skill_name = ? AND skill_version = ? AND user_id = ?), ?), "
            "  ?)",
            (skill_name, version, user_id, score, comment,
             skill_name, version, user_id, now,
             now),
        )
        self._db.commit()

        # Emit EventBus event
        try:
            from sccsos.core.event_bus import get_bus
            get_bus().emit("skill.rated", skill_name=skill_name,
                          version=version, user_id=user_id, score=score)
        except Exception:
            pass

        row = self._db.fetchone(
            "SELECT * FROM skill_ratings WHERE skill_name = ? AND skill_version = ? AND user_id = ?",
            (skill_name, version, user_id),
        )
        if not row:
            return None
        return self._row_to_rating(dict(row))

    def get_user_rating(self, skill_name: str, user_id: str,
                        version: str = "1.0") -> Optional[SkillRating]:
        """Get a specific user's rating for a skill.

        Returns None if the user hasn't rated this skill.
        """
        row = self._db.fetchone(
            "SELECT * FROM skill_ratings "
            "WHERE skill_name = ? AND skill_version = ? AND user_id = ?",
            (skill_name, version, user_id),
        )
        return self._row_to_rating(dict(row)) if row else None

    def get_rating(self, skill_name: str,
                   version: str = "1.0") -> Optional[SkillRatingStats]:
        """Get aggregated rating statistics for a skill.

        Returns:
            SkillRatingStats with avg_score, total_ratings, distribution,
            or None if skill has no ratings.
        """
        rows = self._db.fetchall(
            "SELECT score, COUNT(*) as cnt FROM skill_ratings "
            "WHERE skill_name = ? AND skill_version = ? "
            "GROUP BY score ORDER BY score",
            (skill_name, version),
        )
        if not rows:
            return SkillRatingStats(
                skill_name=skill_name,
                skill_version=version,
            )

        total = 0
        score_sum = 0
        dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for r in rows:
            s = int(r["score"])
            c = int(r["cnt"])
            dist[s] = c
            total += c
            score_sum += s * c

        return SkillRatingStats(
            skill_name=skill_name,
            skill_version=version,
            avg_score=round(score_sum / total, 2) if total > 0 else 0.0,
            total_ratings=total,
            distribution=dist,
        )

    def list_ratings(self, skill_name: str,
                     version: str = "1.0") -> list[SkillRating]:
        """List all ratings for a skill."""
        rows = self._db.fetchall(
            "SELECT * FROM skill_ratings "
            "WHERE skill_name = ? AND skill_version = ? "
            "ORDER BY created_at DESC",
            (skill_name, version),
        )
        return [self._row_to_rating(dict(r)) for r in rows]

    # ── Install tracking ──────────────────────────────────────────

    def increment_install_count(self, skill_name: str,
                                version: str = "1.0") -> bool:
        """Increment the install count for a skill.

        Called when a skill is installed via SkillMarket.install().

        Returns:
            True if updated, False if skill not found.
        """
        existing = self._db.fetchone(
            "SELECT id FROM skill_market WHERE name = ? AND version = ?",
            (skill_name, version),
        )
        if not existing:
            return False

        self._db.execute(
            "UPDATE skill_market SET install_count = IFNULL(install_count, 0) + 1, "
            "updated_at = ? WHERE name = ? AND version = ?",
            (datetime.now(timezone.utc).isoformat(), skill_name, version),
        )
        self._db.commit()
        return True

    def get_install_count(self, skill_name: str,
                          version: str = "1.0") -> int:
        """Get the install count for a skill."""
        row = self._db.fetchone(
            "SELECT install_count FROM skill_market WHERE name = ? AND version = ?",
            (skill_name, version),
        )
        return int(row["install_count"]) if row and row["install_count"] else 0

    # ── Rankings ──────────────────────────────────────────────────

    def get_top_rated(self, limit: int = 10,
                      min_ratings: int = 1) -> list[SkillPopularity]:
        """Get top-rated skills by average score.

        Args:
            limit: Max results.
            min_ratings: Minimum number of ratings to be considered.

        Returns:
            List of SkillPopularity sorted by avg_score descending.
        """
        rows = self._db.fetchall(
            """SELECT sm.name, sm.version, sm.type, sm.description,
                      sm.author, sm.tags, sm.category, sm.status,
                      sm.install_count,
                      AVG(sr.score) as avg_score,
                      COUNT(sr.id) as total_ratings
               FROM skill_ratings sr
               JOIN skill_market sm ON sm.name = sr.skill_name
                   AND sm.version = sr.skill_version
               GROUP BY sr.skill_name, sr.skill_version
               HAVING total_ratings >= ?
               ORDER BY avg_score DESC, total_ratings DESC
               LIMIT ?""",
            (min_ratings, limit),
        )
        return [self._row_to_popularity(r) for r in rows]

    def get_most_installed(self, limit: int = 10) -> list[SkillPopularity]:
        """Get most-installed skills.

        Returns:
            List of SkillPopularity sorted by install_count descending.
        """
        rows = self._db.fetchall(
            """SELECT name, version, type, description, author, tags,
                      category, status, install_count,
                      0.0 as avg_score, 0 as total_ratings
               FROM skill_market
               WHERE install_count > 0
               ORDER BY install_count DESC
               LIMIT ?""",
            (limit,),
        )
        return [self._row_to_popularity(r) for r in rows]

    def get_popular(self, limit: int = 10) -> list[SkillPopularity]:
        """Get popular skills combining ratings and installs.

        Uses a weighted score: (avg_rating * 10 + install_count) * status_weight.
        Published/approved skills get weight 1.0, drafts 0.3.

        Returns:
            List of SkillPopularity sorted by weighted popularity.
        """
        rows = self._db.fetchall(
            """SELECT sm.name, sm.version, sm.type, sm.description,
                      sm.author, sm.tags, sm.category, sm.status,
                      sm.install_count,
                      COALESCE(AVG(sr.score), 0) as avg_score,
                      COUNT(sr.id) as total_ratings
               FROM skill_market sm
               LEFT JOIN skill_ratings sr
                   ON sr.skill_name = sm.name AND sr.skill_version = sm.version
               GROUP BY sm.name, sm.version
               HAVING total_ratings > 0 OR sm.install_count > 0
               ORDER BY
                   CASE sm.status
                       WHEN 'published' THEN 1.0
                       WHEN 'approved' THEN 1.0
                       ELSE 0.3
                   END *
                   (COALESCE(AVG(sr.score), 0) * 10 + sm.install_count) DESC
               LIMIT ?""",
            (limit,),
        )
        return [self._row_to_popularity(r) for r in rows]

    # ── Categories ────────────────────────────────────────────────

    def list_categories(self) -> list[str]:
        """List all unique categories used in skill_market."""
        rows = self._db.fetchall(
            "SELECT DISTINCT category FROM skill_market "
            "WHERE category IS NOT NULL AND category != '' "
            "ORDER BY category",
        )
        return [r["category"] for r in rows]

    def get_skills_by_category(self, category: str) -> list[SkillPopularity]:
        """Get all skills in a category with rating stats."""
        rows = self._db.fetchall(
            """SELECT sm.name, sm.version, sm.type, sm.description,
                      sm.author, sm.tags, sm.category, sm.status,
                      sm.install_count,
                      COALESCE(AVG(sr.score), 0) as avg_score,
                      COUNT(sr.id) as total_ratings
               FROM skill_market sm
               LEFT JOIN skill_ratings sr
                   ON sr.skill_name = sm.name AND sr.skill_version = sm.version
               WHERE sm.category = ?
               GROUP BY sm.name, sm.version
               ORDER BY avg_score DESC""",
            (category,),
        )
        return [self._row_to_popularity(r) for r in rows]

    # ── Internal ──────────────────────────────────────────────────

    def _row_to_rating(self, row: dict) -> SkillRating:
        return SkillRating(
            id=row.get("id", 0),
            skill_name=row.get("skill_name", ""),
            skill_version=row.get("skill_version", "1.0"),
            user_id=row.get("user_id", ""),
            score=row.get("score", 0),
            comment=row.get("comment", ""),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
        )

    def _row_to_popularity(self, row) -> SkillPopularity:
        d = dict(row)
        import json
        return SkillPopularity(
            name=d.get("name", ""),
            version=d.get("version", "1.0"),
            type=d.get("type", ""),
            description=d.get("description", ""),
            author=d.get("author", ""),
            tags=json.loads(d.get("tags", "[]")),
            category=d.get("category", ""),
            avg_score=round(float(d.get("avg_score", 0)), 2),
            total_ratings=int(d.get("total_ratings", 0)),
            install_count=int(d.get("install_count", 0)),
            status=d.get("status", ""),
        )
