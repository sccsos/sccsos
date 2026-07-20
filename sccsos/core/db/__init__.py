"""Database layer — multi-backend persistence for sccsos.

Supports SQLite (default) and PostgreSQL (optional ``sccsos[pg]`` extras).
New backends implement ``AbstractDatabase`` and are registered in
``create_database()``.

Usage::

    # Auto-detect from config
    from sccsos.core.db import create_database
    db = create_database(cfg.database)

    # Direct SQLite (backward compatible)
    from sccsos.core.db import Database
    db = Database("./data/sccsos.db")
"""

from __future__ import annotations

import re
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

# ── SQL dialect conversion ──────────────────────────────────────────
# Convert SQLite-placeholder SQL to PostgreSQL-compatible syntax.
# Used by PostgresDatabase to run the same crud.py functions.
_PG_PARAM_RE = re.compile(r"(?<![:(])'(?=[^']*')")
# Actually we just convert ? to %s — safe for sccsos SQL patterns
_SQLITE_QMARK_RE = re.compile(r"\?")
_SQLITE_DATETIME_NOW_RE = re.compile(r"datetime\('now'\)", re.IGNORECASE)
_SQLITE_INSERT_OR_REPLACE_RE = re.compile(
    r"INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)", re.IGNORECASE
)
# Match INSERT OR REPLACE INTO personality_versions (...)
# to extract table_name and columns for UPSERT conversion
_SQLITE_INSERT_OR_REPLACE_FULL_RE = re.compile(
    r"INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\((.+?)\)\s*VALUES\s*\((.+?)\)",
    re.IGNORECASE | re.DOTALL,
)


def _convert_sql_for_pg(sql: str) -> str:
    """Convert SQLite SQL to PostgreSQL-compatible syntax.

    Handles:
    - ``?`` → ``%s`` (parameter placeholder style)
    - ``datetime('now')`` → ``NOW()``
    - ``INSERT OR REPLACE`` → ``INSERT ... ON CONFLICT DO UPDATE SET ...``
    """
    # ? → %s (parameter style)
    sql = _SQLITE_QMARK_RE.sub(r"%s", sql)
    # datetime('now') → NOW()
    sql = _SQLITE_DATETIME_NOW_RE.sub("NOW()", sql)
    # INSERT OR REPLACE → UPSERT
    match = _SQLITE_INSERT_OR_REPLACE_FULL_RE.search(sql)
    if match:
        table = match.group(1)
        columns = [c.strip() for c in match.group(2).split(",")]
        # Build the ON CONFLICT clause
        # Determine conflict columns from UNIQUE constraints
        # For personality_versions it's (personality_name, version)
        if "personality_versions" in table:
            conflict_cols = ["personality_name", "version"]
        elif "memory_store" in table:
            conflict_cols = ["tenant_id", "agent_name", "key"]
        else:
            conflict_cols = [columns[0]]  # fallback to first column
        # Build column = EXCLUDED.col pairs
        update_set = ", ".join(
            f"{col} = EXCLUDED.{col}"
            for col in columns
            if col not in conflict_cols
        )
        if not update_set:
            update_set = f"{columns[-1]} = EXCLUDED.{columns[-1]}"
        # Rewrite the INSERT
        placeholders = ", ".join(f"%s" for _ in columns)
        col_names_str = ", ".join(columns)
        conflict_str = ", ".join(conflict_cols)
        pg_sql = (
            f"INSERT INTO {table} ({col_names_str}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_str}) DO UPDATE SET {update_set}"
        )
        sql = pg_sql
    return sql


