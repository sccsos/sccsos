"""Database schema DDL and migration utilities.

Extracted from ``database.py`` for modularity.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("sccsos.database.schema")


# ── Schema DDL (SQLite) ────────────────────────────────────────────

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
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

-- Session persistence
CREATE TABLE IF NOT EXISTS agent_sessions (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    context_summary TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS session_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tokens INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES agent_sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_session_messages_session
    ON session_messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_agent
    ON agent_sessions(tenant_id, agent_name, status);

-- Persistent memory store
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

-- Persistent event queue
CREATE TABLE IF NOT EXISTS event_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Personality version management
CREATE TABLE IF NOT EXISTS personality_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personality_name TEXT NOT NULL,
    version TEXT NOT NULL,
    content TEXT NOT NULL,
    change_log TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(personality_name, version)
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id TEXT NOT NULL UNIQUE,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    msg_type TEXT NOT NULL DEFAULT 'broadcast',
    payload_json TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'incoming',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Migration v7: agent_messages table (Phase 7)
CREATE TABLE IF NOT EXISTS _schema_version (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personality_name TEXT NOT NULL,
    version TEXT NOT NULL,
    content TEXT NOT NULL,
    change_log TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(personality_name, version)
);

-- Skill marketplace
CREATE TABLE IF NOT EXISTS skill_market (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '1.0',
    type TEXT NOT NULL DEFAULT 'personality',
    description TEXT DEFAULT '',
    author TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    filename TEXT NOT NULL,
    content TEXT NOT NULL,
    source_url TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    review_notes TEXT DEFAULT '',
    install_count INTEGER DEFAULT 0,
    category TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, version)
);

CREATE TABLE IF NOT EXISTS installed_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT NOT NULL,
    installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, type)
);

-- Review comments: threaded review feedback
CREATE TABLE IF NOT EXISTS review_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT NOT NULL,
    skill_version TEXT NOT NULL DEFAULT '1.0',
    reviewer TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL,
    parent_id INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_review_comments_skill
    ON review_comments(skill_name, skill_version);

-- Review audit trail: every status change recorded
CREATE TABLE IF NOT EXISTS review_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT NOT NULL,
    skill_version TEXT NOT NULL DEFAULT '1.0',
    action TEXT NOT NULL,
    reviewer TEXT NOT NULL DEFAULT '',
    old_status TEXT NOT NULL DEFAULT '',
    new_status TEXT NOT NULL DEFAULT '',
    detail TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_review_history_skill
    ON review_history(skill_name, skill_version);

-- Skill ratings: star ratings (1-5) per user per skill
CREATE TABLE IF NOT EXISTS skill_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT NOT NULL,
    skill_version TEXT NOT NULL DEFAULT '1.0',
    user_id TEXT NOT NULL,
    score INTEGER NOT NULL CHECK(score >= 1 AND score <= 5),
    comment TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(skill_name, skill_version, user_id)
);
CREATE INDEX IF NOT EXISTS idx_skill_ratings_skill
    ON skill_ratings(skill_name, skill_version);
CREATE INDEX IF NOT EXISTS idx_skill_ratings_score
    ON skill_ratings(score);
"""

# ── PostgreSQL schema (without SQLite-specific features) ───────────

