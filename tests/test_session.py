"""Unit tests for AgentSessionManager — conversation history persistence."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sccsos.core.database import Database
from sccsos.core.session import AgentSessionManager, _format_history, Message


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def db():
    """In-memory SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    database = Database(path)
    database.initialize()
    yield database
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def manager(db):
    """AgentSessionManager instance for testing."""
    return AgentSessionManager(db)


# ── Session lifecycle ─────────────────────────────────────────────


class TestSessionLifecycle:
    """Tests for session creation, retrieval, and status transitions."""

    def test_get_or_create_returns_active_session(self, manager):
        session = manager.get_or_create("architect")
        assert session.id is not None
        assert session.agent_name == "architect"
        assert session.tenant_id == "default"
        assert session.status == "active"
        assert session.created_at is not None

    def test_get_or_create_returns_same_active_session(self, manager):
        s1 = manager.get_or_create("architect")
        s2 = manager.get_or_create("architect")
        assert s1.id == s2.id  # Same session

    def test_get_or_create_multiple_agents(self, manager):
        s1 = manager.get_or_create("architect")
        s2 = manager.get_or_create("reviewer")
        assert s1.id != s2.id  # Different agents = different sessions

    def test_get_or_create_with_tenant(self, manager):
        s1 = manager.get_or_create("architect", tenant_id="tenant-a")
        s2 = manager.get_or_create("architect", tenant_id="tenant-b")
        assert s1.id != s2.id  # Different tenants = different sessions

    def test_close_session_creates_new_on_next_get(self, manager):
        s1 = manager.get_or_create("architect")
        manager.close_session(s1.id, new_status="closed")

        # Verify paused session is not returned
        paused = manager.get_or_create("architect")
        assert paused.id != s1.id  # New session created
        assert paused.status == "active"

    def test_close_session_with_paused(self, manager):
        s1 = manager.get_or_create("architect")
        manager.close_session(s1.id, new_status="paused")

        # get_paused_session should find the paused one
        paused = manager.get_paused_session("architect")
        assert paused is not None
        assert paused.id == s1.id
        assert paused.status == "paused"

        # get_or_create should create a new active one
        s2 = manager.get_or_create("architect")
        assert s2.id != s1.id

    def test_get_paused_session_none_when_active(self, manager):
        manager.get_or_create("architect")
        paused = manager.get_paused_session("architect")
        assert paused is None  # No paused session

    def test_tenant_isolation(self, manager):
        s_a = manager.get_or_create("architect", tenant_id="t1")
        s_b = manager.get_or_create("architect", tenant_id="t2")
        assert s_a.id != s_b.id

        # Closing in t1 should not affect t2
        manager.close_session(s_a.id, new_status="paused")
        s_b_again = manager.get_or_create("architect", tenant_id="t2")
        assert s_b_again.id == s_b.id  # Still the original


# ── Messages ──────────────────────────────────────────────────────


class TestMessages:
    """Tests for message appending and retrieval."""

    def test_append_and_read(self, manager):
        session = manager.get_or_create("architect")
        msg_id = manager.append_message(session.id, "user", "Hello")
        assert msg_id > 0

        history = manager.get_history(session.id)
        assert len(history) == 1
        assert history[0].role == "user"
        assert history[0].content == "Hello"

    def test_append_multiple_messages(self, manager):
        session = manager.get_or_create("architect")
        manager.append_message(session.id, "user", "Design auth")
        manager.append_message(session.id, "assistant", "Here is a design")
        manager.append_message(session.id, "user", "Add JWT")

        history = manager.get_history(session.id)
        assert len(history) == 3
        assert history[0].role == "user"    # First: "Design auth"
        assert history[1].role == "assistant"
        assert history[2].role == "user"    # Last: "Add JWT"

    def test_get_history_limit(self, manager):
        session = manager.get_or_create("architect")
        for i in range(20):
            manager.append_message(session.id, "user", f"msg-{i}")

        # Default limit is 10
        history = manager.get_history(session.id)
        assert len(history) == 10
        assert history[0].content == "msg-10"  # Oldest of the last 10

        # Custom limit
        history5 = manager.get_history(session.id, limit=5)
        assert len(history5) == 5

    def test_get_history_empty_session(self, manager):
        session = manager.get_or_create("architect")
        history = manager.get_history(session.id)
        assert history == []

    def test_get_history_invalid_session(self, manager):
        history = manager.get_history("nonexistent")
        assert history == []


