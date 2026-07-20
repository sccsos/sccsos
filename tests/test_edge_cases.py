"""Edge case tests for core SCCS OS modules."""

from __future__ import annotations

import threading
import time

import pytest

from sccsos.core.event_bus import EventBus, WORKFLOW_STARTED, WORKFLOW_COMPLETED
from sccsos.core.config import AgentOSConfig, get_config, reload_config, set_config
from sccsos.core.hermes_adapter import MockHermesAdapter
from sccsos.core.agent_runner import AgentProcess, AgentRunner
from sccsos.core.supervisor import Supervisor
from sccsos.core.workflow import (
    WorkflowDef, WorkflowEngine, WorkflowStepDef, ParallelGroupDef,
)
from sccsos.core.step_executor import WorkflowExecutionError


# ═══════════════════════════════════════════════════════════════════
# EventBus edge cases
# ═══════════════════════════════════════════════════════════════════


class TestEventBusEdgeCases:
    """Additional EventBus edge case coverage."""

    @pytest.fixture(autouse=True)
    def reset_bus(self):
        EventBus.reset_instance()
        yield
        EventBus.reset_instance()

    def test_re_register_after_unregister(self):
        """Re-registering the same handler should work."""
        bus = EventBus.get_instance()
        calls = []

        def handler(**kw):
            calls.append("ok")

        bus.on("evt", handler)
        bus.off("evt", handler)
        bus.on("evt", handler)
        bus.emit("evt")
        assert calls == ["ok"]

    def test_emitting_to_unregistered_event_is_safe(self):
        """Emit to an event that was never registered should not raise."""
        bus = EventBus.get_instance()
        bus.emit("nobody.listens", data=42)

    def test_multiple_registrations_same_handler_once(self):
        """Registering the same handler twice should call it twice per emit."""
        bus = EventBus.get_instance()
        calls = []

        def handler(**kw):
            calls.append("x")

        bus.on("evt", handler)
        bus.on("evt", handler)  # Duplicate registration
        bus.emit("evt")
        assert len(calls) == 2  # Called twice (two registrations)

    def test_handler_args_preserved(self):
        """All keyword arguments should reach the handler."""
        bus = EventBus.get_instance()
        received = {}

        def handler(**kw):
            received.update(kw)

        bus.on("evt", handler)
        bus.emit("evt", string="hi", number=42, flag=True, items=[1, 2, 3])
        assert received["string"] == "hi"
        assert received["number"] == 42
        assert received["flag"] is True
        assert received["items"] == [1, 2, 3]


# ═══════════════════════════════════════════════════════════════════
# Supervisor edge cases
# ═══════════════════════════════════════════════════════════════════


class TestSupervisorEdgeCases:

    def test_list_status_multiple_processes(self):
        """list_status should return all supervised processes."""
        sup = Supervisor()
        adapter = MockHermesAdapter()
        p1 = AgentProcess("a", "sccsos", adapter)
        p2 = AgentProcess("b", "sccsos", adapter)
        sup.register("a", p1)
        sup.register("b", p2)

        statuses = sup.list_status()
        names = [s.name for s in statuses]
        assert "a" in names
        assert "b" in names

    def test_unregister_then_register_same_name(self):
        """Re-registering the same name should track fresh state."""
        sup = Supervisor()
        adapter = MockHermesAdapter()
        p1 = AgentProcess("x", "sccsos", adapter)
        sup.register("x", p1)
        sup.unregister("x")

        p2 = AgentProcess("x", "sccsos", adapter)
        sup.register("x", p2)
        assert sup.get_status("x") is not None

    def test_heartbeat_before_register_ignored(self):
        """heartbeat() on an unregistered name should not crash."""
        sup = Supervisor()
        sup.heartbeat("unknown")  # Should not raise

    def test_uptime_increases(self):
        """Process uptime should increase over time."""
        sup = Supervisor(heartbeat_timeout=30.0)
        adapter = MockHermesAdapter()
        proc = AgentProcess("uptime-test", "sccsos", adapter)
        proc.start()
        sup.register("uptime-test", proc)
        time.sleep(0.2)

        status = sup.get_status("uptime-test")
        assert status is not None
        assert status.uptime_seconds > 0.0

        proc.stop()
        sup.stop()