POSTGRES_SCHEMA_SQL = """\
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
    id SERIAL PRIMARY KEY,
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
    id SERIAL PRIMARY KEY,
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
    id SERIAL PRIMARY KEY,
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
    id SERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    agent_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    tool_name TEXT,
    model_name TEXT,
    tokens_used INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    duration_ms INTEGER,
    success BOOLEAN DEFAULT TRUE,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    context_summary TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS session_messages (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tokens INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES agent_sessions(id)
);

CREATE TABLE IF NOT EXISTS memory_store (
    id SERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    agent_name TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ttl_seconds INTEGER DEFAULT 0,
    UNIQUE(tenant_id, agent_name, key)
);

CREATE TABLE IF NOT EXISTS event_queue (
    id SERIAL PRIMARY KEY,
    event TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    consumed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id SERIAL PRIMARY KEY,
    msg_id TEXT NOT NULL UNIQUE,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    msg_type TEXT NOT NULL DEFAULT 'broadcast',
    payload_json TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'incoming',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS personality_versions (
    id SERIAL PRIMARY KEY,
    personality_name TEXT NOT NULL,
    version TEXT NOT NULL,
    content TEXT NOT NULL,
    change_log TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(personality_name, version)
);

CREATE TABLE IF NOT EXISTS skill_market (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '1.0',
    type TEXT NOT NULL DEFAULT 'personality',
    description TEXT DEFAULT '',
    author TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    filename TEXT NOT NULL,
    content TEXT NOT NULL,
    source_url TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    review_notes TEXT DEFAULT '',
    install_count INTEGER DEFAULT 0,
    category TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, version)
);

CREATE TABLE IF NOT EXISTS installed_skills (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT NOT NULL,
    installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, type)
);

-- Skill ratings (PostgreSQL)
CREATE TABLE IF NOT EXISTS skill_ratings (
    id SERIAL PRIMARY KEY,
    skill_name TEXT NOT NULL,
    skill_version TEXT NOT NULL DEFAULT '1.0',
    user_id TEXT NOT NULL,
    score INTEGER NOT NULL CHECK(score >= 1 AND score <= 5),
    comment TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(skill_name, skill_version, user_id)
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
CREATE INDEX IF NOT EXISTS idx_session_messages_session ON session_messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_agent ON agent_sessions(tenant_id, agent_name, status);
"""


# ── Migration helpers ──────────────────────────────────────────────


def apply_migrations(conn) -> None:
    """Apply incremental schema migrations for existing databases."""
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

        # Migration v4: Create agent_sessions and session_messages
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        if 'agent_sessions' not in tables:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    context_summary TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS session_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tokens INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES agent_sessions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_session_messages_session
                    ON session_messages(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_agent_sessions_agent
                    ON agent_sessions(tenant_id, agent_name, status);
            """)
            conn.commit()

        # Migration v5: Add review_notes to skill_market
        col_info = conn.execute(
            "PRAGMA table_info(skill_market)"
        ).fetchall()
        col_names = [c[1] for c in col_info]
        if 'review_notes' not in col_names:
            conn.execute(
                "ALTER TABLE skill_market ADD COLUMN review_notes TEXT DEFAULT ''"
            )
            conn.commit()

        # Migration v6: Create tenant_quotas table
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        if 'tenant_quotas' not in tables:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tenant_quotas (
                    tenant_id TEXT PRIMARY KEY,
                    max_agents INTEGER NOT NULL DEFAULT 10,
                    max_tokens_per_day INTEGER NOT NULL DEFAULT 500000,
                    max_cost_per_day REAL NOT NULL DEFAULT 10.0,
                    max_cost_total REAL NOT NULL DEFAULT 100.0,
                    max_memory_entries INTEGER NOT NULL DEFAULT 10000,
                    max_storage_mb INTEGER NOT NULL DEFAULT 1024,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()

        # Migration v7: Create skill_ratings table
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        if 'skill_ratings' not in tables:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS skill_ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_name TEXT NOT NULL,
                    skill_version TEXT NOT NULL DEFAULT '1.0',
                    user_id TEXT NOT NULL,
                    score INTEGER NOT NULL CHECK(score >= 1 AND score <= 5),
                    comment TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(skill_name, skill_version, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_skill_ratings_skill
                    ON skill_ratings(skill_name, skill_version);
                CREATE INDEX IF NOT EXISTS idx_skill_ratings_score
                    ON skill_ratings(score);
            """)
            conn.commit()

        # Migration v8: Add install_count and category to skill_market
        col_info = conn.execute(
            "PRAGMA table_info(skill_market)"
        ).fetchall()
        col_names = [c[1] for c in col_info]
        if 'install_count' not in col_names:
            conn.execute(
                "ALTER TABLE skill_market ADD COLUMN install_count INTEGER DEFAULT 0"
            )
            conn.commit()
        if 'category' not in col_names:
            conn.execute(
                "ALTER TABLE skill_market ADD COLUMN category TEXT DEFAULT ''"
            )
            conn.commit()
    except Exception as e:
        logger.warning("Migration failed (schema may be compatible): %s", e)
