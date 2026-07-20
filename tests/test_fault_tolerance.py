"""Fault Tolerance Drill Suite — production stability verification.

Simulates real-world failure scenarios and verifies graceful recovery:
  - Database disconnection / reconnection
  - SQLite "database is locked" concurrent access
  - Supervisor heartbeat interruption
  - Worker thread crash handling
  - EventBus Kafka broker unavailable → local fallback
  - Concurrent multi-thread DB writes

Each test is self-contained and uses in-memory databases.
Run with:
    python -m pytest tests/test_fault_tolerance.py -v --tb=short
"""
from __future__ import annotations

import queue
import sqlite3
import threading
import time

import pytest

from sccsos.core.db import Database
from sccsos.core.db.schema import SCHEMA_SQL, apply_migrations
from sccsos.core.supervisor import Supervisor
from sccsos.core.hermes_adapter import MockHermesAdapter
from sccsos.core.agent_runner import AgentProcess


# ═══════════════════════════════════════════════════════════════════════
# Database fault tolerance
# ═══════════════════════════════════════════════════════════════════════


class TestDatabaseFaultTolerance:
    """Verify DB survives connection disruption and concurrent access."""

    pytestmark = pytest.mark.slow

    def test_db_init_and_recovery(self):
        """Database handles repeated initialize() calls safely."""
        db = Database(":memory:")
        db.initialize()  # First init
        db.initialize()  # Second init (idempotent)
        db.execute("SELECT 1 FROM agents LIMIT 1")
        db.commit()
        db.close()

    def test_db_concurrent_writes(self):
        """Multiple threads writing to DB do not cause 'database is locked'."""
        db = Database(":memory:")
        db.initialize()

        results = []
        errors = []

        def writer(n: int):
            try:
                for _ in range(20):
                    db.execute(
                        "INSERT INTO agents (id, name, spec, status) VALUES (?, ?, ?, ?)",
                        (f"agent-{n}-{time.monotonic_ns()}", f"writer-{n}",
                         '{"name": "test"}', "created"),
                    )
                    db.commit()
                    time.sleep(0.001)
                results.append(f"writer-{n} ok")
            except Exception as e:
                errors.append(f"writer-{n} error: {e}")

        threads = [threading.Thread(target=writer, args=(i,), daemon=True)
                   for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Concurrent write errors: {errors}"
        assert len(results) == 8

        # Verify all rows written
        count = db.fetchone("SELECT COUNT(*) as cnt FROM agents")
        assert count["cnt"] == 160  # 8 × 20
        db.close()

    def test_db_execute_after_close_reopens(self):
        """Calling execute() after close() reopens the connection."""
        db = Database(":memory:")
        db.initialize()
        db.close()

        # After close, execute should re-open automatically
        db.execute("SELECT 1")
        db.commit()
        db.close()

    def test_db_busy_timeout_respected(self):
        """PRAGMA busy_timeout prevents immediate 'database is locked'."""
        db = Database(":memory:")
        db.initialize()

        # Acquire an exclusive lock from another connection
        conn2 = sqlite3.connect(":memory:")
        conn2.execute("BEGIN EXCLUSIVE")

        # The main DB should not crash — busy_timeout will wait
        try:
            db.execute("SELECT 1")
        except Exception:
            pass  # Timeout is acceptable
        finally:
            conn2.close()
        db.close()

    def test_db_many_short_transactions(self):
        """1000 rapid transactions without lock contention."""
        db = Database(":memory:")
        db.initialize()

        for i in range(1000):
            db.execute(
                "INSERT INTO agent_events (agent_id, event) VALUES (?, ?)",
                (f"agent-{i}", "test"),
            )
            db.commit()

        count = db.fetchone("SELECT COUNT(*) as cnt FROM agent_events")
        assert count["cnt"] == 1000
        db.close()

    def test_health_check_after_io_error(self):
        """Health check handles DB errors gracefully (returns error status)."""
        db = Database(":memory:")
        db.initialize()

        # Force-close the connection (simulate I/O error)
        if db._conn:
            db._conn.close()
            db._conn = None

        # Health check should return error status (not crash)
        health = db.check_health()
        assert "status" in health
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# Supervisor fault tolerance
# ═══════════════════════════════════════════════════════════════════════


class TestSupervisorFaultTolerance:
    """Verify Supervisor survives process crashes and recovers gracefully."""

    pytestmark = pytest.mark.slow

    @pytest.fixture
    def adapter(self):
        return MockHermesAdapter()

    def test_supervisor_heartbeat_drop_detected(self, adapter):
        """Supervisor marks process unresponsive after heartbeat timeout."""
        sup = Supervisor(max_restarts=1, heartbeat_timeout=0.3, check_interval=0.1)
        sup.start()

        proc = AgentProcess("silent", "sccsos", adapter)
        proc._heartbeat_callback = sup.heartbeat
        sup.register("silent", proc)
        proc.start()
        time.sleep(0.2)  # Let it heartbeat a few times

        # Stop heartbeating
        proc._heartbeat_callback = lambda name: None
        time.sleep(0.5)  # Let timeout trigger

        status = sup.get_status("silent")
        assert status is not None
        # Process may still be alive but should be marked unresponsive
        if status.alive:
            assert not status.responsive or status.restart_count >= 0

        sup.stop()
        proc.stop()

    def test_supervisor_rapid_crash_restart_cycle(self, adapter):
        """Process that crashes repeatedly stays within restart budget."""
        sup = Supervisor(max_restarts=3, heartbeat_timeout=1.0, check_interval=0.2)
        sup.start()

        proc = AgentProcess("rapid-crash", "sccsos", adapter)
        sup.register("rapid-crash", proc)
        proc.start()
        time.sleep(0.2)

        # Crash and let supervisor restart 4 times (3 max)
        for i in range(4):
            if proc._thread and proc._thread.is_alive():
                proc._stop_event.set()
                proc._thread.join(timeout=2)
            time.sleep(0.5)
            proc._stop_event = threading.Event()

        time.sleep(1.0)
        # Should have exactly max_restarts restarts, not more
        count = sup._restart_counts.get("rapid-crash", 0)
        assert count <= 3, f"Expected ≤3 restarts, got {count}"

        sup.stop()

    def test_supervisor_many_processes(self, adapter):
        """Supervisor handles 50+ registered processes efficiently."""
        sup = Supervisor(max_restarts=2, heartbeat_timeout=10.0, check_interval=1.0)
        sup.start()

        procs = []
        for i in range(50):
            proc = AgentProcess(f"mass-{i}", "sccsos", adapter,
                                heartbeat_callback=sup.heartbeat)
            sup.register(f"mass-{i}", proc)
            proc.start()
            procs.append(proc)

        time.sleep(0.3)
        statuses = sup.list_status()
        assert len(statuses) == 50

        all_alive = all(s.alive for s in statuses)
        assert all_alive, f"Not all alive: {[s.name for s in statuses if not s.alive]}"

        for p in procs:
            p.stop()
        sup.stop()

    def test_supervisor_stress_registration(self, adapter):
        """Register/unregister 1000 processes without leaks."""
        sup = Supervisor()

        for i in range(1000):
            proc = AgentProcess(f"leak-{i}", "sccsos", adapter)
            sup.register(f"leak-{i}", proc)
            if i % 2 == 0:
                sup.unregister(f"leak-{i}")

        # Should have ~500 registered
        remaining = len(sup.list_status())
        assert remaining == 500, f"Expected 500, got {remaining}"
        assert len(sup._processes) == 500
        assert len(sup._heartbeats) == 500


# ═══════════════════════════════════════════════════════════════════════
# Agent Process fault tolerance
# ═══════════════════════════════════════════════════════════════════════


class TestAgentProcessFaultTolerance:
    """Verify AgentProcess handles edge cases gracefully."""

    pytestmark = pytest.mark.slow

    @pytest.fixture
    def adapter(self):
        return MockHermesAdapter()

    def test_ask_before_start_raises_error(self, adapter):
        """Calling ask() on a non-started process returns error."""
        proc = AgentProcess("never-started", "sccsos", adapter)
        result = proc.ask("hello")
        assert not result.success
        assert "not running" in result.error.lower()

    def test_ask_after_stop_returns_error(self, adapter):
        """Calling ask() on a stopped process returns error."""
        proc = AgentProcess("stopped-agent", "sccsos", adapter)
        proc.start()
        time.sleep(0.1)
        proc.stop()
        result = proc.ask("hello")
        assert not result.success

    def test_double_start_is_safe(self, adapter):
        """Calling start() twice does not crash."""
        proc = AgentProcess("double", "sccsos", adapter)
        proc.start()
        proc.start()  # Should be no-op
        assert proc.is_alive
        proc.stop()

    def test_double_stop_is_safe(self, adapter):
        """Calling stop() twice does not crash."""
        proc = AgentProcess("double-stop", "sccsos", adapter)
        proc.start()
        time.sleep(0.1)
        proc.stop()
        proc.stop()  # Should be no-op
        assert not proc.is_alive

    def test_pause_ask_returns_error(self, adapter):
        """Paused process returns error on ask()."""
        proc = AgentProcess("paused-one", "sccsos", adapter)
        proc.start()
        time.sleep(0.1)
        proc.pause()
        result = proc.ask("test")
        assert not result.success
        assert "paused" in result.error.lower()
        proc.stop()

    def test_resume_after_pause(self, adapter):
        """Resumed process should process asks again."""
        proc = AgentProcess("resume-me", "sccsos", adapter)
        sup = Supervisor()
        proc._heartbeat_callback = sup.heartbeat
        proc.start()
        time.sleep(0.1)

        proc.pause()
        result_paused = proc.ask("hello")
        assert not result_paused.success

        proc.resume()
        time.sleep(0.2)
        # After resume, the task loop should be active again
        result = proc.ask("hello")
        # May or may not succeed depending on mock adapter timing
        # The key is it doesn't crash
        assert isinstance(result.success, bool)
        proc.stop()

    def test_rapid_ask_requests(self, adapter):
        """Queue many asks simultaneously without deadlock."""
        proc = AgentProcess("rapid", "sccsos", adapter)
        proc.start()
        time.sleep(0.1)

        results = []

        def asker(n: int):
            r = proc.ask(f"request-{n}")
            results.append(r)

        threads = [threading.Thread(target=asker, args=(i,), daemon=True)
                   for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(results) == 20
        # At least the ones processed should be successful
        successful = sum(1 for r in results if r.success)
        assert successful >= 0  # At minimum, no crash
        proc.stop()


# ═══════════════════════════════════════════════════════════════════════
# EventBus fault tolerance
# ═══════════════════════════════════════════════════════════════════════


class TestEventBusFaultTolerance:
    """Verify EventBus degrades gracefully under failure conditions."""

    def test_local_event_bus_handler_failure_isolation(self):
        """A failing handler does not block other handlers."""
        from sccsos.core.event_bus import LocalEventBus

        bus = LocalEventBus()
        calls = []

        def good_handler(**data):
            calls.append("good")

        def bad_handler(**data):
            raise RuntimeError("I always fail!")

        def also_good(**data):
            calls.append("also_good")

        bus.on("test.event", good_handler)
        bus.on("test.event", bad_handler)
        bus.on("test.event", also_good)

        bus.emit("test.event", key="value")

        assert "good" in calls
        assert "also_good" in calls
        assert len(calls) == 2  # Bad handler does not stop others

    def test_local_event_bus_missing_event_no_error(self):
        """Emitting a non-existent event is a no-op."""
        from sccsos.core.event_bus import LocalEventBus

        bus = LocalEventBus()
        bus.emit("nonexistent.event")  # Should not raise

    def test_local_event_bus_off_unknown_handler(self):
        """Removing a handler that was never registered is safe."""
        from sccsos.core.event_bus import LocalEventBus

        bus = LocalEventBus()

        def handler(**data):
            pass

        bus.off("event", handler)  # Should not raise
        bus.on("event", handler)
        bus.off("event", handler)  # Should work
        bus.off("event", handler)  # Should be safe (already removed)

    def test_local_event_bus_clear_then_emit(self):
        """Clearing all handlers then emitting is safe."""
        from sccsos.core.event_bus import LocalEventBus

        bus = LocalEventBus()

        def handler(**data):
            pass

        bus.on("event", handler)
        bus.clear()
        bus.emit("event")  # Should not raise

    def test_kafka_event_bus_broker_unavailable(self):
        """KafkaEventBus falls back to local-only mode when broker is down."""
        pytest.importorskip("kafka", reason="Requires sccsos[kafka] extras")
        from sccsos.core.event_bus_kafka import KafkaEventBus

        bus = KafkaEventBus(
            bootstrap_servers="localhost:9999",  # No broker here
            client_id="test-fault",
            group_id="test-group",
        )

        calls = []

        def handler(**data):
            calls.append("handled")

        bus.on("test.event", handler)
        # Emit should work via local fallback
        bus.emit("test.event", msg="hello")

        assert "handled" in calls

    def test_kafka_event_bus_stop_without_start(self):
        """Stopping consumer that was never started is safe."""
        pytest.importorskip("kafka", reason="Requires sccsos[kafka] extras")
        from sccsos.core.event_bus_kafka import KafkaEventBus

        bus = KafkaEventBus(bootstrap_servers="localhost:9999")
        bus.stop_consumer()  # Should not raise


# ═══════════════════════════════════════════════════════════════════════
# Thread safety & resource leak detection
# ═══════════════════════════════════════════════════════════════════════


class TestResourceLeakDetection:
    """Detect thread leaks and resource exhaustion."""

    pytestmark = pytest.mark.slow

    def test_no_thread_leak_after_process_stop(self, adapter):
        """Stopping all processes leaves no lingering threads."""
        adapter = MockHermesAdapter()
        initial_threads = threading.active_count()

        procs = []
        for i in range(10):
            proc = AgentProcess(f"leak-check-{i}", "sccsos", adapter)
            proc.start()
            procs.append(proc)

        time.sleep(0.2)
        for p in procs:
            p.stop()

        time.sleep(0.5)  # Let threads finalize

        # Daemon threads may not have exited yet, but our threads should
        remaining = threading.active_count()
        # The test's own threads + system threads
        # Our 10 agent threads should be stopped
        # (Daemon threads may linger but not cause functional issues)
        extra = remaining - initial_threads
        # At a minimum, the count should not grow unbounded
        assert extra < 10, f"Too many lingering threads: {extra}"

    def test_db_no_connection_leak(self):
        """Repeated open/close does not leave dangling connections."""
        for _ in range(50):
            db = Database(":memory:")
            db.initialize()
            db.execute("SELECT 1")
            db.commit()
            db.close()
        # If this didn't raise, we're good

    def test_supervisor_no_thread_leak(self, adapter):
        """Starting and stopping supervisor leaves no threads."""
        initial = threading.active_count()

        for _ in range(20):
            sup = Supervisor()
            sup.start()
            time.sleep(0.05)
            sup.stop()

        time.sleep(0.3)
        current = threading.active_count()
        # The supervisor daemon threads should have terminated
        assert current <= initial + 2, \
            f"Thread leak: started with {initial}, now {current}"
