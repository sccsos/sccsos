"""Edge case tests covering boundary conditions."""
from __future__ import annotations

import pytest

from sccsos.core.event_bus import get_bus, LocalEventBus, WORKFLOW_STARTED, WORKFLOW_COMPLETED


@pytest.fixture(autouse=True)
def reset_bus():
    """Reset EventBus singleton before and after each test."""
    LocalEventBus.reset_instance()
    yield
    LocalEventBus.reset_instance()


class TestEventBusEdgeCases:
    """Edge cases for EventBus (singleton, Kafka not needed)."""

    @pytest.fixture
    def bus(self):
        return get_bus()

    def test_emit_before_any_handlers(self, bus):
        """Emit with no handlers at all — should not raise."""
        bus.emit("unknown.event", data=42)

    def test_off_unregistered_handler(self, bus):
        """Removing a handler that was never registered should not raise."""

        def handler(**kw):
            pass

        bus.off("test.event", handler)  # Should not raise

    def test_off_wrong_event(self, bus):
        """Removing a handler from wrong event should not raise."""

        def handler(**kw):
            pass

        bus.on("event_a", handler)
        bus.off("event_b", handler)  # No-op

    def test_handler_that_emits_another_event(self, bus):
        """Handler that emits a different event should not cause infinite loop."""
        results = []

        def trigger(**kw):
            results.append("triggered")
            bus.emit("second.event", val=99)

        bus.on("first.event", trigger)

        second_results = []

        def second(**kw):
            second_results.append(kw.get("val"))

        bus.on("second.event", second)

        bus.emit("first.event", msg="start")
        assert results == ["triggered"]
        assert second_results == [99]

    def test_register_emit_on_same_object(self, bus):
        """Register and emit on the same event should process correctly."""
        received = []

        bus.on(WORKFLOW_STARTED, lambda **kw: received.append(kw.get("run_id")))
        bus.on(WORKFLOW_COMPLETED, lambda **kw: received.append(kw.get("status")))

        bus.emit(WORKFLOW_STARTED, run_id="wf_1", status="running")
        assert received == ["wf_1"]

        bus.emit(WORKFLOW_COMPLETED, status="done")
        assert received == ["wf_1", "done"]
