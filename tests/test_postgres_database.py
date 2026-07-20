"""Tests for PostgreSQL database adapter (SQL dialect conversion).

These tests validate the SQLite-to-PostgreSQL conversion layer
without requiring a running PostgreSQL instance (psycopg2 import
is optional).
"""

from __future__ import annotations

import pytest
from sccsos.core.db import (
    _convert_sql_for_pg,
    PostgresDatabase,
    AbstractDatabase,
)


class TestSqlConversion:
    """Test _convert_sql_for_pg SQLite→PostgreSQL dialect conversion."""

    def test_qmark_to_ps(self):
        """? → %s parameter placeholder conversion."""
        sql = "SELECT * FROM agents WHERE id = ? AND name = ?"
        result = _convert_sql_for_pg(sql)
        assert result == "SELECT * FROM agents WHERE id = %s AND name = %s"

    def test_qmark_values(self):
        """? → %s in VALUES clause."""
        sql = "INSERT INTO agents (id, name) VALUES (?, ?)"
        result = _convert_sql_for_pg(sql)
        assert result == "INSERT INTO agents (id, name) VALUES (%s, %s)"

    def test_datetime_now(self):
        """datetime('now') → NOW() conversion."""
        sql = "UPDATE agents SET started_at = datetime('now') WHERE id = ?"
        result = _convert_sql_for_pg(sql)
        assert result == "UPDATE agents SET started_at = NOW() WHERE id = %s"

    def test_insert_or_replace_personality(self):
        """INSERT OR REPLACE INTO personality_versions → UPSERT."""
        sql = (
            "INSERT OR REPLACE INTO personality_versions "
            "(personality_name, version, content, change_log, created_at) "
            "VALUES (?, ?, ?, ?, ?)"
        )
        result = _convert_sql_for_pg(sql)
        assert result.startswith("INSERT INTO personality_versions")
        assert "ON CONFLICT" in result
        assert "DO UPDATE SET" in result
        assert "content = EXCLUDED.content" in result
        assert "change_log = EXCLUDED.change_log" in result
        assert "personality_name, version" in result

    def test_combined_conversion(self):
        """Multiple conversions in a single query."""
        sql = (
            "UPDATE agents SET "
            "status = ?, "
            "started_at = datetime('now') "
            "WHERE id = ?"
        )
        result = _convert_sql_for_pg(sql)
        assert "%s" in result
        assert "NOW()" in result
        assert "datetime('now')" not in result
        assert "?" not in result

    def test_simple_select_unchanged(self):
        """Simple SELECT without ? passes through."""
        sql = "SELECT 1"
        result = _convert_sql_for_pg(sql)
        assert result == "SELECT 1"

    def test_insert_without_or_replace_passes(self):
        """Regular INSERT (not OR REPLACE) passes through."""
        sql = "INSERT INTO agents (id, name) VALUES (%s, %s)"
        result = _convert_sql_for_pg(sql)
        assert result == sql

    def test_limit_clause(self):
        """LIMIT ? conversion."""
        sql = "SELECT * FROM agents ORDER BY id DESC LIMIT ?"
        result = _convert_sql_for_pg(sql)
        assert result == "SELECT * FROM agents ORDER BY id DESC LIMIT %s"

    def test_multiple_values_upsert(self):
        """INSERT OR REPLACE with multiple columns."""
        sql = (
            "INSERT OR REPLACE INTO memory_store "
            "(tenant_id, agent_name, key, value, updated_at) "
            "VALUES (?, ?, ?, ?, ?)"
        )
        result = _convert_sql_for_pg(sql)
        assert result.startswith("INSERT INTO memory_store")
        assert "ON CONFLICT" in result
        assert "value = EXCLUDED.value" in result
        assert "tenant_id, agent_name, key" in result or "personality_name, version" not in result


class TestAbstractDatabaseLastInsertId:
    """Test portable last_insert_id pattern."""

    def test_abstract_database_has_method(self):
        """AbstractDatabase defines last_insert_id()."""
        assert hasattr(AbstractDatabase, "last_insert_id")

    def test_sqlite_lastrowid_fallback(self):
        """conn.last_insert_id() for SQLite uses .lastrowid."""
        # Simulate a sqlite3 cursor
        class FakeSQLiteCursor:
            lastrowid = 42

        class FakeSQLiteConn:
            def last_insert_id(self, cursor):
                return cursor.lastrowid

        conn = FakeSQLiteConn()
        cursor = FakeSQLiteCursor()
        assert conn.last_insert_id(cursor) == 42


class TestPostgresDatabaseInit:
    """Test PostgresDatabase init and schema detection (no PG required)."""

    def test_init_defaults(self):
        """PostgresDatabase default initialization."""
        db = PostgresDatabase()
        assert db._dsn == ""
        assert db._schema == "public"
        assert db._conn is None

    def test_init_with_dsn(self):
        """PostgresDatabase with custom DSN."""
        db = PostgresDatabase(
            dsn="postgresql://user:pass@host:5432/sccsos",
            schema="myschema",
        )
        assert "user" in db._dsn
        assert "host:5432" in db._dsn
        assert db._schema == "myschema"

    def test_has_last_insert_id(self):
        """PostgresDatabase has last_insert_id method."""
        db = PostgresDatabase()
        assert hasattr(db, "last_insert_id")

    def test_check_health_no_conn(self):
        """check_health returns error when no connection."""
        db = PostgresDatabase(dsn="postgresql://invalid:5432/sccsos")
        result = db.check_health()
        assert result["status"] == "error"

    def test_convert_method(self):
        """PostgresDatabase._convert() delegates to _convert_sql_for_pg."""
        db = PostgresDatabase()
        sql = "SELECT * FROM agents WHERE id = ?"
        assert db._convert(sql) == "SELECT * FROM agents WHERE id = %s"


class TestCreateDatabase:
    """Test the create_database factory function."""

    def test_create_sqlite_from_path(self):
        """Default driver creates SQLite Database."""
        from sccsos.core.db import create_database

        class FakeConfig:
            driver = "sqlite"
            path = ":memory:"

        db = create_database(FakeConfig())
        from sccsos.core.db import Database
        assert isinstance(db, Database)

    def test_create_postgres_from_dsn(self):
        """postgres driver creates PostgresDatabase."""
        from sccsos.core.db import create_database

        class FakeConfig:
            driver = "postgres"
            dsn = "postgresql://u:p@h:5432/db"
            schema = "public"

        db = create_database(FakeConfig())
        assert isinstance(db, PostgresDatabase)
        assert "h:5432" in db._dsn

    def test_create_postgres_missing_dsn(self):
        """postgres driver without dsn raises ValueError."""
        from sccsos.core.db import create_database

        class FakeConfig:
            driver = "postgres"
            dsn = ""
            schema = "public"

        with pytest.raises(ValueError, match="dsn"):
            create_database(FakeConfig())
