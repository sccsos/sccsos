"""Tests for database schema migrations."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from sccsos.core.db.schema import (
    SCHEMA_SQL,
    apply_migrations,
)


class TestSchemaMigrations:
    """Schema migration tests using fresh SQLite databases."""

    @pytest.fixture
    def db(self):
        """Fresh empty SQLite database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        yield conn
        conn.close()
        Path(path).unlink(missing_ok=True)

    def test_full_schema_creates_all_tables(self, db):
        """Applying full SCHEMA_SQL creates all expected tables."""
        db.executescript(SCHEMA_SQL)
        db.commit()
        tables = {
            r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {
            "agents", "agent_events", "workflow_runs", "workflow_steps",
            "traces", "audit_log", "memory_store",
            "agent_messages", "agent_sessions", "session_messages",
            "skill_market", "skill_ratings", "review_comments",
            "review_history",
        }
        for t in expected:
            assert t in tables, f"Missing table: {t}"

    def test_schema_idempotent(self, db):
        """Running SCHEMA_SQL twice is safe (no errors)."""
        db.executescript(SCHEMA_SQL)
        db.commit()
        # Second run should be a no-op
        db.executescript(SCHEMA_SQL)
        db.commit()

    def test_migrate_from_scratch(self, db):
        """apply_migrations works on a fresh database."""
        db.executescript(SCHEMA_SQL)
        db.commit()
        # Should not raise
        apply_migrations(db)

    def test_migrate_adds_columns(self, db):
        """apply_migrations is safe on a current-schema database."""
        db.executescript(SCHEMA_SQL)
        db.commit()
        # Run migration (should be a no-op)
        apply_migrations(db)

    def test_migrate_from_v0_bootstrap(self, db):
        """apply_migrations can bootstrap from a v0 schema with base tables."""
        # Create a v0-compatible schema (without migration-specific columns/tables)
        db.executescript("""
            CREATE TABLE agents (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'created'
            );
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL, event_type TEXT NOT NULL
            );
            CREATE TABLE workflow_runs (
                id TEXT PRIMARY KEY, workflow_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running'
            );
            CREATE TABLE skill_market (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE, status TEXT DEFAULT 'pending'
            );
        """)
        db.commit()
        apply_migrations(db)
        # After migration, migration-specific tables should exist
        tables = {
            r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "memory_store" in tables
        assert "skill_ratings" in tables
        assert "subscriptions" in tables
        # Migration-specific columns should exist
        col_info = db.execute(
            "PRAGMA table_info(skill_market)"
        ).fetchall()
        col_names = [c[1] for c in col_info]
        assert "review_notes" in col_names
        assert "install_count" in col_names
        assert "category" in col_names

    def test_migrate_idempotent(self, db):
        """apply_migrations can be run multiple times safely."""
        db.executescript(SCHEMA_SQL)
        db.commit()
        apply_migrations(db)
        # Second run should not raise
        apply_migrations(db)
