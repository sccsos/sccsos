"""Skill Marketplace — publish, discover, and install skills.

A skill is a reusable YAML file (personality, agent definition, or workflow)
registered in the central ``skill_market`` table.  Skills can be:

- **Published** from a local file into the marketplace
- **Listed** for discovery (filterable by type, status, tags)
- **Installed** into the local project (copied to the appropriate directory)
- **Approved** to promote from draft to published status

Schema::

    skill_market (name, version, type, description, author, tags,
                  filename, content, source_url, status)

    installed_skills (name, version, type, installed_at)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class SkillEntry:
    """A skill registered in the marketplace."""
    name: str
    version: str = "1.0"
    type: str = "personality"  # personality | agent | workflow
    description: str = ""
    author: str = ""
    tags: list[str] = field(default_factory=list)
    filename: str = ""
    content: str = ""
    source_url: str = ""
    status: str = "draft"  # draft | published | archived


@dataclass
class InstalledSkill:
    """A skill installed into the local project."""
    name: str
    version: str
    type: str
    installed_at: str = ""


class SkillMarket:
    """Skill marketplace operations backed by the database."""

    def __init__(self, db):
        self._db = db

    # ── Publish ─────────────────────────────────────────────────────

    def create_skill(self, *, name: str, ftype: str = "personality",
                     author: str = "", content: str = "",
                     tags: Optional[list[str]] = None,
                     auto_approve: bool = False) -> SkillEntry:
        """Create a skill directly from inline data (no file).

        Unlike publish(), this method accepts content as a string
        rather than a file path. Useful for the API layer.
        """
        version = "1.0"
        status = "published" if auto_approve else "draft"

        # Check for existing entry
        existing = self._db.fetchone(
            "SELECT id FROM skill_market WHERE name = ? AND version = ?",
            (name, version),
        )
        if existing:
            version = self._next_version(name)

        description = self._extract_description(content) or name

        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            """INSERT INTO skill_market
               (name, version, type, description, author, tags, filename, content,
                source_url, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, version, ftype, description, author,
             json.dumps(tags or [], ensure_ascii=False),
             f"{name}.yaml", content, "", status, now, now),
        )

        return SkillEntry(
            name=name, version=version, type=ftype,
            description=description, author=author, tags=tags or [],
            filename=f"{name}.yaml", content=content, status=status,
        )

    def publish(self, filepath: str | Path, *,
                author: str = "",
                tags: Optional[list[str]] = None,
                source_url: str = "",
                auto_approve: bool = False) -> SkillEntry:
        """Publish a skill YAML file into the marketplace.

        Reads the file, infers type from path, and registers it.
        """
        fp = Path(filepath)
        if not fp.exists():
            raise FileNotFoundError(f"File not found: {fp}")

        content = fp.read_text(encoding="utf-8")
        name = fp.stem  # filename without extension
        ftype = self._infer_type(fp)
        description = self._extract_description(content)

        version = "1.0"
        status = "published" if auto_approve else "draft"

        # Check for existing entry
        existing = self._db.fetchone(
            "SELECT id FROM skill_market WHERE name = ? AND version = ?",
            (name, version),
        )
        if existing:
            # Bump version
            version = self._next_version(name)

        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            """INSERT INTO skill_market
               (name, version, type, description, author, tags, filename, content,
                source_url, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, version, ftype, description, author,
             json.dumps(tags or [], ensure_ascii=False),
             fp.name, content, source_url, status, now, now),
        )

        return SkillEntry(
            name=name, version=version, type=ftype,
            description=description, author=author, tags=tags or [],
            filename=fp.name, content=content, status=status,
        )

    def _infer_type(self, fp: Path) -> str:
        """Infer skill type from file path."""
        parent = fp.parent.name.lower()
        if "personalities" in parent:
            return "personality"
        elif "agents" in parent:
            return "agent"
        elif "workflows" in parent:
            return "workflow"
        return "personality"

    def _extract_description(self, content: str) -> str:
        """Extract description from YAML frontmatter."""
        import yaml
        try:
            data = yaml.safe_load(content)
            if isinstance(data, dict):
                return data.get("description", "") or data.get("name", "")
        except Exception:
            pass
        return ""

    def _next_version(self, name: str) -> str:
        """Bump to next patch version."""
        rows = self._db.fetchall(
            "SELECT version FROM skill_market WHERE name = ? ORDER BY created_at DESC LIMIT 1",
            (name,),
        )
        if not rows:
            return "1.0"
        parts = rows[0][0].split(".")
        major = int(parts[0]) if parts else 1
        minor = int(parts[1]) if len(parts) > 1 else 0
        return f"{major}.{minor + 1}"

    # ── Listing ─────────────────────────────────────────────────────

    def list_skills(self, status: Optional[str] = None,
                    ftype: Optional[str] = None,
                    tag: Optional[str] = None,
                    query: Optional[str] = None) -> list[SkillEntry]:
        """List skills with optional filters."""
        where = []
        params = []
        if status:
            where.append("status = ?")
            params.append(status)
        if ftype:
            where.append("type = ?")
            params.append(ftype)
        if query:
            where.append("(name LIKE ? OR description LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])

        where_clause = " AND ".join(where) if where else "1=1"
        rows = self._db.fetchall(
            f"SELECT * FROM skill_market WHERE {where_clause} ORDER BY created_at DESC",
            tuple(params),
        )

        result = []
        for row in rows:
            entry = self._row_to_entry(row)
            if tag and tag not in entry.tags:
                continue
            result.append(entry)
        return result

    def get_skill(self, name: str, version: Optional[str] = None) -> Optional[SkillEntry]:
        """Get a specific skill by name and version."""
        if version:
            row = self._db.fetchone(
                "SELECT * FROM skill_market WHERE name = ? AND version = ?",
                (name, version),
            )
        else:
            row = self._db.fetchone(
                "SELECT * FROM skill_market WHERE name = ? ORDER BY created_at DESC LIMIT 1",
                (name,),
            )
        return self._row_to_entry(row) if row else None

    def _row_to_entry(self, row) -> SkillEntry:
        """Convert a DB row to SkillEntry."""
        d = dict(row)
        return SkillEntry(
            name=d["name"],
            version=d["version"],
            type=d.get("type", "personality"),
            description=d.get("description", ""),
            author=d.get("author", ""),
            tags=json.loads(d.get("tags", "[]")),
            filename=d.get("filename", ""),
            content=d.get("content", ""),
            source_url=d.get("source_url", ""),
            status=d.get("status", "draft"),
        )

    # ── Approval workflow ────────────────────────────────────────────

    def submit_for_review(self, name: str, version: str) -> None:
        """Submit a draft skill for review: draft → in_review."""
        self._db.execute(
            "UPDATE skill_market SET status = 'in_review', updated_at = ? WHERE name = ? AND version = ?",
            (datetime.now(timezone.utc).isoformat(), name, version),
        )

    def approve(self, name: str, version: str) -> None:
        """Approve a skill: in_review → published."""
        self._db.execute(
            "UPDATE skill_market SET status = 'published', updated_at = ? WHERE name = ? AND version = ?",
            (datetime.now(timezone.utc).isoformat(), name, version),
        )

    def reject(self, name: str, version: str,
               reason: str = "") -> None:
        """Reject a skill: in_review → rejected."""
        self._db.execute(
            "UPDATE skill_market SET status = 'rejected', updated_at = ? WHERE name = ? AND version = ?",
            (datetime.now(timezone.utc).isoformat(), name, version),
        )

    def archive(self, name: str, version: str) -> None:
        """Archive a skill: published → archived."""
        self._db.execute(
            "UPDATE skill_market SET status = 'archived', updated_at = ? WHERE name = ? AND version = ?",
            (datetime.now(timezone.utc).isoformat(), name, version),
        )

    # ── Install / Remove ────────────────────────────────────────────

    def install(self, name: str, version: Optional[str] = None,
                target_dir: str | Path = ".") -> str:
        """Install a published skill into the local project.

        Copies the skill content to the appropriate directory
        (personalities/, agents/, workflows/).
        """
        skill = self.get_skill(name, version)
        if skill is None:
            raise ValueError(f"Skill '{name}' v{version or 'latest'} not found")
        if skill.status != "published":
            raise ValueError(f"Skill '{name}' is not published (status: {skill.status})")

        target = Path(target_dir)
        if skill.type == "personality":
            dest = target / "personalities" / skill.filename
        elif skill.type == "agent":
            dest = target / "agents" / skill.filename
        elif skill.type == "workflow":
            dest = target / "workflows" / skill.filename
        else:
            dest = target / "personalities" / skill.filename

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(skill.content, encoding="utf-8")

        # Record installation
        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "INSERT OR REPLACE INTO installed_skills (name, version, type, installed_at) VALUES (?, ?, ?, ?)",
            (skill.name, skill.version, skill.type, now),
        )

        # Increment install count (best-effort)
        try:
            from sccsos.skill_rating import SkillRatingManager
            SkillRatingManager(self._db).increment_install_count(name, version or "1.0")
        except Exception:
            pass

        return str(dest)

    def remove(self, name: str) -> None:
        """Remove an installed skill record."""
        self._db.execute(
            "DELETE FROM installed_skills WHERE name = ?",
            (name,),
        )

    def list_installed(self) -> list[InstalledSkill]:
        """List all installed skills."""
        rows = self._db.fetchall(
            "SELECT * FROM installed_skills ORDER BY installed_at DESC",
        )
        return [
            InstalledSkill(
                name=r["name"],
                version=r["version"],
                type=r["type"],
                installed_at=r["installed_at"] if "installed_at" in r.keys() else "",
            )
            for r in rows
        ]

    # ── Cleanup / Maintenance ─────────────────────────────────────────

    def prune_stale(self, days: int = 90,
                    statuses: Optional[list[str]] = None) -> dict:
        """Delete stale skills not updated in N days.

        Args:
            days: Age threshold in days (default 90).
            statuses: Statuses to target (default: draft, rejected).

        Returns:
            Dict with counts of pruned skills per status.
        """
        if statuses is None:
            statuses = ["draft", "rejected"]
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        results = {}
        for st in statuses:
            rows = self._db.fetchall(
                "SELECT name, version FROM skill_market "
                "WHERE status = ? AND updated_at < ?",
                (st, cutoff),
            )
            if rows:
                self._db.execute(
                    "DELETE FROM skill_market "
                    "WHERE status = ? AND updated_at < ?",
                    (st, cutoff),
                )
            results[st] = len(rows)
        self._db.commit()
        return results

    def prune_orphaned(self) -> int:
        """Delete skills with broken content that fail YAML parse.

        Returns:
            Number of skills deleted.
        """
        rows = self._db.fetchall(
            "SELECT name, version, content FROM skill_market "
            "WHERE content IS NOT NULL AND content != ''",
        )
        import yaml
        deleted = 0
        for row in rows:
            try:
                data = yaml.safe_load(row["content"])
                if data is None:
                    raise ValueError("empty YAML")
            except Exception:
                self._db.execute(
                    "DELETE FROM skill_market WHERE name = ? AND version = ?",
                    (row["name"], row["version"]),
                )
                deleted += 1
        if deleted:
            self._db.commit()
        return deleted

    def verify_all(self) -> dict:
        """Verify all published/installed skills for YAML validity.

        Returns:
            Dict with total, valid, invalid counts and list of issues.
        """
        rows = self._db.fetchall(
            "SELECT name, version, type, status, content FROM skill_market "
            "WHERE status IN ('published', 'approved')",
        )
        import yaml
        valid = 0
        invalid = 0
        issues = []
        for row in rows:
            content = row["content"] if row["content"] else ""
            if not content.strip():
                invalid += 1
                issues.append({
                    "name": row["name"], "version": row["version"],
                    "issue": "empty content",
                })
                continue
            try:
                data = yaml.safe_load(content)
                if not isinstance(data, dict):
                    invalid += 1
                    issues.append({
                        "name": row["name"], "version": row["version"],
                        "issue": "not a YAML mapping",
                    })
                else:
                    valid += 1
            except yaml.YAMLError as e:
                invalid += 1
                issues.append({
                    "name": row["name"], "version": row["version"],
                    "issue": f"YAML error: {e}",
                })
        return {
            "total": valid + invalid,
            "valid": valid,
            "invalid": invalid,
            "issues": issues[:50],  # Cap at 50
        }
