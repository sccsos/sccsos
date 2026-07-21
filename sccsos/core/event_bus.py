"""EventBus — lightweight pub/sub event bus for workflow lifecycle.

Decouples event producers (WorkflowEngine, StepExecutor) from
observers (Tracer, Auditor, WebhookNotifier, AlertManager).

Architecture::

    EventBusABC  (abstract interface)
        │
        ├── LocalEventBus  (in-process, singleton, with persistence)
        └── KafkaEventBus  (distributed, via kafka-python, sccsos[kafka])

Usage::

    # Default (local in-process)
    from sccsos.core.event_bus import LocalEventBus
    bus = LocalEventBus.get_instance()
    bus.on("workflow.completed", my_handler)
    bus.emit("workflow.completed", run_id="xxx")

    # Kafka backend (requires sccsos[kafka] extras)
    from sccsos.core.event_bus import configure_event_bus
    configure_event_bus(backend="kafka", bootstrap_servers="localhost:9092")
    bus = EventBus.get_instance()  # Now returns KafkaEventBus

Event name constants are in ``sccsos.core.events``::

    from sccsos.core.events import WORKFLOW_COMPLETED
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable

from sccsos.core.events import (
    WORKFLOW_STARTED,
    WORKFLOW_COMPLETED,
    WORKFLOW_FAILED,
    WORKFLOW_CANCELLED,
    STEP_STARTED,
    STEP_COMPLETED,
    STEP_FAILED,
    STEP_SKIPPED,
)


logger = logging.getLogger("sccsos.event_bus")


# ── Abstract Interface ─────────────────────────────────────────────


class EventBusABC(ABC):
    """Abstract event bus — allows swapping in-process pub/sub for
    a distributed message broker (Kafka, RabbitMQ) without changing
    producers or consumers.
    """

    @abstractmethod
    def on(self, event: str, handler: Callable[..., Any]) -> None:
        """Register a handler for an event pattern."""

    @abstractmethod
    def off(self, event: str, handler: Callable[..., Any]) -> None:
        """Remove a specific handler from an event."""

    @abstractmethod
    def emit(self, event: str, **data: Any) -> None:
        """Emit an event to all registered handlers."""

    @abstractmethod
    def has_handlers(self, event: str) -> bool:
        """Check if an event has any registered handlers."""

    @abstractmethod
    def clear(self) -> None:
        """Remove all handlers."""

    def set_persist(self, fn: Callable[[str, dict], None] | None) -> None:
        """Set an optional persistence callback (not all backends
        support this)."""
        pass


# Module-level singleton (shared across the process)
_local_bus: EventBusABC | None = None


def configure_event_bus(
    backend: str = "local",
    bootstrap_servers: str = "localhost:9092",
    client_id: str = "sccsos",
    group_id: str = "sccsos-events",
) -> None:
    """Configure the global event bus backend.

    Must be called before the first ``get_instance()`` call or
    before any handlers are registered.  Call it early in
    ``AgentRuntime.initialize()``.

    Args:
        backend: ``"local"`` (default, in-process) or ``"kafka"``.
        bootstrap_servers: Kafka broker address (ignored for ``"local"``).
        client_id: Kafka producer/consumer client ID.
        group_id: Kafka consumer group ID.
    """
    global _local_bus
    if _local_bus is not None:
        logger.warning("Event bus already initialised; reconfiguring")

    if backend == "kafka":
        from sccsos.core.event_bus_kafka import KafkaEventBus
        _local_bus = KafkaEventBus(
            bootstrap_servers=bootstrap_servers,
            client_id=client_id,
            group_id=group_id,
        )
        logger.info(
            "Event bus backend set to kafka (%s)", bootstrap_servers,
        )
    else:
        _local_bus = LocalEventBus()
        logger.info("Event bus backend set to local (in-process)")


class LocalEventBus(EventBusABC):
    """In-process pub/sub event bus with isolated handler failures.

    Each handler runs inside a try/except — a single failing handler
    never blocks others. Exceptions are logged at ERROR level but
    never propagated to the emitter.

    Supports an optional persistence callback for durable event storage
    (e.g. to SQLite) so events can survive process restarts.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[..., Any]]] = {}
        self._persist_fn: Callable[[str, dict], None] | None = None

    def set_persist(self, fn: Callable[[str, dict], None] | None) -> None:
        """Set an optional persistence callback.

        When set, every ``emit()`` call also invokes ``fn(event, data)``
        so events can be stored durably (e.g. to SQLite) for replay
        after a process restart.
        """
        self._persist_fn = fn

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

        When a persistence callback is configured (via ``set_persist``),
        the event is also persisted durably before any handler runs.

        Args:
            event: Event name (e.g. ``"workflow.completed"``).
            **data: Keyword arguments passed to each handler.
        """
        # Persist before dispatch (best-effort)
        if self._persist_fn is not None:
            try:
                self._persist_fn(event, data)
            except Exception:
                logger.exception("Event persist failed for '%s'", event)

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
    def get_instance(cls) -> EventBusABC:
        """Get the process-wide LocalEventBus singleton."""
        global _local_bus
        if _local_bus is None:
            _local_bus = cls()
        return _local_bus

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton (used in tests)."""
        global _local_bus
        _local_bus = None


# -- Public API: get_bus is the single entry point --

def get_bus() -> EventBusABC:
    """Get the configured event bus instance.

    Returns the global event bus (local or Kafka, depending on
    ``configure_event_bus()``).  Falls back to ``LocalEventBus``
    if not yet configured.
    """
    global _local_bus
    if _local_bus is None:
        _local_bus = LocalEventBus()
    return _local_bus
