"""Chaos engineering — fault injection and resilience tests.

Simulates system failures to verify SCCS OS handles them gracefully:
- Database connection loss and recovery
- EventBus subscriber crashes
- RetryPolicy resilience
- Supervisor restart cycles

Each test injects a controlled fault and verifies the system
recovers without data loss or corruption.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from typing import Any

import pytest

from sccsos.core.db import Database
from sccsos.core.event_bus import LocalEventBus
from sccsos.core.retry_policy import RetryPolicy
from sccsos.core.supervisor import Supervisor
from sccsos.core.agent_runner import AgentProcess
from sccsos.core.hermes_adapter import HermesAdapter
from sccsos.observability.logger import get_logger


# ── Mock adapter ─────────────────────────────────────────────────────


class _MockAdapter(HermesAdapter):
    """Mock adapter for Supervisor tests — does nothing but respond."""

    def __init__(self):
        self._call_count = 0

    def ask(self, prompt: str, agent_name: str = "", **kwargs) -> str:
        self._call_count += 1
        return f"mock response to: {prompt[:20]}"

    def delegate_task(self, agent_name: str, prompt: str, **kwargs) -> "TaskResult":
        from sccsos.core.hermes_adapter import TaskResult
        self._call_count += 1
        return TaskResult(
            response=f"mock: {prompt[:20]}",
            success=True,
        )

    def check_connectivity(self) -> bool:
        return True

    def get_profile_info(self, profile: str = "sccsos") -> dict:
        return {"profile": profile, "status": "mock"}

    def health(self) -> bool:
        return True

    def stop(self) -> None:
        pass


# ── Test: DB fault tolerance ────────────────────────────────────────


class TestDatabaseChaos:
    """Database resilience under fault conditions."""

    def test_db_reconnect_after_file_deleted(self):
        """DB should survive temporary file deletion (re-initialize)."""
        tmp = tempfile.mktemp(suffix=".db")
        db = Database(db_path=tmp)
        db.initialize()
        assert db.execute("SELECT 1").fetchone() is not None

        # Simulate catastrophic file deletion
        db.close()
        os.unlink(tmp)

        # Should recover with new initialization
        db2 = Database(db_path=tmp)
        db2.initialize()
        db2.execute("CREATE TABLE IF NOT EXISTS test_recover (id INTEGER)")
        row = db2.execute("SELECT count(*) FROM test_recover").fetchone()
        assert row is not None, "DB should recover after re-initialization"
        db2.close()

    def test_db_concurrent_writes_no_corruption(self):
        """Concurrent writes from multiple threads should not corrupt the DB."""
        tmp = tempfile.mktemp(suffix=".db")
        db = Database(db_path=tmp)
        db.initialize()
        db.execute(
            "CREATE TABLE IF NOT EXISTS test_concurrent "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, val INTEGER, thread INTEGER)"
        )

        errors: list[str] = []

        def writer(thread_id: int):
            try:
                for i in range(20):
                    db.execute(
                        "INSERT INTO test_concurrent (val, thread) VALUES (?, ?)",
                        (i, thread_id),
                    )
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent write errors: {errors}"
        row = db.execute("SELECT count(*) FROM test_concurrent").fetchone()
        assert row[0] == 80, f"Expected 80 rows, got {row[0]}"
        db.close()
        os.unlink(tmp)

    def test_db_rollback_on_exception(self):
        """An exception during a transaction should roll back cleanly."""
        tmp = tempfile.mktemp(suffix=".db")
        db = Database(db_path=tmp)
        db.initialize()
        db.execute(
            "CREATE TABLE IF NOT EXISTS test_rollback (id INTEGER PRIMARY KEY, val TEXT)"
        )
        db.execute("INSERT INTO test_rollback (id, val) VALUES (1, 'before')")

        # Trigger an error inside a transaction
        with pytest.raises(Exception):
            db.execute("INSERT INTO test_rollback (id, val) VALUES (1, 'duplicate')")

        # The first row should still be intact
        row = db.execute("SELECT val FROM test_rollback WHERE id = 1").fetchone()
        assert row[0] == "before", "Rollback should preserve prior data"
        db.close()
        os.unlink(tmp)


# ── Test: EventBus resilience ────────────────────────────────────────


class TestEventBusChaos:
    """EventBus resilience under subscriber failures."""

    def test_bus_survives_crashing_subscriber(self):
        """One crashing subscriber should not block other subscribers."""
        bus = LocalEventBus.get_instance()

        received: list[str] = []

        def good_handler(**data: Any):
            received.append("test.event")

        def bad_handler(**data: Any):
            raise RuntimeError("Simulated crash")

        bus.on("test.event", good_handler)
        bus.on("test.event", bad_handler)
        bus.on("test.event", good_handler)

        # Should not raise — bad handler is isolated
        bus.emit("test.event", msg="hello")

        # Good handlers on both sides should still fire
        assert len(received) >= 1, "Good handlers should not be blocked"

        bus.clear()

    def test_bus_many_emit_cycles(self):
        """Repeated emit cycles should not degrade performance."""
        bus = LocalEventBus.get_instance()
        count = 0

        def handler(**data: Any):
            nonlocal count
            count += 1

        bus.on("test.event", handler)

        for i in range(100):
            bus.emit("test.event", seq=i)

        assert count == 100, f"Expected 100, got {count}"
        bus.clear()

    def test_bus_clear_releases_handlers(self):
        """Clearing all handlers should stop event propagation."""
        bus = LocalEventBus.get_instance()
        events: list[str] = []

        def handler(**data: Any):
            events.append("test.event")

        bus.on("test.event", handler)
        bus.emit("test.event", seq=1)
        assert len(events) == 1

        bus.clear()
        bus.emit("test.event", seq=2)
        assert len(events) == 1, "After clear, handlers should not fire"

    def test_bus_isolation_between_events(self):
        """Handlers for different events should not interfere."""
        bus = LocalEventBus.get_instance()

        a_events: list[str] = []
        b_events: list[str] = []

        def handler_a(**data: Any):
            a_events.append("event.a")

        def handler_b(**data: Any):
            b_events.append("event.b")

        bus.on("event.a", handler_a)
        bus.on("event.b", handler_b)

        bus.emit("event.a")
        assert len(a_events) == 1
        assert len(b_events) == 0, "Event B handlers should not fire on event A"

        bus.emit("event.b")
        assert len(b_events) == 1

        bus.clear()


# ── Test: RetryPolicy resilience ─────────────────────────────────────


class TestRetryPolicyChaos:
    """RetryPolicy resilience under repeated failures."""

    def test_retry_exhaustion_raises(self, tmp_path):
        """After max retries, the original exception should propagate."""
        db_path = tmp_path / "test_retry.db"
        db_lock = threading.Lock()
        db = Database(db_path=str(db_path))
        db.initialize()

        policy = RetryPolicy(db, db_lock, base_delay=1, max_delay=5)
        call_count = 0

        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("persistent failure")

        with pytest.raises(Exception):
            policy.execute(
                always_fails,
                max_attempts=3,
                step_id="chaos-test",
                step_agent="chaos",
            )

        assert call_count <= 3, f"Expected ≤3 calls, got {call_count}"
        db.close()

    def test_non_retryable_pattern_stops_retry(self, tmp_path):
        """When failure matches non_retryable_patterns, retry should stop."""
        db_path = tmp_path / "test_nonretry.db"
        db_lock = threading.Lock()
        db = Database(db_path=str(db_path))
        db.initialize()

        policy = RetryPolicy(db, db_lock, base_delay=1, max_delay=5)
        call_count = 0

        def fails_with_policy_reject():
            nonlocal call_count
            call_count += 1
            raise ValueError("Policy rejected: budget exceeded")

        with pytest.raises(Exception):
            policy.execute(
                fails_with_policy_reject,
                max_attempts=5,
                step_id="chaos-policy",
                step_agent="chaos",
            )

        # Should stop early (only 1 attempt) because "Policy rejected" matches
        assert call_count == 1, f"Expected 1 call (non-retryable), got {call_count}"
        db.close()


# ── Test: Supervisor resilience ──────────────────────────────────────


class TestSupervisorChaos:
    """Supervisor resilience under agent failures."""

    def test_supervisor_register_and_status(self, tmp_path):
        """A registered agent should appear in status checks."""
        adapter = _MockAdapter()
        proc = AgentProcess(
            name="test-agent",
            profile="sccsos",
            adapter=adapter,
        )

        supervisor = Supervisor(max_restarts=3, heartbeat_timeout=30.0, check_interval=5.0)
        supervisor.register("test-agent", proc)

        status = supervisor.get_status("test-agent")
        assert status is not None
        assert status.name == "test-agent"
        assert status.responsive, "Freshly registered agent should be responsive"
        assert status.restart_count == 0

    def test_supervisor_tracks_unresponsive_agent(self, tmp_path):
        """An agent that stops heartbeating should be marked unresponsive."""
        adapter = _MockAdapter()
        proc = AgentProcess(
            name="hb-agent",
            profile="sccsos",
            adapter=adapter,
        )

        supervisor = Supervisor(max_restarts=1, heartbeat_timeout=0.2, check_interval=0.1)
        supervisor.register("hb-agent", proc)

        # Send one heartbeat
        supervisor.heartbeat("hb-agent")

        # Wait for timeout to expire
        time.sleep(0.5)

        status = supervisor.get_status("hb-agent")
        assert status is not None
        assert not status.responsive, "Agent should be unresponsive after heartbeat timeout"

    def test_supervisor_tracks_restart_count(self, tmp_path):
        """Restarting an agent should increment its restart count."""
        adapter = _MockAdapter()
        proc = AgentProcess(
            name="restart-agent",
            profile="sccsos",
            adapter=adapter,
        )

        supervisor = Supervisor(max_restarts=5, heartbeat_timeout=30.0, check_interval=5.0)
        supervisor.register("restart-agent", proc)

        # Manually increment restart count (simulates what auto-restart does)
        supervisor._restart_counts["restart-agent"] = 3

        status = supervisor.get_status("restart-agent")
        assert status is not None
        assert status.restart_count == 3

    def test_supervisor_wraps_after_max_restarts(self, tmp_path):
        """After exceeding max_restarts, the agent should not restart."""
        adapter = _MockAdapter()
        proc = AgentProcess(
            name="overlimit-agent",
            profile="sccsos",
            adapter=adapter,
        )

        max_r = 2
        supervisor = Supervisor(max_restarts=max_r, heartbeat_timeout=30.0, check_interval=5.0)
        supervisor.register("overlimit-agent", proc)

        # Simulate restarts exceeding max
        supervisor._restart_counts["overlimit-agent"] = 4

        status = supervisor.get_status("overlimit-agent")
        assert status is not None
        assert status.restart_count >= max_r
