"""Database layer — SQLite persistence for sccsos.

Uses WAL mode for concurrent access. Schema created automatically
on first connection.
"""

from __future__ import annotations

import sqlite3
import threading
import logging
from pathlib import Path
from typing import Optional


logger = logging.getLogger("sccsos.database")


# ── Schema DDL ─────────────────────────────────────────────────────

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    name TEXT NOT NULL,
    spec TEXT NOT NULL,
    spec_version TEXT NOT NULL DEFAULT '1.0',
    status TEXT NOT NULL DEFAULT 'created',
    session_id TEXT,
    hermes_profile TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    paused_at TIMESTAMP,
    terminated_at TIMESTAMP,
    total_runtime_seconds INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS agent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    event TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    workflow_name TEXT NOT NULL,
    workflow_content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    trace_id TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS workflow_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    agent_name TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    duration_ms INTEGER,
    output TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_span_id TEXT,
    name TEXT NOT NULL,
    agent_name TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration_ms INTEGER,
    status TEXT,
    events TEXT DEFAULT '[]',
    UNIQUE(trace_id, span_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    agent_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    tool_name TEXT,
    model_name TEXT,
    tokens_used INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    duration_ms INTEGER,
    success BOOLEAN DEFAULT 1,
    detail TEXT
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_agent_events_agent ON agent_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_workflow_steps_run ON workflow_steps(run_id);
CREATE INDEX IF NOT EXISTS idx_traces_trace ON traces(trace_id);
CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_tenant ON agents(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id);

-- Persistent memory store (key-value, per tenant)
CREATE TABLE IF NOT EXISTS memory_store (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    agent_name TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ttl_seconds INTEGER DEFAULT 0,
    UNIQUE(tenant_id, agent_name, key)
);
"""


# ── Agent Row ↔ Dict helpers ──────────────────────────────────────

def _row_to_agent(row: sqlite3.Row) -> dict:
    return dict(row)


# ── Database ───────────────────────────────────────────────────────


class Database:
    """SQLite database with auto-schema creation.

    Thread-safe via check_same_thread=False + thread-local connections.
    """

    def __init__(self, db_path: str | Path = "./data/sccsos.db"):
        self._db_path = Path(db_path)
        self._local = threading.local()
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._db_path

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local connection (internal use)."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def get_conn(self) -> sqlite3.Connection:
        """Get a thread-local database connection (public API)."""
        return self._get_conn()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a single SQL statement and return cursor.

        Thread-safe convenience wrapper over ``get_conn().execute()``.
        For multi-statement scripts, use :meth:`executescript`.
        """
        return self.get_conn().execute(sql, params)

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        """Execute and fetch one row. Returns None if no results.

        Convenience method combining execute + fetchone.
        """
        return self.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Execute and fetch all rows.

        Convenience method combining execute + fetchall.
        """
        return self.execute(sql, params).fetchall()

    def executescript(self, sql: str) -> None:
        """Execute a multi-statement SQL script with commit."""
        conn = self.get_conn()
        conn.executescript(sql)
        conn.commit()

    def initialize(self) -> None:
        """Create schema if not exists. Applies migrations for existing DBs."""
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        # ── Schema migrations (for existing databases) ──────────
        self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Apply incremental schema migrations."""
        try:
            # Migration v1: Add tenant_id columns
            for table in ('agents', 'audit_log', 'workflow_runs'):
                col_info = conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
                col_names = [c[1] for c in col_info]
                if 'tenant_id' not in col_names:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'"
                    )
                    conn.commit()
            # Migration v2: Create memory_store table
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            if 'memory_store' not in tables:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS memory_store (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tenant_id TEXT NOT NULL DEFAULT 'default',
                        agent_name TEXT NOT NULL,
                        key TEXT NOT NULL,
                        value TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(tenant_id, agent_name, key)
                    )
                """)
                conn.commit()
            # Migration v3: Add ttl_seconds to memory_store
            col_info = conn.execute(
                "PRAGMA table_info(memory_store)"
            ).fetchall()
            col_names = [c[1] for c in col_info]
            if 'ttl_seconds' not in col_names:
                conn.execute(
                    "ALTER TABLE memory_store ADD COLUMN ttl_seconds INTEGER DEFAULT 0"
                )
                conn.commit()
        except Exception as e:
            logger.warning("Migration failed (schema may be compatible): %s", e)

    def close(self) -> None:
        """Close the connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    # ── Agent CRUD ──────────────────────────────────────────────

    def insert_agent(self, agent_id: str, name: str, spec_json: str,
                     spec_version: str = "1.0",
                     hermes_profile: str = "sccsos",
                     tenant_id: str = "default") -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO agents (id, tenant_id, name, spec, spec_version, hermes_profile)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (agent_id, tenant_id, name, spec_json, spec_version, hermes_profile),
        )
        conn.commit()

    def update_agent_status(self, agent_id: str, status: str,
                            session_id: Optional[str] = None,
                            error: Optional[str] = None) -> None:
        conn = self._get_conn()
        now_sql = "datetime('now')"

        updates = {"status": status}
        if session_id:
            updates["session_id"] = session_id
        if error:
            updates["last_error"] = error

        if status == "running":
            updates["started_at"] = now_sql
        elif status == "paused":
            updates["paused_at"] = now_sql
        elif status == "terminated":
            updates["terminated_at"] = now_sql
        elif status == "failed":
            updates["error_count"] = "error_count + 1"

        set_clauses = []
        params = []
        for key, value in updates.items():
            if value == now_sql:
                set_clauses.append(f"{key} = {now_sql}")
            elif key == "error_count":
                set_clauses.append(f"{key} = {value}")
            else:
                set_clauses.append(f"{key} = ?")
                params.append(value)

        params.append(agent_id)
        sql = f"UPDATE agents SET {', '.join(set_clauses)} WHERE id = ?"
        conn.execute(sql, params)
        conn.commit()

    def get_agent(self, agent_id: str) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM agents WHERE id = ?", (agent_id,)
        ).fetchone()
        return _row_to_agent(row) if row else None

    def get_agent_by_name(self, name: str,
                          tenant_id: str = "default") -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute(
            """SELECT * FROM agents WHERE name = ? AND tenant_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (name, tenant_id),
        ).fetchone()
        return _row_to_agent(row) if row else None

    def list_agents(self, status: Optional[str] = None,
                    tenant_id: str = "default") -> list[dict]:
        conn = self._get_conn()
        if status:
            rows = conn.execute(
                """SELECT * FROM agents WHERE status = ? AND tenant_id = ?
                   ORDER BY created_at DESC""",
                (status, tenant_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM agents WHERE tenant_id = ?
                   ORDER BY created_at DESC""",
                (tenant_id,),
            ).fetchall()
        return [_row_to_agent(r) for r in rows]

    # ── Agent Events ────────────────────────────────────────────

    def add_event(self, agent_id: str, event: str,
                  detail: Optional[str] = None) -> int:
        conn = self._get_conn()
        cursor = conn.execute(
            "INSERT INTO agent_events (agent_id, event, detail) VALUES (?, ?, ?)",
            (agent_id, event, detail),
        )
        conn.commit()
        return cursor.lastrowid

    def get_events(self, agent_id: str, limit: int = 50) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM agent_events
               WHERE agent_id = ? ORDER BY timestamp DESC LIMIT ?""",
            (agent_id, limit),
        ).fetchall()
        return [_row_to_agent(r) for r in rows]

    # ── Health ──────────────────────────────────────────────────

    def check_health(self) -> dict:
        """Return database health info."""
        try:
            conn = self._get_conn()
            conn.execute("SELECT 1").fetchone()
            agent_count = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
            return {
                "status": "ok",
                "path": str(self._db_path),
                "agent_count": agent_count,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
            }