class AbstractDatabase(ABC):
    """Abstract interface for database operations.

    All return types are generic (``Any``) to support multiple backends.
    Concrete implementations return row-like objects that support
    ``__getitem__`` / ``__setitem__`` / ``dict()`` conversion.
    """

    @abstractmethod
    def execute(self, sql: str, params: tuple = ()) -> Any:
        """Execute a SQL statement, return cursor-like object."""
        ...

    @abstractmethod
    def fetchone(self, sql: str, params: tuple = ()) -> Any:
        """Execute a query and return one row, or None."""
        ...

    @abstractmethod
    def fetchall(self, sql: str, params: tuple = ()) -> list[Any]:
        """Execute a query and return all matching rows."""
        ...

    @abstractmethod
    def executescript(self, sql: str) -> None:
        """Execute a multi-statement SQL script."""
        ...

    @abstractmethod
    def commit(self) -> None:
        """Commit the current transaction."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Close the database connection."""
        ...

    @abstractmethod
    def initialize(self) -> None:
        """Create schema and run migrations on first use."""
        ...

    @abstractmethod
    def check_health(self) -> dict:
        """Return health status dict for monitoring."""
        ...

    def row_to_dict(self, row: Any) -> dict:
        """Convert a backend-specific row to a plain dict."""
        return dict(row)

    def last_insert_id(self, cursor: Any) -> int:
        """Return the last inserted row ID.

        Default implementation uses ``cursor.lastrowid`` (SQLite).
        Subclasses (e.g. PostgresDatabase) override with ``RETURNING``.
        """
        return cursor.lastrowid

    # ── Convenience CRUD helpers (delegate to crud module) ──────

    def insert_agent(self, agent_id: str, name: str, spec_json: str,
                     spec_version: str = "1.0",
                     hermes_profile: str = "sccsos",
                     tenant_id: str = "default") -> None:
        from sccsos.core.db.crud import insert_agent as _do
        _do(self, agent_id, name, spec_json, spec_version, hermes_profile, tenant_id)

    def update_agent_status(self, agent_id: str, status: str,
                            session_id: Optional[str] = None,
                            error: Optional[str] = None) -> None:
        from sccsos.core.db.crud import update_agent_status as _do
        _do(self, agent_id, status, session_id, error)

    def get_agent(self, agent_id: str) -> Optional[dict]:
        from sccsos.core.db.crud import get_agent as _do
        return _do(self, agent_id)

    def get_agent_by_name(self, name: str,
                          tenant_id: str = "default") -> Optional[dict]:
        from sccsos.core.db.crud import get_agent_by_name as _do
        return _do(self, name, tenant_id)

    def list_agents(self, status: Optional[str] = None,
                    tenant_id: str = "default") -> list[dict]:
        from sccsos.core.db.crud import list_agents as _do
        return _do(self, status, tenant_id)

    def add_event(self, agent_id: str, event: str,
                  detail: Optional[str] = None) -> int:
        from sccsos.core.db.crud import add_event as _do
        return _do(self, agent_id, event, detail)

    def get_events(self, agent_id: str, limit: int = 50) -> list[dict]:
        from sccsos.core.db.crud import get_events as _do
        return _do(self, agent_id, limit)


# ═══════════════════════════════════════════════════════════════════════
# SQLite backend
# ═══════════════════════════════════════════════════════════════════════


class Database(AbstractDatabase):
    """SQLite database with auto-schema creation.

    Thread-safe via ``check_same_thread=False`` + ``threading.Lock``.
    """

    def __init__(self, db_path: str | Path = "./data/sccsos.db"):
        import sqlite3
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._sqlite3 = sqlite3

    @property
    def path(self) -> Path:
        return self._db_path

    def _get_conn(self):
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = self._sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.row_factory = self._sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
            self._conn = conn
        return self._conn

    def get_conn(self):
        return self._get_conn()

    def execute(self, sql: str, params: tuple = ()):
        with self._lock:
            return self.get_conn().execute(sql, params)

    def fetchone(self, sql: str, params: tuple = ()):
        with self._lock:
            return self.get_conn().execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list:
        with self._lock:
            return self.get_conn().execute(sql, params).fetchall()

    def executescript(self, sql: str) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.executescript(sql)
            conn.commit()

    def commit(self) -> None:
        with self._lock:
            self._get_conn().commit()

    def initialize(self) -> None:
        from sccsos.core.db.schema import SCHEMA_SQL, apply_migrations
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        apply_migrations(conn)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def check_health(self) -> dict:
        from sccsos.core.db.crud import check_health as _check_health
        return _check_health(self._get_conn(), str(self._db_path))


