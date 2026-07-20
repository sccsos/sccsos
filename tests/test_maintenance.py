"""Tests for MaintenanceScheduler — periodic cleanup tasks."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone, timedelta

import pytest
import yaml

from sccsos.core.db import Database
from sccsos.core.maintenance import MaintenanceScheduler


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
def scheduler(db):
    """MaintenanceScheduler with empty DB."""
    return MaintenanceScheduler(db)


def _insert_skill(db, name, version, status, content, updated_at_days_ago=0):
    """Helper to insert a skill with controlled updated_at."""
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


class TestMaintenanceRunOnce:
    """Tests for a single maintenance pass."""

    def test_run_with_nothing_to_clean(self, scheduler, db):
        """Empty DB → maintenance runs cleanly."""
        results = scheduler.run_once()
        assert results["_meta"]["total_removed"] == 0
        assert sum(results["prune_stale"].values()) == 0
        assert results["prune_orphaned"] == 0

    def test_run_prunes_stale_drafts(self, scheduler, db):
        """Old drafts are pruned during maintenance."""
        _insert_skill(db, "stale", "1.0", "draft",
                      "name: stale\nsystem_prompt: ok", 100)
        results = scheduler.run_once()
        assert results["prune_stale"].get("draft", 0) >= 1
        assert results["_meta"]["total_removed"] >= 1

    def test_run_prunes_stale_rejected(self, scheduler, db):
        """Old rejected skills are pruned during maintenance."""
        _insert_skill(db, "rejected", "1.0", "rejected",
                      "name: bad", 200)
        results = scheduler.run_once()
        assert results["prune_stale"].get("rejected", 0) >= 1

    def test_run_verifies_published(self, scheduler, db):
        """Published skills are verified during maintenance."""
        _insert_skill(db, "good", "1.0", "approved",
                      "name: good\nsystem_prompt: hello", 1)
        results = scheduler.run_once()
        assert results["verify"]["total"] >= 1
        assert results["verify"]["valid"] >= 1

    def test_run_cleans_broken_yaml(self, scheduler, db):
        """Skills with broken YAML are pruned."""
        _insert_skill(db, "broken", "1.0", "draft",
                      "{invalid: yaml: broken", 1)
        results = scheduler.run_once()
        assert results["prune_orphaned"] >= 1

    def test_run_preserves_recent_skills(self, scheduler, db):
        """Recent draft skills are kept."""
        _insert_skill(db, "recent", "1.0", "draft",
                      "name: recent\nsystem_prompt: ok", 1)
        results = scheduler.run_once()
        assert results["prune_stale"].get("draft", 0) == 0


class TestMaintenanceSchedulerLifecycle:
    """Tests for background scheduler start/stop."""

    def test_start_stop(self, scheduler):
        """Scheduler can be started and stopped."""
        scheduler.start(interval_hours=1)
        assert scheduler._thread is not None
        assert scheduler._thread.is_alive()
        scheduler.stop()
        assert scheduler._thread is None

    def test_double_start(self, scheduler):
        """Starting twice does not create two threads."""
        scheduler.start(interval_hours=1)
        t1 = scheduler._thread
        scheduler.start(interval_hours=1)
        assert scheduler._thread is t1
        scheduler.stop()

    def test_stop_without_start(self, scheduler):
        """Stopping without starting is a no-op."""
        scheduler.stop()  # Should not raise
        assert True
