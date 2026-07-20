"""Tests for Personality Version Manager."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sccsos.core.db import Database
from sccsos.core.personality_version import PersonalityVersionManager


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    db = Database(path)
    db.initialize()
    yield db
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def personalities_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def mgr(db, personalities_dir):
    return PersonalityVersionManager(db, personalities_dir)


class TestPersonalityVersionCore:

    def test_save_first_version(self, mgr, personalities_dir):
        """First save should create version 1.0."""
        yaml_path = personalities_dir / "architect.yaml"
        yaml_path.write_text("name: architect\nsystem_prompt: Be helpful\n", encoding="utf-8")
        ver = mgr.save_version("architect", change_log="Initial")
        assert ver == "1.0"

    def test_save_increments_version(self, mgr, personalities_dir):
        """Second save should increment to 1.1."""
        yaml_path = personalities_dir / "architect.yaml"
        yaml_path.write_text("v1", encoding="utf-8")
        mgr.save_version("architect")
        yaml_path.write_text("v2", encoding="utf-8")
        ver = mgr.save_version("architect")
        assert ver == "1.1"

    def test_list_versions_returns_all(self, mgr, personalities_dir):
        """list_versions should return all versions, newest first."""
        yaml_path = personalities_dir / "architect.yaml"
        yaml_path.write_text("v1", encoding="utf-8")
        mgr.save_version("architect", "first")
        yaml_path.write_text("v2", encoding="utf-8")
        mgr.save_version("architect", "second")

        versions = mgr.list_versions("architect")
        assert len(versions) == 2
        assert versions[0].version == "1.1"  # newest first
        assert versions[1].version == "1.0"

    def test_list_versions_empty(self, mgr):
        """list_versions for unknown name should return empty list."""
        assert mgr.list_versions("nonexistent") == []

    def test_get_version_returns_content(self, mgr, personalities_dir):
        """get_version should return the exact content saved."""
        yaml_path = personalities_dir / "architect.yaml"
        yaml_path.write_text("name: architect\nprompt: design\n", encoding="utf-8")
        mgr.save_version("architect", "initial")
        yaml_path.write_text("name: architect\nprompt: review\n", encoding="utf-8")
        mgr.save_version("architect", "updated")

        v1 = mgr.get_version("architect", "1.0")
        v2 = mgr.get_version("architect", "1.1")
        assert v1 is not None
        assert v2 is not None
        assert "design" in v1.content
        assert "review" in v2.content
        assert v1.change_log == "initial"
        assert v2.change_log == "updated"

    def test_get_version_not_found(self, mgr):
        """get_version for nonexistent version should return None."""
        assert mgr.get_version("architect", "99.99") is None

    def test_get_current_latest(self, mgr, personalities_dir):
        """get_current should return the latest version content."""
        yaml_path = personalities_dir / "architect.yaml"
        yaml_path.write_text("latest-content", encoding="utf-8")
        mgr.save_version("architect")

        current = mgr.get_current("architect")
        assert current is not None
        assert "latest-content" in current

    def test_get_current_no_versions(self, mgr):
        """get_current when no versions exist should return None."""
        assert mgr.get_current("architect") is None

    def test_list_all_personalities(self, mgr, personalities_dir):
        """list_all_personalities should return unique names."""
        for name in ["architect", "reviewer"]:
            (personalities_dir / f"{name}.yaml").write_text(f"name: {name}", encoding="utf-8")
            mgr.save_version(name)

        names = mgr.list_all_personalities()
        assert "architect" in names
        assert "reviewer" in names

    def test_save_missing_file_raises(self, mgr):
        """save_version on nonexistent personality should raise."""
        with pytest.raises(FileNotFoundError):
            mgr.save_version("nonexistent")

    def test_read_personality_file_case_insensitive(self, mgr, personalities_dir):
        """File lookup should be case-insensitive."""
        (personalities_dir / "MY-AGENT.yaml").write_text("content", encoding="utf-8")
        content = mgr._read_personality_file("my-agent")
        assert content == "content"

    def test_save_keeps_change_log(self, mgr, personalities_dir):
        """Change log should be stored and retrievable."""
        yaml_path = personalities_dir / "architect.yaml"
        yaml_path.write_text("data", encoding="utf-8")
        mgr.save_version("architect", change_log="Fixed prompt injection vulnerability")
        v = mgr.get_version("architect", "1.0")
        assert v is not None
        assert "vulnerability" in v.change_log

    def test_runtime_wiring(self, db, personalities_dir):
        """PersonalityVersionManager should work with a real db fixture."""
        mgr = PersonalityVersionManager(db, personalities_dir)
        (personalities_dir / "test.yaml").write_text("hello", encoding="utf-8")
        ver = mgr.save_version("test")
        assert ver == "1.0"
        versions = mgr.list_versions("test")
        assert len(versions) == 1
