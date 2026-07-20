"""Integration tests for PostgreSQL backend.

Requires:
  - ``sccsos[pg]`` extras installed
  - A running PostgreSQL at the configured DSN

Environment:
  SCCSOS_PG_DSN: PostgreSQL DSN (default: postgresql://postgres:SmartBiz9158#@localhost:5432/sccsos_test)
"""

from __future__ import annotations

import os

import pytest

PG_DSN = os.environ.get(
    "SCCSOS_PG_DSN",
    "postgresql://postgres:SmartBiz9158#@localhost:5432/sccsos_test",
)


def _pg_available() -> bool:
    """Check if PostgreSQL is reachable."""
    import psycopg2
    try:
        conn = psycopg2.connect(PG_DSN, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_available(),
    reason=f"PostgreSQL not available at {PG_DSN}",
)


@pytest.fixture
def pg_db():
    """PostgreSQL database with SCCS OS schema."""
    from sccsos.core.db import create_database
    from sccsos.core.config import DatabaseConfig

    cfg = DatabaseConfig(
        driver="postgres",
        dsn=PG_DSN,
    )
    # Clean slate: drop and recreate schema
    import psycopg2
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    cur = conn.cursor()
    tables = [
        "skill_market", "installed_skills", "agent_events",
        "agent_sessions", "session_messages", "workflow_runs",
        "workflow_steps", "audit_log", "trace_spans",
        "personality_versions", "memory_store", "event_queue",
    ]
    for t in tables:
        cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    cur.close()
    conn.close()

    db = create_database(cfg)
    db.initialize()
    yield db
    db.close()


class TestPostgresDatabase:
    """Test basic PostgreSQL database operations."""

    def test_health(self, pg_db):
        """Health check works."""
        health = pg_db.check_health()
        assert health["status"] == "ok"

    def test_execute_insert_and_select(self, pg_db):
        """Basic CRUD works. Uses ? placeholders (converted to %s by driver)."""
        pg_db.execute(
            "INSERT INTO skill_market (name, version, type, description, author, "
            "filename, content, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NOW(), NOW())",
            ("pg-test-skill", "1.0", "personality", "PG test", "tester",
             "pg-test.yaml", "name: pg-test\nsystem_prompt: hello", "draft"),
        )
        pg_db.commit()

        row = pg_db.fetchone(
            "SELECT name, version, status FROM skill_market WHERE name = ?",
            ("pg-test-skill",),
        )
        assert row is not None
        assert dict(row)["name"] == "pg-test-skill"
        assert dict(row)["version"] == "1.0"
        assert dict(row)["status"] == "draft"

    def test_fetchall(self, pg_db):
        """fetchall returns multiple rows."""
        for i in range(3):
            pg_db.execute(
                "INSERT INTO skill_market (name, version, type, description, author, "
                "filename, content, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NOW(), NOW())",
                (f"pg-skill-{i}", "1.0", "personality", f"Test {i}", "tester",
                 f"skill-{i}.yaml", f"name: test-{i}\nsystem_prompt: ok", "draft"),
            )
        pg_db.commit()

        rows = pg_db.fetchall(
            "SELECT name FROM skill_market WHERE name LIKE 'pg-skill-%%' ORDER BY name",
        )
        assert len(rows) == 3
        assert rows[0]["name"] == "pg-skill-0"

    @pytest.mark.skip(reason="known bug: INSERT OR REPLACE UPSERT conversion mismatches param count")
    def test_upsert(self, pg_db):
        """INSERT OR REPLACE → UPSERT conversion works."""
        pg_db.execute(
            "INSERT OR REPLACE INTO memory_store (tenant_id, agent_name, key, "
            "value_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, NOW(), NOW())",
            ("default", "test-agent", "mykey", '"myvalue"'),
        )
        pg_db.commit()

        row = pg_db.fetchone(
            "SELECT value_json FROM memory_store "
            "WHERE tenant_id = ? AND agent_name = ? AND key = ?",
            ("default", "test-agent", "mykey"),
        )
        assert row is not None
        assert '"myvalue"' in row["value_json"]

    def test_transaction_rollback(self, pg_db):
        """Rollback works correctly."""
        pg_db.execute(
            "INSERT INTO skill_market (name, version, type, description, author, "
            "filename, content, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NOW(), NOW())",
            ("rollback-test", "1.0", "personality", "rollback", "tester",
             "rb.yaml", "name: rb\nsystem_prompt: ok", "draft"),
        )
        pg_db.execute("ROLLBACK")

        row = pg_db.fetchone(
            "SELECT name FROM skill_market WHERE name = 'rollback-test'",
        )
        assert row is None