# ── History formatting ────────────────────────────────────────────


class TestHistoryFormatting:
    """Tests for _format_history and get_history_block."""

    def test_format_empty(self):
        assert _format_history([]) == ""

    def test_format_single_message(self):
        msgs = [
            Message(id=1, session_id="s1", role="user",
                    content="Hello", created_at="now"),
        ]
        result = _format_history(msgs)
        assert "[Previous conversation]" in result
        assert "You said:" in result
        assert "Hello" in result
        assert "[End of previous conversation]" in result

    def test_format_turns(self, manager):
        session = manager.get_or_create("architect")
        manager.append_message(session.id, "user", "Design auth")
        manager.append_message(session.id, "assistant",
                               "Use JWT with refresh tokens")

        block = manager.get_history_block(session.id)
        assert block != ""
        assert "You said:" in block
        assert "Design auth" in block
        assert "Assistant:" in block
        assert "JWT" in block

    def test_format_truncates_long_content(self):
        long_text = "x" * 2000
        msgs = [
            Message(id=1, session_id="s1", role="user",
                    content=long_text, created_at="now"),
        ]
        result = _format_history(msgs)
        assert len(result) < 2500  # Truncated
        assert "..." in result

    def test_get_history_block_empty(self, manager):
        session = manager.get_or_create("architect")
        block = manager.get_history_block(session.id)
        assert block == ""


# ── Context summary ───────────────────────────────────────────────


class TestSummary:
    """Tests for context_summary update."""

    def test_update_summary(self, manager):
        session = manager.get_or_create("architect")
        manager.update_summary(session.id, "User asked about auth design")
        # Re-fetch
        session2 = manager.get_or_create("architect")
        assert session2.context_summary == "User asked about auth design"

    def test_summary_persists_across_sessions(self, manager):
        s1 = manager.get_or_create("architect")
        manager.update_summary(s1.id, "Final summary")
        manager.close_session(s1.id, new_status="closed")

        s2 = manager.get_or_create("architect")
        # Summary is tied to closed session, not new one
        assert s2.id != s1.id
        assert s2.context_summary == ""


# ── Listing ───────────────────────────────────────────────────────


class TestListSessions:
    """Tests for list_sessions filtering."""

    def test_list_all(self, manager):
        manager.get_or_create("architect")
        manager.get_or_create("reviewer")
        sessions = manager.list_sessions()
        assert len(sessions) == 2

    def test_list_filter_by_agent(self, manager):
        manager.get_or_create("architect")
        manager.get_or_create("reviewer")
        sessions = manager.list_sessions(agent_name="architect")
        assert len(sessions) == 1
        assert sessions[0].agent_name == "architect"

    def test_list_filter_by_status(self, manager):
        s1 = manager.get_or_create("architect")
        manager.close_session(s1.id, new_status="closed")
        manager.get_or_create("architect")

        sessions = manager.list_sessions(status="active")
        assert len(sessions) == 1

        sessions = manager.list_sessions(status="closed")
        assert len(sessions) == 1

    def test_list_tenant_isolation(self, manager):
        manager.get_or_create("architect", tenant_id="t1")
        manager.get_or_create("architect", tenant_id="t2")
        assert len(manager.list_sessions(tenant_id="t1")) == 1
        assert len(manager.list_sessions(tenant_id="t2")) == 1
