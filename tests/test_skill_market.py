"""Tests for SkillMarket — marketplace CRUD, publish, install, maintenance.

Tests cover:
  - SkillEntry / InstalledSkill dataclasses
  - create_skill (inline) and publish (file-based)
  - list_skills with status/type/tag/query filters
  - get_skill by name and version
  - submit_for_review / approve / reject / archive lifecycle
  - install / remove / list_installed
  - prune_stale / prune_orphaned / verify_all maintenance
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from sccsos.core.db import Database
from sccsos.skill_market import InstalledSkill, SkillEntry, SkillMarket


@pytest.fixture
def db():
    tmp = tempfile.mktemp(suffix=".db")
    database = Database(db_path=tmp)
    database.initialize()
    yield database
    database.close()
    os.unlink(tmp)


@pytest.fixture
def market(db):
    return SkillMarket(db)


# ── Data Types ────────────────────────────────────────────────────────


class TestSkillEntry:
    def test_defaults(self):
        s = SkillEntry(name="test-agent")
        assert s.version == "1.0"
        assert s.type == "personality"
        assert s.status == "draft"
        assert s.tags == []

    def test_all_fields(self):
        s = SkillEntry(
            name="agent-a", version="2.1", type="agent",
            description="My agent", author="tester",
            tags=["nlp", "demo"], filename="agent-a.yaml",
            content="name: agent-a", source_url="https://example.com",
            status="published",
        )
        assert s.name == "agent-a"
        assert s.tags == ["nlp", "demo"]


class TestInstalledSkill:
    def test_defaults(self):
        s = InstalledSkill(name="test", version="1.0", type="personality")
        assert s.installed_at == ""

    def test_with_timestamp(self):
        s = InstalledSkill(name="test", version="2.0", type="workflow",
                           installed_at="2026-07-22T00:00:00")
        assert s.installed_at == "2026-07-22T00:00:00"


# ── Create Skill ──────────────────────────────────────────────────────


class TestCreateSkill:
    """Inline skill creation (no file)."""

    def test_create_basic(self, market):
        entry = market.create_skill(name="agent-x", author="me")
        assert entry.name == "agent-x"
        assert entry.version == "1.0"
        assert entry.type == "personality"
        assert entry.status == "draft"
        assert entry.author == "me"

    def test_create_with_content(self, market):
        yaml = "name: agent-x\nsystem_prompt: You are helpful."
        entry = market.create_skill(
            name="agent-x", ftype="agent", content=yaml,
            tags=["ai", "test"], auto_approve=True,
        )
        assert entry.status == "published"
        assert "ai" in entry.tags
        assert entry.content == yaml

    def test_create_version_bump(self, market):
        """Creating a skill with the same name bumps version."""
        market.create_skill(name="dup-agent")
        entry = market.create_skill(name="dup-agent")
        assert entry.version == "1.1"

    def test_create_with_description_extracted(self, market):
        """Description extracted from YAML content."""
        yaml = "name: my-agent\ndescription: A helpful test agent"
        entry = market.create_skill(name="my-agent", content=yaml)
        assert entry.description == "A helpful test agent"


# ── Publish Skill (file-based) ────────────────────────────────────────


class TestPublishSkill:
    def test_publish_from_file(self, market, tmp_path):
        skill_file = tmp_path / "personalities" / "test-agent.yaml"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text("name: test-agent\nsystem_prompt: Hi", encoding="utf-8")
        entry = market.publish(str(skill_file), author="tester")
        assert entry.name == "test-agent"
        assert entry.status == "draft"

    def test_publish_auto_approve(self, market, tmp_path):
        skill_file = tmp_path / "personalities" / "quick.yaml"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text("name: quick", encoding="utf-8")
        entry = market.publish(str(skill_file), auto_approve=True)
        assert entry.status == "published"

    def test_publish_file_not_found(self, market):
        with pytest.raises(FileNotFoundError):
            market.publish("/nonexistent/path.yaml")

    def test_publish_type_inferred(self, market, tmp_path):
        """Type is inferred from parent directory name."""
        for dirname, expected_type in [
            ("personalities", "personality"),
            ("agents", "agent"),
            ("workflows", "workflow"),
        ]:
            skill_file = tmp_path / dirname / "s.yaml"
            skill_file.parent.mkdir(parents=True, exist_ok=True)
            skill_file.write_text("name: s", encoding="utf-8")
            entry = market.publish(str(skill_file))
            assert entry.type == expected_type, f"{dirname} should map to {expected_type}"


# ── List / Get Skills ────────────────────────────────────────────────


class TestListSkills:
    def _seed(self, market):
        market.create_skill(name="agent-a", ftype="agent", tags=["nlp"])
        market.create_skill(name="agent-b", ftype="agent", tags=["vision"])
        market.create_skill(name="helper", ftype="personality",
                            content="description: 'Helpful bot'")
        # Create an auto-approved (published) skill
        market.create_skill(name="prod-agent", auto_approve=True, tags=["nlp"])

    def test_list_all(self, market):
        self._seed(market)
        all_skills = market.list_skills()
        assert len(all_skills) == 4

    def test_list_by_status(self, market):
        self._seed(market)
        drafts = market.list_skills(status="draft")
        published = market.list_skills(status="published")
        assert len(drafts) == 3
        assert len(published) == 1

    def test_list_by_type(self, market):
        self._seed(market)
        agents = market.list_skills(ftype="agent")
        assert len(agents) == 2
        personalities = market.list_skills(ftype="personality")
        assert len(personalities) == 2  # helper + prod-agent (default type)

    def test_list_by_tag(self, market):
        self._seed(market)
        nlp_skills = market.list_skills(tag="nlp")
        assert len(nlp_skills) == 2  # agent-a + prod-agent

    def test_list_by_query(self, market):
        self._seed(market)
        results = market.list_skills(query="agent")
        assert len(results) >= 2  # agent-a, agent-b

    def test_list_by_query_description(self, market):
        self._seed(market)
        results = market.list_skills(query="Helpful")
        assert len(results) == 1
        assert results[0].name == "helper"

    def test_list_empty(self, market):
        assert market.list_skills() == []


class TestGetSkill:
    def test_get_by_name(self, market):
        market.create_skill(name="get-test")
        entry = market.get_skill("get-test")
        assert entry is not None
        assert entry.name == "get-test"

    def test_get_by_name_and_version(self, market):
        market.create_skill(name="v-test")
        market.create_skill(name="v-test")  # version 1.1
        entry = market.get_skill("v-test", version="1.0")
        assert entry.version == "1.0"

    def test_get_latest(self, market):
        market.create_skill(name="latest-test")
        market.create_skill(name="latest-test")  # 1.1
        entry = market.get_skill("latest-test")  # Gets latest
        assert entry.version == "1.1"

    def test_get_not_found(self, market):
        assert market.get_skill("ghost") is None
        assert market.get_skill("ghost", version="9.9") is None


# ── Review Lifecycle ─────────────────────────────────────────────────


class TestReviewLifecycle:
    def test_submit_for_review(self, market):
        market.create_skill(name="review-me")
        market.submit_for_review("review-me", "1.0")
        entry = market.get_skill("review-me")
        assert entry.status == "in_review"

    def test_approve_skill(self, market):
        market.create_skill(name="approve-me")
        market.submit_for_review("approve-me", "1.0")
        market.approve("approve-me", "1.0")
        entry = market.get_skill("approve-me")
        assert entry.status == "published"

    def test_reject_skill(self, market):
        market.create_skill(name="reject-me")
        market.submit_for_review("reject-me", "1.0")
        market.reject("reject-me", "1.0")
        entry = market.get_skill("reject-me")
        assert entry.status == "rejected"

    def test_archive_skill(self, market):
        market.create_skill(name="archive-me", auto_approve=True)
        market.archive("archive-me", "1.0")
        entry = market.get_skill("archive-me")
        assert entry.status == "archived"


# ── Install / Remove ─────────────────────────────────────────────────


class TestInstallRemove:
    def test_install_published_skill(self, market, tmp_path):
        market.create_skill(name="inst-agent", ftype="agent", auto_approve=True)
        dest = market.install("inst-agent", target_dir=str(tmp_path))
        assert Path(dest).exists()
        assert "inst-agent" in dest

    def test_install_not_published(self, market):
        market.create_skill(name="draft-agent")
        with pytest.raises(ValueError, match="not published"):
            market.install("draft-agent")

    def test_install_not_found(self, market):
        with pytest.raises(ValueError, match="not found"):
            market.install("ghost")

    def test_list_installed(self, market, tmp_path):
        market.create_skill(name="inst-a", auto_approve=True)
        market.create_skill(name="inst-b", auto_approve=True)
        market.install("inst-a", target_dir=str(tmp_path))
        market.install("inst-b", target_dir=str(tmp_path))
        installed = market.list_installed()
        assert len(installed) == 2
        names = [s.name for s in installed]
        assert "inst-a" in names
        assert "inst-b" in names

    def test_remove_installed(self, market, tmp_path):
        market.create_skill(name="to-remove", auto_approve=True)
        market.install("to-remove", target_dir=str(tmp_path))
        assert len(market.list_installed()) == 1
        market.remove("to-remove")
        assert len(market.list_installed()) == 0

    def test_remove_nonexistent(self, market):
        market.remove("ghost")  # Should not raise


# ── Maintenance ──────────────────────────────────────────────────────


class TestMaintenance:
    def test_prune_stale(self, market):
        market.create_skill(name="stale-draft")
        market.create_skill(name="stale-rejected")
        market.submit_for_review("stale-rejected", "1.0")
        market.reject("stale-rejected", "1.0")
        result = market.prune_stale(days=0)  # Age threshold = 0 days = all stale
        assert result.get("draft", 0) >= 1
        assert result.get("rejected", 0) >= 1

    def test_prune_stale_no_stale(self, market):
        result = market.prune_stale(days=9999)
        assert all(v == 0 for v in result.values())

    def test_prune_orphaned(self, market):
        """Orphaned skills (broken YAML content) should be pruned."""
        # Create a skill with invalid content
        market.create_skill(name="broken", content=": : invalid yaml : : :")
        count = market.prune_orphaned()
        assert count >= 1
        # Should be removed from DB
        assert market.get_skill("broken") is None

    def test_prune_orphaned_valid_content(self, market):
        """Valid skills should survive orphan pruning."""
        market.create_skill(name="good-skill", content="name: good")
        count = market.prune_orphaned()
        assert count == 0
        assert market.get_skill("good-skill") is not None

    def test_verify_all_valid(self, market):
        market.create_skill(name="valid", content="name: valid", auto_approve=True)
        result = market.verify_all()
        assert result["total"] >= 1
        assert result["valid"] >= 1
        assert "valid" not in [i["name"] for i in result["issues"]]

    def test_verify_all_detects_invalid(self, market):
        market.create_skill(name="invalid", content=": : : broken", auto_approve=True)
        result = market.verify_all()
        assert result["invalid"] >= 1
        issue_names = [i["name"] for i in result["issues"]]
        assert "invalid" in issue_names

    def test_verify_all_empty_content(self, market):
        """Empty content should be flagged as invalid."""
        market.create_skill(name="empty", content="", auto_approve=True)
        result = market.verify_all()
        assert result["invalid"] >= 1


# ── Row-to-Entry Conversion ──────────────────────────────────────────


class TestRowConversion:
    def test_row_to_entry(self, market, db):
        """_row_to_entry should handle all fields including tags JSON."""
        market.create_skill(name="row-test", tags=["a", "b"])
        row = db.fetchone(
            "SELECT * FROM skill_market WHERE name = ?", ("row-test",)
        )
        entry = market._row_to_entry(row)
        assert entry.name == "row-test"
        assert entry.tags == ["a", "b"]
