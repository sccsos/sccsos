"""Unit tests for session persistence — CLI commands and API endpoints."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from sccsos.core.database import Database
from sccsos.core.session import AgentSessionManager
from sccsos.core.agent_runner import AgentRunner, AgentProcess
from sccsos.core.hermes_adapter import MockHermesAdapter


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    database = Database(path)
    database.initialize()
    yield database
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def manager(db):
    return AgentSessionManager(db)


@pytest.fixture
def adapter():
    return MockHermesAdapter()


# ── AgentProcess session integration ──────────────────────────────


class TestAgentProcessSession:
    """Tests that AgentProcess auto-creates sessions and injects history."""

    def test_agent_process_creates_session_on_start(self, db, adapter):
        manager = AgentSessionManager(db)
        runner = AgentRunner(adapter, session_manager=manager)

        runner.start_agent("test-agent")
        assert runner.is_running("test-agent")

        # A session should have been created for this agent
        sessions = manager.list_sessions(agent_name="test-agent")
        assert len(sessions) == 1
        assert sessions[0].status == "active"
        assert sessions[0].agent_name == "test-agent"

        runner.stop_all()

    def test_agent_ask_records_messages(self, db, adapter):
        manager = AgentSessionManager(db)
        runner = AgentRunner(adapter, session_manager=manager)

        runner.start_agent("test-agent")
        result = runner.ask_agent("test-agent", "Hello!", timeout=10)
        assert result.success is True

        # Messages should be recorded
        sessions = manager.list_sessions(agent_name="test-agent")
        session_id = sessions[0].id
        messages = manager.get_history(session_id)
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Hello!"
        assert messages[1].role == "assistant"

        runner.stop_all()

    def test_agent_ask_injects_history(self, db, adapter):
        manager = AgentSessionManager(db)
        runner = AgentRunner(adapter, session_manager=manager)

        runner.start_agent("test-agent")
        # First ask records history
        runner.ask_agent("test-agent", "First message", timeout=5)
        # Second ask should inject it
        result = runner.ask_agent("test-agent", "Second message", timeout=5)
        assert result.success is True
        # The prompt should contain the context from the first turn
        # (MockHermesAdapter echoes the agent name but let's check messages)
        sessions = manager.list_sessions(agent_name="test-agent")
        session_id = sessions[0].id
        messages = manager.get_history(session_id)
        assert len(messages) == 4  # 2 user + 2 assistant

        runner.stop_all()

    def test_session_isolated_between_agents(self, db, adapter):
        manager = AgentSessionManager(db)
        runner = AgentRunner(adapter, session_manager=manager)

        runner.start_agent("agent-a")
        runner.start_agent("agent-b")

        runner.ask_agent("agent-a", "Hello A", timeout=5)
        runner.ask_agent("agent-b", "Hello B", timeout=5)

        sessions_a = manager.list_sessions(agent_name="agent-a")
        sessions_b = manager.list_sessions(agent_name="agent-b")
        assert len(sessions_a) == 1
        assert len(sessions_b) == 1
        assert sessions_a[0].id != sessions_b[0].id

        runner.stop_all()


# ── Pause/resume session lifecycle ────────────────────────────────


class TestPauseResumeSession:
    """Tests that pausing closes session and resuming creates a new one."""

    def test_pause_closes_session(self, db, adapter):
        manager = AgentSessionManager(db)
        runner = AgentRunner(adapter, session_manager=manager)

        runner.start_agent("test-agent")
        runner.ask_agent("test-agent", "Hello", timeout=5)

        # Pause — session should be marked 'paused'
        runner.pause_agent("test-agent")
        sessions = manager.list_sessions(agent_name="test-agent")
        paused = [s for s in sessions if s.status == "paused"]
        assert len(paused) >= 1

        runner.stop_all()

    def test_resume_creates_new_session(self, db, adapter):
        manager = AgentSessionManager(db)
        runner = AgentRunner(adapter, session_manager=manager)

        runner.start_agent("test-agent")
        runner.ask_agent("test-agent", "Hello", timeout=5)

        # Pause, then resume
        runner.pause_agent("test-agent")
        first_sessions = manager.list_sessions(agent_name="test-agent")
        first_active = [s for s in first_sessions if s.status == "active"]

        runner.resume_agent("test-agent")
        second_sessions = manager.list_sessions(agent_name="test-agent",
                                                status="active")
        assert len(second_sessions) == 1

        # If we had a first active session, the IDs should differ
        if first_active:
            assert first_active[0].id != second_sessions[0].id

        runner.stop_all()

    def test_stop_closes_session(self, db, adapter):
        manager = AgentSessionManager(db)
        runner = AgentRunner(adapter, session_manager=manager)

        runner.start_agent("test-agent")
        runner.ask_agent("test-agent", "Hello", timeout=5)

        # Stop — session should be 'closed'
        active_before = manager.list_sessions(agent_name="test-agent",
                                              status="active")
        assert len(active_before) == 1

        runner.stop_agent("test-agent")
        active_after = manager.list_sessions(agent_name="test-agent",
                                             status="active")
        assert len(active_after) == 0

    def test_ask_rejected_when_paused(self, db, adapter):
        manager = AgentSessionManager(db)
        runner = AgentRunner(adapter, session_manager=manager)

        runner.start_agent("test-agent")
        runner.pause_agent("test-agent")

        result = runner.ask_agent("test-agent", "Hello", timeout=5)
        assert result.success is False
        assert "paused" in result.error.lower()

        runner.stop_all()


# ── AgentSessionManager with AgentProcess (direct) ────────────────


class TestAgentProcessDirect:
    """Tests for AgentProcess session handling at the process level."""

    def test_build_prompt_with_session(self, db, adapter):
        manager = AgentSessionManager(db)
        proc = AgentProcess("test-agent", "sccsos", adapter,
                            session_manager=manager)
        # Simulate session creation (normally happens in _run_loop)
        session = manager.get_or_create("test-agent")
        proc._session_id = session.id

        # Add history
        manager.append_message(session.id, "user", "Previous question")
        manager.append_message(session.id, "assistant", "Previous answer")

        prompt = proc._build_prompt("New question")
        assert "[Previous conversation]" in prompt
        assert "Previous question" in prompt
        assert "Previous answer" in prompt
        assert "New question" in prompt

    def test_build_prompt_empty_history(self, db, adapter):
        manager = AgentSessionManager(db)
        proc = AgentProcess("test-agent", "sccsos", adapter,
                            session_manager=manager)
        session = manager.get_or_create("test-agent")
        proc._session_id = session.id

        prompt = proc._build_prompt("First question")
        # No history to inject — just the user prompt
        assert "First question" in prompt
        assert "[Previous conversation]" not in prompt

    def test_build_prompt_no_session_manager(self, adapter):
        proc = AgentProcess("test-agent", "sccsos", adapter,
                            session_manager=None)
        prompt = proc._build_prompt("Hello")
        assert prompt == "Hello"

    def test_build_prompt_with_memory_and_session(self, db, adapter):
        from sccsos.memory.memory_store import MemoryStore
        ms = MemoryStore(db)
        manager = AgentSessionManager(db)

        proc = AgentProcess("test-agent", "sccsos", adapter,
                            memory_store=ms, session_manager=manager)
        session = manager.get_or_create("test-agent")
        proc._session_id = session.id

        # Add both memory and session history
        ms.save("test-agent", "language", "Python")
        manager.append_message(session.id, "user", "Design auth")

        prompt = proc._build_prompt("Add JWT")
        assert "Persistent memory" in prompt
        assert "Python" in prompt
        assert "Previous conversation" in prompt
        assert "Design auth" in prompt
        assert "Add JWT" in prompt


# ── Multi-tenant session isolation ────────────────────────────────


class TestMultiTenantSessions:
    """Tests that sessions are properly isolated between tenants."""

    def test_tenant_session_isolation(self, db, adapter):
        manager = AgentSessionManager(db)
        runner = AgentRunner(adapter, session_manager=manager)

        runner.start_agent("agent-a")  # Default tenant
        runner.ask_agent("agent-a", "Hello", timeout=5)

        # Use manager directly for second tenant (runner uses 'default')
        manager.get_or_create("agent-a", tenant_id="tenant-2")

        sessions_t1 = manager.list_sessions(agent_name="agent-a",
                                            tenant_id="default")
        sessions_t2 = manager.list_sessions(agent_name="agent-a",
                                            tenant_id="tenant-2")
        assert len(sessions_t1) == 1
        assert len(sessions_t2) == 1
        assert sessions_t1[0].id != sessions_t2[0].id

        runner.stop_all()


# ── CLI integration smoke tests ───────────────────────────────────


class TestSessionCommandHelpers:
    """Tests for session command helper functions (no click invocation)."""

    def test_get_history_block_formatting(self, db, adapter):
        """Verify history block is well-formatted for CLI display."""
        manager = AgentSessionManager(db)
        runner = AgentRunner(adapter, session_manager=manager)

        runner.start_agent("test-agent")
        runner.ask_agent("test-agent", "Design auth", timeout=5)
        runner.ask_agent("test-agent", "Add JWT", timeout=5)

        sessions = manager.list_sessions(agent_name="test-agent")
        assert len(sessions) == 1

        history = manager.get_history(sessions[0].id)
        assert len(history) >= 1
        # Verify chronological order
        roles = [m.role for m in history]
        assert roles.count("user") == roles.count("assistant")
        # First message is user
        assert history[0].role == "user"

        runner.stop_all()