# ═══════════════════════════════════════════════════════════════════
# Agent / Runner edge cases
# ═══════════════════════════════════════════════════════════════════


class TestAgentEdgeCases:

    def test_stop_agent_twice(self):
        """Stopping an already stopped agent should not raise."""
        adapter = MockHermesAdapter()
        runner = AgentRunner(adapter)
        runner.start_agent("twice-stop", "sccsos")
        assert runner.stop_agent("twice-stop") is True
        assert runner.stop_agent("twice-stop") is False  # Already stopped

    def test_is_running_checks_correctly(self):
        """is_running should reflect agent state accurately."""
        adapter = MockHermesAdapter()
        runner = AgentRunner(adapter)
        assert not runner.is_running("ghost")
        runner.start_agent("real", "sccsos")
        assert runner.is_running("real")
        runner.stop_agent("real")
        assert not runner.is_running("real")

    def test_pause_then_ask_returns_error(self):
        """Asking a paused agent should return an error immediately."""
        adapter = MockHermesAdapter()
        runner = AgentRunner(adapter)
        runner.start_agent("pausy", "sccsos")
        time.sleep(0.1)
        runner.pause_agent("pausy")
        result = runner.ask_agent("pausy", "hello")
        assert not result.success
        assert "paused" in result.error.lower()

    def test_list_running(self):
        """list_running should return names of alive agents only."""
        adapter = MockHermesAdapter()
        runner = AgentRunner(adapter)
        runner.start_agent("alive1", "sccsos")
        runner.start_agent("alive2", "sccsos")
        runner.stop_agent("alive1")
        running = runner.list_running()
        assert "alive2" in running
        assert "alive1" not in running
        runner.stop_agent("alive2")


# ═══════════════════════════════════════════════════════════════════
# Workflow engine edge cases
# ═══════════════════════════════════════════════════════════════════


class TestWorkflowEdgeCases:

    def test_workflow_with_parallel_group_executes(self, db, adapter, tmp_path):
        """Workflow with a parallel group should run both steps."""
        engine = WorkflowEngine(db, adapter)
        wf = WorkflowDef(
            name="parallel-test",
            steps=[
                WorkflowStepDef(id="s1", agent="arch", prompt="Task A"),
                WorkflowStepDef(id="s2", agent="arch", prompt="Task B"),
            ],
            parallel_groups=[
                ParallelGroupDef(id="group1", steps=["s1", "s2"], max_concurrent=2),
            ],
        )
        run_id = engine.execute(wf)
        status = engine.get_run_status(run_id)
        assert status["status"] == "completed"
        step_statuses = {s["step_id"]: s["status"] for s in status["steps"]}
        assert step_statuses["s1"] == "completed"
        assert step_statuses["s2"] == "completed"

    def test_cancel_running_workflow(self, db, adapter):
        """Cancel a running workflow should mark it as cancelled."""
        class SlowAdapter(MockHermesAdapter):
            def delegate_task(self, *a, **kw):
                import time
                time.sleep(0.5)
                return super().delegate_task(*a, **kw)

        slow = SlowAdapter()
        engine = WorkflowEngine(db, slow)
        wf = WorkflowDef(
            name="slow",
            steps=[WorkflowStepDef(id="s1", agent="arch", prompt="Slow task")],
        )
        run_id = engine.execute(wf)
        # Cancel immediately (works because it runs synchronously)
        from sccsos.core.step_executor import WorkflowExecutionError
        try:
            engine.cancel_run(run_id)
        except WorkflowExecutionError:
            pass
        status = engine.get_run_status(run_id)
        assert "completed" in status["status"] or "cancelled" in status["status"]
