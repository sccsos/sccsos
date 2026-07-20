"""Tests for SkillMarket cleanup/prune/verify methods."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone, timedelta

import pytest
import yaml

from sccsos.core.db import Database
from sccsos.skill_market import SkillMarket


@pytest.fixture
def db():
    """Create a temporary SQLite database for testing."""
    tmp = tempfile.mktemp(suffix=".db")
    database = Database(db_path=tmp)
    database.initialize()
    yield database
    database.close()
    os.unlink(tmp)


@pytest.fixture
def market(db):
    """SkillMarket with an empty DB."""
    return SkillMarket(db)


def _insert_skill(db, name, version, status, content, updated_at_days_ago=0):
    """Helper to insert a skill with a controlled updated_at."""
    now = datetime.now(timezone.utc)
    updated = (now - timedelta(days=updated_at_days_ago)).isoformat()
    db.execute(
        "INSERT INTO skill_market (name, version, type, description, author, "
        "filename, content, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, version, "personality", f"Test {name}", "tester",
         f"{name}.yaml", content, status, now.isoformat(), updated),
    )
    db.commit()


class TestSkillMarketPruneStale:
    """Tests for prune_stale()."""

    def test_prune_nothing_stale(self, db, market):
        """No skills older than threshold → nothing pruned."""
        _insert_skill(db, "fresh", "1.0", "draft", "name: fresh\nsystem_prompt: ok", 10)
        result = market.prune_stale(days=30)
        assert sum(result.values()) == 0

    def test_prune_stale_draft(self, db, market):
        """Old draft skills are pruned."""
        _insert_skill(db, "stale", "1.0", "draft", "name: stale\nsystem_prompt: ok", 100)
        _insert_skill(db, "fresh", "1.0", "draft", "name: fresh\nsystem_prompt: ok", 10)
        result = market.prune_stale(days=90)
        assert result.get("draft", 0) == 1
        # Fresh one still exists
        remaining = market.list_skills(status="draft")
        assert len(remaining) == 1
        assert remaining[0].name == "fresh"

    def test_prune_stale_rejected(self, db, market):
        """Old rejected skills are pruned."""
        _insert_skill(db, "old-reject", "1.0", "rejected", "name: bad", 200)
        result = market.prune_stale(days=90)
        assert result.get("rejected", 0) >= 1

    def test_prune_keeps_recent_rejected(self, db, market):
        """Recently rejected skills are kept."""
        _insert_skill(db, "recent-reject", "1.0", "rejected", "name: bad", 5)
        result = market.prune_stale(days=90)
        assert result.get("rejected", 0) == 0
        remaining = market.list_skills(status="rejected")
        assert len(remaining) == 1


class TestSkillMarketPruneOrphaned:
    """Tests for prune_orphaned()."""

    def test_prune_broken_yaml(self, db, market):
        """Skills with broken YAML content are deleted."""
        _insert_skill(db, "broken", "1.0", "draft", "{invalid: yaml: broken", 1)
        count = market.prune_orphaned()
        assert count >= 1
        assert market.get_skill("broken") is None

    def test_prune_empty_content(self, db, market):
        """Skills with empty content are NOT deleted (no content)."""
        _insert_skill(db, "empty", "1.0", "draft", "", 1)
        count = market.prune_orphaned()
        # Empty content is excluded by WHERE content != ''
        assert count == 0

    def test_prune_valid_kept(self, db, market):
        """Valid YAML skills are NOT deleted."""
        _insert_skill(db, "valid", "1.0", "draft",
                      "name: valid\nsystem_prompt: hello", 1)
        count = market.prune_orphaned()
        assert count == 0
        assert market.get_skill("valid") is not None


class TestSkillMarketVerifyAll:
    """Tests for verify_all()."""

    def test_verify_valid_skill(self, db, market):
        """Valid YAML is reported as valid."""
        _insert_skill(db, "good", "1.0", "approved",
                      "name: good\nsystem_prompt: hello", 1)
        result = market.verify_all()
        assert result["total"] == 1
        assert result["valid"] == 1
        assert result["invalid"] == 0

    def test_verify_invalid_yaml(self, db, market):
        """Invalid YAML is reported as invalid with issue."""
        _insert_skill(db, "bad", "1.0", "approved", "{broken", 1)
        result = market.verify_all()
        assert result["total"] == 1
        assert result["valid"] == 0
        assert result["invalid"] == 1
        assert len(result["issues"]) == 1
        assert "YAML error" in result["issues"][0]["issue"]

    def test_verify_empty_content(self, db, market):
        """Empty content is reported as invalid."""
        _insert_skill(db, "empty", "1.0", "approved", "", 1)
        result = market.verify_all()
        assert result["invalid"] >= 1

    def test_verify_skips_draft(self, db, market):
        """Draft skills are excluded from verification."""
        _insert_skill(db, "draft-only", "1.0", "draft",
                      "name: draft\nsystem_prompt: ok", 1)
        result = market.verify_all()
        assert result["total"] == 0
