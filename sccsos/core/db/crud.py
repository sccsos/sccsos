"""Database CRUD operations — single source of truth for all SQL access.

All raw SQL is encapsulated in this module. Callers (step_executor, session,
workflow/engine, personality_version, runtime_workflow) must use these
functions instead of calling conn.execute() directly.
"""

from __future__ import annotations

from typing import Optional


def row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row)


# ═══════════════════════════════════════════════════════════════════════
# Agent CRUD
# ═══════════════════════════════════════════════════════════════════════


def insert_agent(conn, agent_id: str, name: str, spec_json: str,
                 spec_version: str = "1.0",
                 hermes_profile: str = "sccsos",
                 tenant_id: str = "default") -> None:
    conn.execute(
        "INSERT INTO agents (id, tenant_id, name, spec, spec_version, hermes_profile) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (agent_id, tenant_id, name, spec_json, spec_version, hermes_profile),
    )
    conn.commit()


def update_agent_status(conn, agent_id: str, status: str,
                        session_id: Optional[str] = None,
                        error: Optional[str] = None) -> None:
    now_sql = "datetime('now')"
    updates: dict[str, str] = {"status": status}
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
    conn.execute(f"UPDATE agents SET {', '.join(set_clauses)} WHERE id = ?", params)
    conn.commit()


def get_agent(conn, agent_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    return row_to_dict(row) if row else None


def get_agent_by_name(conn, name: str, tenant_id: str = "default") -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM agents WHERE name = ? AND tenant_id = ? ORDER BY created_at DESC LIMIT 1",
        (name, tenant_id),
    ).fetchone()
    return row_to_dict(row) if row else None


