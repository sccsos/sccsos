"""Personality Version Manager — version history and rollback support.

Tracks changes to personality YAML files by storing versioned snapshots
in the ``personality_versions`` table. Each time a personality file is
modified via CLI, a new version snapshot is recorded.

Usage:
    mgr = PersonalityVersionManager(db, personalities_dir)
    mgr.save_version("agent-architect", "Updated system prompt")  # v1.1
    mgr.list_versions("agent-architect")
    mgr.get_version("agent-architect", "1.0")
    current = mgr.get_current("agent-architect")
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from sccsos.core.database import Database


@dataclass
class PersonalityVersion:
    """A single version snapshot of a personality."""
    personality_name: str
    version: str
    content: str
    change_log: str = ""
    created_at: str = ""


class PersonalityVersionManager:
    """Manages versioned snapshots of personality definitions."""

    def __init__(self, db: Database, personalities_dir: Optional[str | Path] = None):
        self._db = db
        self._personalities_dir = Path(personalities_dir) if personalities_dir else None

    # ── Public API ───────────────────────────────────────────────

    def save_version(self, personality_name: str,
                     change_log: str = "") -> str:
        """Snapshot the current file content as a new version.

        Increments the version number based on existing versions:
        no versions → "1.0", existing "1.0" → "1.1", etc.

        Args:
            personality_name: Name of the personality (matches YAML filename).
            change_log: Description of what changed.

        Returns:
            The new version string (e.g. ``"1.1"``).
        """
        content = self._read_personality_file(personality_name)
        versions = self._get_existing_versions(personality_name)
        next_ver = self._next_version(versions)

        self._db.execute(
            """INSERT OR REPLACE INTO personality_versions
               (personality_name, version, content, change_log, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (personality_name, next_ver, content, change_log,
             datetime.now(timezone.utc).isoformat()),
        )
        self._db.commit()
        return next_ver

    def list_versions(self, personality_name: str) -> list[PersonalityVersion]:
        """List all versioned snapshots for a personality, newest first."""
        rows = self._db.fetchall(
            """SELECT personality_name, version, content, change_log, created_at
               FROM personality_versions
               WHERE personality_name = ?
               ORDER BY created_at DESC""",
            (personality_name,),
        )
        return [
            PersonalityVersion(
                personality_name=r["personality_name"],
                version=r["version"],
                content=r["content"],
                change_log=r.get("change_log", ""),
                created_at=r.get("created_at", ""),
            )
            for r in rows
        ]

    def get_version(self, personality_name: str,
                    version: str) -> Optional[PersonalityVersion]:
        """Get a specific version."""
        row = self._db.fetchone(
            """SELECT personality_name, version, content, change_log, created_at
               FROM personality_versions
               WHERE personality_name = ? AND version = ?""",
            (personality_name, version),
        )
        if not row:
            return None
        r = dict(row)
        return PersonalityVersion(
            personality_name=r["personality_name"],
            version=r["version"],
            content=r["content"],
            change_log=r.get("change_log", ""),
            created_at=r.get("created_at", ""),
        )

    def get_current(self, personality_name: str) -> Optional[str]:
        """Get the content of the current (latest) version.

        Returns the YAML content string, or None if no versions exist.
        """
        row = self._db.fetchone(
            """SELECT content FROM personality_versions
               WHERE personality_name = ?
               ORDER BY created_at DESC LIMIT 1""",
            (personality_name,),
        )
        return row[0] if row else None

    def list_all_personalities(self) -> list[str]:
        """List all personality names that have version history."""
        rows = self._db.fetchall(
            """SELECT DISTINCT personality_name
               FROM personality_versions
               ORDER BY personality_name"""
        )
        return [r[0] for r in rows]

    # ── Internal ─────────────────────────────────────────────────

    def _read_personality_file(self, name: str) -> str:
        """Read the current YAML file for a personality.

        Raises FileNotFoundError if the file doesn't exist.
        """
        if self._personalities_dir is None:
            raise FileNotFoundError(
                f"Personalities directory not configured"
            )

        # Try exact name, then name.yaml, then name.yml
        for fname in (name, f"{name}.yaml", f"{name}.yml"):
            fpath = self._personalities_dir / fname
            if fpath.exists():
                return fpath.read_text(encoding="utf-8")

        # Try case-insensitive match
        if self._personalities_dir.exists():
            for fpath in self._personalities_dir.iterdir():
                if fpath.stem.lower() == name.lower() and fpath.suffix in (".yaml", ".yml"):
                    return fpath.read_text(encoding="utf-8")

        raise FileNotFoundError(
            f"Personality file for '{name}' not found in {self._personalities_dir}"
        )

    def _get_existing_versions(self, name: str) -> list[str]:
        """Get sorted list of existing version strings."""
        rows = self._db.fetchall(
            """SELECT version FROM personality_versions
               WHERE personality_name = ?
               ORDER BY version""",
            (name,),
        )
        return [r[0] for r in rows]

    def _next_version(self, existing: list[str]) -> str:
        """Compute next version number (e.g. 1.0 → 1.1)."""
        if not existing:
            return "1.0"
        try:
            last = float(existing[-1])
            return f"{last + 0.1:.1f}"
        except (ValueError, IndexError):
            return "1.0"
