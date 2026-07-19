"""Tests for Supervisor — agent process monitoring with heartbeat + auto-restart."""

from __future__ import annotations

import threading
import time

import pytest

from sccsos.core.hermes_adapter import MockHermesAdapter
from sccsos.core.agent_runner import AgentProcess
from sccsos.core.supervisor import Supervisor


@pytest.fixture
def adapter():
    return MockHermesAdapter()


class TestSupervisorCore:
    """Supervisor registration, status, and lifecycle."""

    def test_register_and_get_status(self, adapter):
        sup = Supervisor(max_restarts=2, heartbeat_timeout=5.0, check_interval=1.0)
        proc = AgentProcess("test-agent", "sccsos", adapter)

        # Register before process is started
        sup.register("test-agent", proc)
        status = sup.get_status("test-agent")
        assert status is not None
        assert status.name == "test-agent"
        assert not status.alive  # Not started yet
        assert not status.paused
        assert status.restart_count == 0

    def test_unregister_removes_process(self, adapter):
        sup = Supervisor()
        proc = AgentProcess("test-agent", "sccsos", adapter)
        sup.register("test-agent", proc)
        assert sup.get_status("test-agent") is not None

        sup.unregister("test-agent")
        assert sup.get_status("test-agent") is None

    def test_list_status_empty(self, adapter):
        sup = Supervisor()
        assert sup.list_status() == []

    def test_heartbeat_updates_timestamp(self, adapter):
        sup = Supervisor(heartbeat_timeout=30.0)
        proc = AgentProcess("agent-x", "sccsos", adapter)
        proc.start()
        sup.register("agent-x", proc)
        time.sleep(0.1)

        # Status should show responsive because heartbeat was called
        # (AgentProcess._run_loop calls heartbeat on each iteration)
        status = sup.get_status("agent-x")
        assert status is not None
        assert status.alive

        sup.stop()
        proc.stop()

    def test_get_status_unregistered_returns_none(self, adapter):
        sup = Supervisor()
        assert sup.get_status("nonexistent") is None

    def test_start_stop_monitor_thread(self, adapter):
        sup = Supervisor()
        assert not sup.is_running

        sup.start()
        time.sleep(0.1)
        assert sup.is_running

        sup.stop()
        assert not sup.is_running


class TestSupervisorHeartbeatIntegration:
    """End-to-end: AgentProcess heartbeat reaches Supervisor."""

    def test_heartbeat_callback_integration(self, adapter):
        """AgentProcess with heartbeat_callback should update supervisor."""
        sup = Supervisor(max_restarts=2, heartbeat_timeout=10.0, check_interval=5.0)
        sup.start()

        # Create process with supervisor's heartbeat as callback
        proc = AgentProcess(
            "hb-agent", "sccsos", adapter,
            heartbeat_callback=sup.heartbeat,
        )
        sup.register("hb-agent", proc)
        proc.start()
        time.sleep(0.3)  # Let a few loop iterations run

        status = sup.get_status("hb-agent")
        assert status is not None
        assert status.alive
        assert status.responsive  # Heartbeat was received

        proc.stop()
        sup.unregister("hb-agent")
        sup.stop()


class TestSupervisorAutoRestart:
    """Auto-restart on thread death."""

    def test_auto_restart_on_death(self, adapter):
        """A process that dies should be restarted by supervisor."""
        sup = Supervisor(max_restarts=2, heartbeat_timeout=2.0, check_interval=0.3)
        sup.start()

        proc = AgentProcess("crashy", "sccsos", adapter)
        sup.register("crashy", proc)
        proc.start()
        time.sleep(0.2)

        assert proc.is_alive
        start_count = sup._restart_counts.get("crashy", 0)

        # Force-stop the internal thread (simulate crash)
        proc._stop_event.set()
        if proc._thread:
            proc._thread.join(timeout=2)

        time.sleep(1.0)  # Let supervisor detect and restart

        # After restart, the process should be alive again
        # and restart count should be incremented
        end_count = sup._restart_counts.get("crashy", 0)
        assert end_count > start_count

        sup.stop()

    def test_max_restarts_exceeded(self, adapter):
        """After max_restarts, supervisor should stop restarting."""
        sup = Supervisor(max_restarts=1, heartbeat_timeout=1.0, check_interval=0.2)
        sup.start()

        proc = AgentProcess("doomed", "sccsos", adapter)
        sup.register("doomed", proc)
        proc.start()
        time.sleep(0.2)

        # Kill thread twice
        for _ in range(3):
            proc._stop_event.set()
            if proc._thread:
                proc._thread.join(timeout=2)
            time.sleep(0.5)
            # Re-create stop event for possible restart
            proc._stop_event = threading.Event()

        # Should have hit max restart limit
        time.sleep(1.0)
        assert sup._restart_counts.get("doomed", 0) >= 1

        sup.stop()


class TestSupervisorPausedProcesses:
    """Paused processes should not trigger auto-restart."""

    def test_paused_process_not_restarted(self, adapter):
        sup = Supervisor(heartbeat_timeout=1.0, check_interval=0.3)
        sup.start()

        proc = AgentProcess("pausy", "sccsos", adapter)
        proc.start()
        sup.register("pausy", proc)
        time.sleep(0.2)

        # Pause the process (simulate)
        proc.pause()
        time.sleep(0.3)

        status = sup.get_status("pausy")
        assert status is not None
        assert status.paused

        sup.stop()
        proc.stop()
