"""EventBus — lightweight pub/sub event bus for workflow lifecycle.

Decouples event producers (WorkflowEngine, StepExecutor) from
observers (Tracer, Auditor, WebhookNotifier, AlertManager).

Usage:
    bus = EventBus.get_instance()

    # Subscribe
    bus.on("workflow.completed", tracer_span_handler)

    # Emit
    bus.emit("workflow.completed", run_id="xxx", status="ok")
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger("sccsos.event_bus")

# Module-level singleton (shared across the process)
_event_bus: EventBus | None = None


class EventBus:
    """Lightweight pub/sub event bus with isolated handler failures.

    Each handler runs inside a try/except — a single failing handler
    never blocks others. Exceptions are logged at ERROR level but
    never propagated to the emitter.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[..., Any]]] = {}

    # ── Public API ───────────────────────────────────────────────

    def on(self, event: str, handler: Callable[..., Any]) -> None:
        """Register a handler for an event pattern.

        Multiple handlers can be registered for the same event.
        Handlers are called in registration order.
        """
        self._handlers.setdefault(event, []).append(handler)

    def off(self, event: str, handler: Callable[..., Any]) -> None:
        """Remove a specific handler from an event."""
        handlers = self._handlers.get(event, [])
        if handler in handlers:
            handlers.remove(handler)

    def emit(self, event: str, **data: Any) -> None:
        """Emit an event to all registered handlers.

        Each handler runs in a try/except so a single failing
        handler never blocks others.

        Args:
            event: Event name (e.g. ``"workflow.completed"``).
            **data: Keyword arguments passed to each handler.
        """
        for handler in self._handlers.get(event, []):
            try:
                handler(**data)
            except Exception:
                logger.exception(
                    "Event handler '%s' failed for event '%s' with data %s",
                    getattr(handler, "__name__", "?"),
                    event,
                    {k: str(v)[:100] for k, v in data.items()},
                )

    def has_handlers(self, event: str) -> bool:
        """Check if an event has any registered handlers (for tests)."""
        return bool(self._handlers.get(event))

    def clear(self) -> None:
        """Remove all handlers (for tests)."""
        self._handlers.clear()

    # ── Singleton ────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> EventBus:
        """Get the process-wide EventBus singleton."""
        global _event_bus
        if _event_bus is None:
            _event_bus = cls()
        return _event_bus

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton (used in tests)."""
        global _event_bus
        _event_bus = None


# ── Event name constants ────────────────────────────────────────────
# Canonical event names used throughout the system.  Import these
# instead of using raw strings to avoid typos.

WORKFLOW_STARTED = "workflow.started"
WORKFLOW_COMPLETED = "workflow.completed"
WORKFLOW_FAILED = "workflow.failed"
WORKFLOW_CANCELLED = "workflow.cancelled"

STEP_STARTED = "step.started"
STEP_COMPLETED = "step.completed"
STEP_FAILED = "step.failed"
STEP_SKIPPED = "step.skipped"
