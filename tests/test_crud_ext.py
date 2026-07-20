"""Tests for extended CRUD functions — workflow steps, runs, sessions, personality, events."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from sccsos.core.db import Database
from sccsos.core.db import crud
from sccsos.core.db.schema import SCHEMA_SQL


@pytest.fixture
def db():
    """In-memory SQLite database with full schema."""
    database = Database(":memory:")
    conn = database.get_conn()
    conn.executescript(SCHEMA_SQL)
    yield database
    database.close()


class TestWorkflowStepCRUD:
    """CRUD operations for workflow_steps table."""

    def test_insert_and_get_steps(self, db):
        conn = db.get_conn()
        crud.insert_workflow_step(conn, "run-1", "step-1", "agent-a", "running", "2026-01-01T00:00:00")
        crud.insert_workflow_step(conn, "run-1", "step-2", "agent-b", "running", "2026-01-01T00:01:00")

        steps = crud.get_workflow_steps(conn, "run-1")
        assert len(steps) == 2
        assert steps[0]["step_id"] == "step-1"
        assert steps[1]["step_id"] == "step-2"

    def test_insert_with_finished_at(self, db):
        conn = db.get_conn()
        crud.insert_workflow_step(conn, "run-2", "step-1", "agent-a", "skipped",
                                   "2026-01-01T00:00:00", finished_at="2026-01-01T00:00:05")
        steps = crud.get_workflow_steps(conn, "run-2")
        assert steps[0]["finished_at"] is not None

    def test_update_step_completed(self, db):
        conn = db.get_conn()
        crud.insert_workflow_step(conn, "run-3", "step-1", "agent-a", "running", "2026-01-01T00:00:00")
        crud.update_workflow_step(conn, "run-3", "step-1",
                                   status="completed", finished_at="2026-01-01T00:00:10",
                                   duration_ms=10000, output="done")
        steps = crud.get_workflow_steps(conn, "run-3")
        assert steps[0]["status"] == "completed"
        assert steps[0]["duration_ms"] == 10000

    def test_update_step_failed(self, db):
        conn = db.get_conn()
        crud.insert_workflow_step(conn, "run-4", "step-1", "agent-a", "running", "2026-01-01T00:00:00")
        crud.update_workflow_step(conn, "run-4", "step-1",
                                   status="failed", finished_at="2026-01-01T00:00:05",
                                   duration_ms=5000, error="timeout")
        steps = crud.get_workflow_steps(conn, "run-4")
        assert steps[0]["status"] == "failed"
        assert "timeout" in steps[0]["error"]

    def test_empty_run_returns_empty(self, db):
        conn = db.get_conn()
        steps = crud.get_workflow_steps(conn, "nonexistent")
        assert steps == []


class TestWorkflowRunCRUD:
    """CRUD operations for workflow_runs table."""

    def test_insert_and_get(self, db):
        conn = db.get_conn()
        crud.insert_workflow_run(conn, "wf-1", "test-workflow", '{"name": "test"}')
        row = crud.get_workflow_run(conn, "wf-1")
        assert row is not None
        assert row["workflow_name"] == "test-workflow"
        assert row["status"] == "running"

    def test_get_nonexistent(self, db):
        conn = db.get_conn()
        assert crud.get_workflow_run(conn, "ghost") is None

    def test_get_with_tenant(self, db):
        conn = db.get_conn()
        crud.insert_workflow_run(conn, "wf-2", "test", '{}')
        assert crud.get_workflow_run(conn, "wf-2", tenant_id="default") is not None
        assert crud.get_workflow_run(conn, "wf-2", tenant_id="other") is None

    def test_update_status_completed(self, db):
        conn = db.get_conn()
        crud.insert_workflow_run(conn, "wf-3", "test", '{}')
        crud.update_workflow_run_status(conn, "wf-3", "completed", finished_at="2026-01-01T00:00:00")
        row = crud.get_workflow_run(conn, "wf-3")
        assert row["status"] == "completed"
        assert row["finished_at"] is not None

    def test_update_status_failed(self, db):
        conn = db.get_conn()
        crud.insert_workflow_run(conn, "wf-4", "test", '{}')
        crud.update_workflow_run_status(conn, "wf-4", "failed", error="Something broke")
        row = crud.get_workflow_run(conn, "wf-4")
        assert row["status"] == "failed"
        assert "Something" in row["error"]

    def test_update_status_cancelled(self, db):
        conn = db.get_conn()
        crud.insert_workflow_run(conn, "wf-5", "test", '{}')
        crud.update_workflow_run_status(conn, "wf-5", "cancelled")
        row = crud.get_workflow_run(conn, "wf-5")
        assert row["status"] == "cancelled"

    def test_list_runs(self, db):
        conn = db.get_conn()
        crud.insert_workflow_run(conn, "wf-a", "workflow-a", '{}')
        crud.insert_workflow_run(conn, "wf-b", "workflow-b", '{}')
        runs = crud.list_workflow_runs(conn, limit=10)
        assert len(runs) == 2

    def test_list_runs_with_tenant(self, db):
        conn = db.get_conn()
        # All rows get 'default' tenant automatically from schema
        crud.insert_workflow_run(conn, "wf-c", "tenant-wf", '{}')
        runs = crud.list_workflow_runs(conn, limit=10, tenant_id="default")
        assert len(runs) == 1
        runs_other = crud.list_workflow_runs(conn, limit=10, tenant_id="ghost")
        assert len(runs_other) == 0

    def test_list_runs_empty(self, db):
        conn = db.get_conn()
        assert crud.list_workflow_runs(conn) == []


class TestSessionCRUD:
    """CRUD operations for agent_sessions and session_messages."""

    def test_insert_session(self, db):
        conn = db.get_conn()
        crud.insert_session(conn, "ses-1", "agent-a", "default", "2026-01-01T00:00:00")
        rows = conn.execute(
            "SELECT * FROM agent_sessions WHERE id = ?", ("ses-1",)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "active"

    def test_update_session_status(self, db):
        conn = db.get_conn()
        crud.insert_session(conn, "ses-2", "agent-a", "default", "2026-01-01T00:00:00")
        crud.update_session(conn, "ses-2", status="closed", updated_at="2026-01-01T01:00:00")
        row = conn.execute(
            "SELECT status FROM agent_sessions WHERE id = ?", ("ses-2",)
        ).fetchone()
        assert row["status"] == "closed"

    def test_update_session_summary(self, db):
        conn = db.get_conn()
        crud.insert_session(conn, "ses-3", "agent-a", "default", "2026-01-01T00:00:00")
        crud.update_session(conn, "ses-3", context_summary="User asked about X")
        row = conn.execute(
            "SELECT context_summary FROM agent_sessions WHERE id = ?", ("ses-3",)
        ).fetchone()
        assert row["context_summary"] == "User asked about X"

    def test_insert_session_message(self, db):
        conn = db.get_conn()
        crud.insert_session(conn, "ses-4", "agent-a", "default", "2026-01-01T00:00:00")
        msg_id = crud.insert_session_message(
            conn, "ses-4", "user", "Hello", 10, "2026-01-01T00:00:01"
        )
        assert msg_id is not None
        row = conn.execute(
            "SELECT role, content FROM session_messages WHERE id = ?", (msg_id,)
        ).fetchone()
        assert row["role"] == "user"
        assert row["content"] == "Hello"


class TestPersonalityVersionCRUD:
    """CRUD operations for personality_versions table."""

    def test_insert_and_retrieve(self, db):
        conn = db.get_conn()
        crud.insert_personality_version(
            conn, "architect", "1.0", "content: v1", "Initial", "2026-01-01T00:00:00"
        )
        rows = conn.execute(
            "SELECT * FROM personality_versions WHERE personality_name = ?",
            ("architect",)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["version"] == "1.0"

    def test_insert_replace(self, db):
        conn = db.get_conn()
        crud.insert_personality_version(
            conn, "writer", "1.0", "v1 content", "v1", "2026-01-01T00:00:00"
        )
        crud.insert_personality_version(
            conn, "writer", "1.0", "v1 revised", "revised", "2026-01-01T00:00:01"
        )
        rows = conn.execute(
            "SELECT * FROM personality_versions WHERE personality_name = ?",
            ("writer",)
        ).fetchall()
        assert len(rows) == 1
        assert "revised" in rows[0]["content"]


class TestEventQueueCRUD:
    """CRUD operations for event_queue table."""

    def test_insert_event(self, db):
        conn = db.get_conn()
        data = json.dumps({"run_id": "wf-1", "status": "completed"})
        crud.insert_event_queue_item(conn, "workflow.completed", data)
        rows = conn.execute(
            "SELECT * FROM event_queue WHERE event = ?",
            ("workflow.completed",)
        ).fetchall()
        assert len(rows) == 1
        assert "wf-1" in rows[0]["data"]

    def test_insert_multiple_events(self, db):
        conn = db.get_conn()
        crud.insert_event_queue_item(conn, "workflow.started", '{"id": "1"}')
        crud.insert_event_queue_item(conn, "workflow.completed", '{"id": "1"}')
        rows = conn.execute("SELECT * FROM event_queue").fetchall()
        assert len(rows) == 2