# ═══════════════════════════════════════════════════════════════════════
# PostgreSQL backend (optional)
# ═══════════════════════════════════════════════════════════════════════


class PostgresDatabase(AbstractDatabase):
    """PostgreSQL backend using ``psycopg2``.

    Requires ``sccsos[pg]`` extras::

        pip install sccsos[pg]

    SQL conversion is applied automatically to handle ``?`` placeholders,
    ``datetime('now')``, and ``INSERT OR REPLACE`` used by crud.py.
    """

    def __init__(self, dsn: str = "", schema: str = "public"):
        self._dsn = dsn
        self._schema = schema
        self._lock = threading.Lock()
        self._conn: Any = None

    def _get_conn(self):
        if self._conn is None:
            import psycopg2

            conn = psycopg2.connect(self._dsn)
            conn.autocommit = False
            self._conn = conn
            with conn.cursor() as cur:
                cur.execute(f"SET search_path TO {self._schema}")
        return self._conn

    def _convert(self, sql: str) -> str:
        """Convert SQLite SQL to PostgreSQL dialect."""
        return _convert_sql_for_pg(sql)

    def execute(self, sql: str, params: tuple = ()):
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            pg_sql = self._convert(sql)
            # Add RETURNING id for INSERT statements to support lastrowid
            if pg_sql.strip().upper().startswith("INSERT") and "RETURNING" not in pg_sql.upper():
                pg_sql = pg_sql.rstrip(";") + " RETURNING id"
            cur.execute(pg_sql, params)
            return cur

    def last_insert_id(self, cursor: Any) -> int:
        """PostgreSQL: read the returned id from RETURNING clause."""
        try:
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def fetchone(self, sql: str, params: tuple = ()):
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            pg_sql = self._convert(sql)
            cur.execute(pg_sql, params)
            row = cur.fetchone()
            if row is not None and cur.description:
                desc = [d[0] for d in cur.description]
                return dict(zip(desc, row))
            return None

    def fetchall(self, sql: str, params: tuple = ()) -> list:
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            pg_sql = self._convert(sql)
            cur.execute(pg_sql, params)
            rows = cur.fetchall()
            if rows and cur.description:
                desc = [d[0] for d in cur.description]
                return [dict(zip(desc, row)) for row in rows]
            return list(rows) if rows else []

    def executescript(self, sql: str) -> None:
        """Execute multi-statement SQL (uses execute for PostgreSQL)."""
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            pg_sql = self._convert(sql)
            cur.execute(pg_sql)
            conn.commit()

    def commit(self) -> None:
        with self._lock:
            self._get_conn().commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def initialize(self) -> None:
        """Create schema from SQL script."""
        from sccsos.core.db.schema import POSTGRES_SCHEMA_SQL

        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
            cur.execute(f"SET search_path TO {self._schema}")
            cur.execute(POSTGRES_SCHEMA_SQL)
        conn.commit()

    def check_health(self) -> dict:
        try:
            with self._lock:
                conn = self._get_conn()
                cur = conn.cursor()
                cur.execute("SELECT 1")
            masked_dsn = (
                self._dsn.split("@")[-1] if "@" in self._dsn else self._dsn
            )
            return {"status": "ok", "dsn": masked_dsn}
        except Exception as e:
            return {"status": "error", "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════════════


def create_database(config) -> AbstractDatabase:
    """Create a database backend from config.

    Args:
        config: A ``DatabaseConfig`` dataclass instance.

    Returns:
        ``SqliteDatabase`` or ``PostgresDatabase`` based on ``config.driver``.
    """
    driver = getattr(config, "driver", "sqlite")
    if driver == "postgres":
        dsn = config.dsn or ""
        if not dsn:
            raise ValueError(
                "PostgreSQL driver requires 'dsn' in database config. "
                "Example: postgresql://user:pass@host:5432/sccsos"
            )
        return PostgresDatabase(dsn=dsn, schema=getattr(config, "schema", "public"))
    # Default: SQLite
    return Database(db_path=config.path)