def list_agents(conn, status: Optional[str] = None,
                tenant_id: str = "default") -> list[dict]:
    if status:
        rows = conn.execute(
            "SELECT * FROM agents WHERE status = ? AND tenant_id = ? ORDER BY created_at DESC",
            (status, tenant_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM agents WHERE tenant_id = ? ORDER BY created_at DESC",
            (tenant_id,),
        ).fetchall()
    return [row_to_dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════
# Agent Events
# ═══════════════════════════════════════════════════════════════════════


def add_event(conn, agent_id: str, event: str,
              detail: Optional[str] = None) -> int:
    cursor = conn.execute(
        "INSERT INTO agent_events (agent_id, event, detail) VALUES (?, ?, ?)",
        (agent_id, event, detail),
    )
    conn.commit()
    return conn.last_insert_id(cursor) if hasattr(conn, 'last_insert_id') else cursor.lastrowid


def get_events(conn, agent_id: str, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM agent_events WHERE agent_id = ? ORDER BY timestamp DESC LIMIT ?",
        (agent_id, limit),
    ).fetchall()
    return [row_to_dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════
# Workflow Steps
# ═══════════════════════════════════════════════════════════════════════


def insert_workflow_step(conn, run_id: str, step_id: str, agent_name: str,
                         status: str, started_at: str,
                         finished_at: Optional[str] = None) -> None:
    """Insert a workflow step record."""
    if finished_at:
        conn.execute(
            """INSERT INTO workflow_steps (run_id, step_id, agent_name, status, started_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, step_id, agent_name, status, started_at, finished_at),
        )
    else:
        conn.execute(
            """INSERT INTO workflow_steps (run_id, step_id, agent_name, status, started_at)
               VALUES (?, ?, ?, ?, ?)""",
            (run_id, step_id, agent_name, status, started_at),
        )


def update_workflow_step(conn, run_id: str, step_id: str, *,
                         status: str,
                         finished_at: str,
                         duration_ms: int,
                         output: Optional[str] = None,
                         error: Optional[str] = None) -> None:
    """Update a workflow step's completion status."""
    if error or status == "failed":
        conn.execute(
            """UPDATE workflow_steps SET status = ?, finished_at = ?, duration_ms = ?, error = ?
               WHERE run_id = ? AND step_id = ?""",
            (status, finished_at, duration_ms, (error or "")[:500], run_id, step_id),
        )
    else:
        conn.execute(
            """UPDATE workflow_steps SET status = ?, finished_at = ?, duration_ms = ?, output = ?
               WHERE run_id = ? AND step_id = ?""",
            (status, finished_at, duration_ms, (output or "")[:1000], run_id, step_id),
        )


def get_workflow_steps(conn, run_id: str) -> list[dict]:
    """Get all steps for a workflow run, ordered by insertion."""
    rows = conn.execute(
        "SELECT * FROM workflow_steps WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    return [row_to_dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════
# Workflow Runs
# ═══════════════════════════════════════════════════════════════════════


def insert_workflow_run(conn, run_id: str, workflow_name: str,
                        workflow_content: str) -> None:
    """Insert a new workflow run record."""
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, workflow_content, status) "
        "VALUES (?, ?, ?, 'running')",
        (run_id, workflow_name, workflow_content),
    )


def update_workflow_run_status(conn, run_id: str, status: str,
                               finished_at: Optional[str] = None,
                               error: Optional[str] = None) -> None:
    """Update the status of a workflow run."""
    if error:
        conn.execute(
            "UPDATE workflow_runs SET status = ?, error = ? WHERE id = ?",
            (status, error, run_id),
        )
    elif finished_at:
        conn.execute(
            "UPDATE workflow_runs SET status = ?, finished_at = ? WHERE id = ?",
            (status, finished_at, run_id),
        )
    else:
        conn.execute(
            "UPDATE workflow_runs SET status = ? WHERE id = ?",
            (status, run_id),
        )


def get_workflow_run(conn, run_id: str,
                     tenant_id: Optional[str] = None) -> Optional[dict]:
    """Get a single workflow run by ID, optionally scoped to tenant."""
    if tenant_id:
        row = conn.execute(
            "SELECT * FROM workflow_runs WHERE id = ? AND tenant_id = ?",
            (run_id, tenant_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM workflow_runs WHERE id = ?", (run_id,)
        ).fetchone()
    return row_to_dict(row) if row else None


def list_workflow_runs(conn, limit: int = 20,
                       tenant_id: Optional[str] = None) -> list[dict]:
    """List recent workflow runs."""
    if tenant_id:
        rows = conn.execute(
            "SELECT * FROM workflow_runs WHERE tenant_id = ? "
            "ORDER BY started_at DESC LIMIT ?",
            (tenant_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM workflow_runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [row_to_dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════
# Session CRUD
# ═══════════════════════════════════════════════════════════════════════


def insert_session(conn, session_id: str, agent_name: str,
                   tenant_id: str, created_at: str) -> None:
    """Create a new agent session."""
    conn.execute(
        """INSERT INTO agent_sessions
           (id, agent_name, tenant_id, status, created_at, updated_at)
           VALUES (?, ?, ?, 'active', ?, ?)""",
        (session_id, agent_name, tenant_id, created_at, created_at),
    )


def update_session(conn, session_id: str, *,
                   status: Optional[str] = None,
                   updated_at: Optional[str] = None,
                   context_summary: Optional[str] = None) -> None:
    """Update session fields selectively."""
    if status and updated_at:
        conn.execute(
            "UPDATE agent_sessions SET status = ?, updated_at = ? WHERE id = ?",
            (status, updated_at, session_id),
        )
    elif updated_at:
        conn.execute(
            "UPDATE agent_sessions SET updated_at = ? WHERE id = ?",
            (updated_at, session_id),
        )
    elif context_summary is not None:
        conn.execute(
            "UPDATE agent_sessions SET context_summary = ? WHERE id = ?",
            (context_summary, session_id),
        )


def insert_session_message(conn, session_id: str, role: str,
                           content: str, tokens: int,
                           created_at: str) -> int:
    """Append a message to a session. Returns the message ID."""
    cursor = conn.execute(
        """INSERT INTO session_messages
           (session_id, role, content, tokens, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (session_id, role, content, tokens, created_at),
    )
    return conn.last_insert_id(cursor) if hasattr(conn, 'last_insert_id') else cursor.lastrowid


# ═══════════════════════════════════════════════════════════════════════
# Personality Version
# ═══════════════════════════════════════════════════════════════════════


def insert_personality_version(conn, personality_name: str, version: str,
                               content: str, change_log: str,
                               created_at: str) -> None:
    """Save a snapshot of a personality version."""
    conn.execute(
        """INSERT OR REPLACE INTO personality_versions
           (personality_name, version, content, change_log, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (personality_name, version, content, change_log, created_at),
    )


# ═══════════════════════════════════════════════════════════════════════
# Event Queue
# ═══════════════════════════════════════════════════════════════════════


def insert_event_queue_item(conn, event: str, data: str) -> None:
    """Persist an event to the durable event queue."""
    conn.execute(
        "INSERT INTO event_queue (event, data) VALUES (?, ?)",
        (event, data),
    )


# ═══════════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════════


def check_health(conn, db_path: str) -> dict:
    try:
        conn.execute("SELECT 1").fetchone()
        agent_count = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        return {"status": "ok", "path": db_path, "agent_count": agent_count}
    except Exception as e:
        return {"status": "error", "error": str(e)}
