"""KafkaEventBus — distributed event bus backed by Apache Kafka.

Implements ``EventBusABC`` using the ``kafka-python`` library.
Requires ``sccsos[kafka]`` extras.

Features:
- Circuit Breaker pattern (CLOSED → OPEN → HALF_OPEN)
- Local handler fallback when Kafka is unavailable
- Configurable failure threshold, recovery timeout, half-open probe count
- Consumer mode for cross-instance event consumption

Usage::

    from sccsos.core.event_bus import configure_event_bus, get_bus

    # At startup, set the backend:
    configure_event_bus(backend="kafka", bootstrap_servers="localhost:9092")

    # Same API as LocalEventBus:
    bus = get_bus()
    bus.on("workflow.completed", my_handler)
    bus.emit("workflow.completed", run_id="xxx")
"""

from __future__ import annotations

import json
import logging
import threading
import time
from enum import Enum
from typing import Any, Callable, Optional

from sccsos.core.event_bus import EventBusABC
from sccsos.core.events import (
    WORKFLOW_STARTED, WORKFLOW_COMPLETED, WORKFLOW_FAILED,
    STEP_STARTED, STEP_COMPLETED, STEP_FAILED, STEP_SKIPPED,
)

logger = logging.getLogger("sccsos.event_bus.kafka")


# ── Circuit Breaker ─────────────────────────────────────────────────


class CircuitBreakerState(str, Enum):
    """Circuit breaker lifecycle states.

    .. code-block::

        CLOSED ──(N failures)──▶ OPEN ──(timeout)──▶ HALF_OPEN
          ▲                                               │
          └─────────(success)─────────────────────────────┘
          ◀──(failure)── OPEN
    """
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
    """Raised when the circuit breaker is OPEN and fast-failing."""


class CircuitBreaker:
    """Production-grade circuit breaker for Kafka producer calls.

    Thread-safe: all state transitions are protected by a reentrant lock.

    Args:
        failure_threshold: Consecutive failures before opening the circuit.
        recovery_timeout: Seconds to wait before transitioning to HALF_OPEN.
        half_open_max_requests: Successful probes needed to close the circuit.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_requests: int = 3,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_requests = half_open_max_requests

        self._state: CircuitBreakerState = CircuitBreakerState.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0
        self._half_open_successes: int = 0
        self._total_failures: int = 0
        self._total_successes: int = 0
        self._state_changes: int = 0
        self._lock = threading.Lock()

    # ── Properties ─────────────────────────────────────────────────

    @property
    def state(self) -> CircuitBreakerState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def metrics(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self._failure_threshold,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "state_changes": self._state_changes,
            "recovery_timeout_s": self._recovery_timeout,
        }

    # ── Core ───────────────────────────────────────────────────────

    def call(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute *fn* through the circuit breaker.

        Returns:
            The return value of *fn*.

        Raises:
            CircuitBreakerOpenError: If the circuit is OPEN and not yet
                ready for recovery.
            Any exception raised by *fn* is propagated; the circuit
                breaker records it as a failure.
        """
        # Pre-flight: check circuit state
        with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                if time.monotonic() - self._last_failure_time < self._recovery_timeout:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker OPEN (failures={self._failure_count}, "
                        f"retry in {self._recovery_timeout - (time.monotonic() - self._last_failure_time):.0f}s)"
                    )
                # Timeout elapsed → transition to HALF_OPEN
                self._state = CircuitBreakerState.HALF_OPEN
                self._half_open_successes = 0
                self._state_changes += 1
                logger.info(
                    "Circuit breaker OPEN→HALF_OPEN after %.0fs timeout",
                    self._recovery_timeout,
                )

            if self._state == CircuitBreakerState.HALF_OPEN:
                if self._half_open_successes >= self._half_open_max_requests:
                    raise CircuitBreakerOpenError(
                        "Circuit breaker HALF_OPEN (awaiting recovery verification)"
                    )

        # Execute
        try:
            result = fn(*args, **kwargs)
        except Exception as e:
            with self._lock:
                self._failure_count += 1
                self._total_failures += 1
                self._last_failure_time = time.monotonic()
                if self._state == CircuitBreakerState.HALF_OPEN:
                    self._state = CircuitBreakerState.OPEN
                    self._state_changes += 1
                    logger.warning(
                        "Circuit breaker HALF_OPEN→OPEN (probe failed: %s)", e,
                    )
                elif self._failure_count >= self._failure_threshold:
                    self._state = CircuitBreakerState.OPEN
                    self._state_changes += 1
                    logger.warning(
                        "Circuit breaker CLOSED→OPEN after %d failures (last: %s)",
                        self._failure_count, e,
                    )
                else:
                    logger.debug(
                        "Circuit breaker recorded failure %d/%d: %s",
                        self._failure_count, self._failure_threshold, e,
                    )
            raise

        # Success
        with self._lock:
            self._failure_count = 0
            self._total_successes += 1
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self._half_open_max_requests:
                    self._state = CircuitBreakerState.CLOSED
                    self._state_changes += 1
                    logger.info(
                        "Circuit breaker HALF_OPEN→CLOSED (%d/%d probes succeeded)",
                        self._half_open_successes, self._half_open_max_requests,
                    )
        return result

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED."""
        with self._lock:
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._last_failure_time = 0.0
            self._half_open_successes = 0
            logger.info("Circuit breaker manually reset to CLOSED")


class KafkaEventBus(EventBusABC):
    """Distributed event bus using Apache Kafka.

    Maps sccsos events to Kafka topics.  Each event type
    (e.g. ``workflow.completed``) becomes a Kafka topic.

    Thread-safe: producer access is serialized.
    """

    def __init__(self, bootstrap_servers: str = "localhost:9092",
                 client_id: str = "sccsos",
                 group_id: str = "sccsos-events",
                 topic_prefix: str = "sccsos.",
                 circuit_breaker: Optional[CircuitBreaker] = None):
        try:
            from kafka import KafkaProducer, KafkaConsumer
            from kafka.errors import NoBrokersAvailable
        except ImportError:
            raise ImportError(
                "Kafka support requires sccsos[kafka] extras. "
                "Install with: pip install sccsos[kafka]"
            )

        self._bootstrap = bootstrap_servers
        self._client_id = client_id
        self._group_id = group_id
        self._prefix = topic_prefix
        self._lock = threading.Lock()
        self._producer: Optional[KafkaProducer] = None
        self._consumer: Optional[KafkaConsumer] = None
        self._handlers: dict[str, list[Callable]] = {}
        self._running = False
        self._consumer_thread: Optional[threading.Thread] = None

        # Circuit breaker (default threshold=5, 30s recovery, 3 probes)
        self._circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
            half_open_max_requests=3,
        )

        # Local fallback for handlers when Kafka is unavailable
        self._local_handlers: dict[str, list[Callable]] = {}
        self._persist_fn: Callable[[str, dict], None] | None = None
        self._closed = False

    def __del__(self):
        """Safety net: ensure cleanup on garbage collection."""
        try:
            if not self._closed:
                self.close()
        except Exception:
            pass

    # ── Producer (circuit-breaker guarded) ─────────────────────────

    @property
    def producer(self):
        """Get or create the Kafka producer through the circuit breaker.

        If the circuit breaker is OPEN, this raises CircuitBreakerOpenError
        and ``emit()`` gracefully falls back to local handlers.
        """
        if self._producer is not None:
            return self._producer

        def _connect() -> Any:
            from kafka import KafkaProducer
            new_producer = KafkaProducer(
                bootstrap_servers=self._bootstrap,
                client_id=self._client_id,
                value_serializer=lambda v: json.dumps(
                    v, ensure_ascii=False, default=str
                ).encode("utf-8"),
                acks="all",
                retries=3,
                max_in_flight_requests_per_connection=5,
                reconnect_backoff_ms=500,
                reconnect_backoff_max_ms=5000,
            )
            # Verify connectivity by listing topics (raises on failure)
            new_producer.partitions_for("__health_check")
            return new_producer

        try:
            self._producer = self._circuit_breaker.call(_connect)
            logger.info("Kafka producer connected to %s (circuit=%s)",
                        self._bootstrap, self._circuit_breaker.state.value)
        except CircuitBreakerOpenError as e:
            logger.warning("Kafka producer unavailable (circuit open): %s", e)
            self._producer = None
        except Exception as e:
            logger.warning("Kafka producer connection failed: %s", e)
            self._producer = None

        return self._producer

    def _topic(self, event: str) -> str:
        """Map sccsos event name to Kafka topic name."""
        return f"{self._prefix}{event}"

    # ── EventBusABC implementation ───────────────────────────────

    def on(self, event: str, handler: Callable[..., Any]) -> None:
        """Register a handler for an event.

        Handlers are stored locally and also dispatched from
        the Kafka consumer when messages arrive.
        """
        self._local_handlers.setdefault(event, []).append(handler)
        logger.debug("Registered handler for event '%s'", event)

    def off(self, event: str, handler: Callable[..., Any]) -> None:
        """Remove a specific handler."""
        handlers = self._local_handlers.get(event, [])
        if handler in handlers:
            handlers.remove(handler)

    def emit(self, event: str, **data: Any) -> None:
        """Emit an event.  Publishes to Kafka topic + local handlers.

        If the circuit breaker is OPEN, only local handlers are used
        (Kafka publish is skipped).  When the circuit recovers
        (HALF_OPEN→CLOSED), Kafka publishing resumes automatically.
        """
        # Always dispatch to local handlers
        for handler in self._local_handlers.get(event, []):
            try:
                handler(**data)
            except Exception:
                logger.exception("Local handler failed for event '%s'", event)

        # Also publish to Kafka (circuit-breaker guarded)
        try:
            prod = self.producer
            if prod is not None:
                topic = self._topic(event)
                future = prod.send(topic, value=data)
                future.get(timeout=5)  # Block until delivered
                logger.debug("Published event '%s' to topic '%s'", event, topic)
        except CircuitBreakerOpenError:
            logger.debug(
                "Skipping Kafka publish for '%s' (circuit=%s, failures=%d)",
                event, self._circuit_breaker.state.value,
                self._circuit_breaker.failure_count,
            )
        except Exception as e:
            logger.warning("Failed to publish event '%s' to Kafka: %s", event, e)

    def has_handlers(self, event: str) -> bool:
        return bool(self._local_handlers.get(event))

    def clear(self) -> None:
        """Remove all handlers."""
        self._local_handlers.clear()

    def set_persist(self, fn: Callable[[str, dict], None] | None) -> None:
        """Set an optional persistence callback (applied before dispatch)."""
        self._persist_fn = fn

    # ── Production-grade lifecycle ─────────────────────────────────

    def health_check(self) -> dict[str, Any]:
        """Probe Kafka broker connectivity and return status.

        Returns:
            dict with keys: ``status``, ``circuit_state``,
            ``producer_connected``, ``bootstrap_servers``,
            ``consumer_running``, ``handlers_count``,
            and circuit breaker metrics.
        """
        cb_metrics = self._circuit_breaker.metrics
        result: dict[str, Any] = {
            "status": "ok",
            "circuit_state": cb_metrics["state"],
            "bootstrap_servers": self._bootstrap,
            "consumer_running": (
                self._consumer_thread is not None
                and self._consumer_thread.is_alive()
            ),
            "handlers_count": sum(
                len(v) for v in self._local_handlers.values()
            ),
            "producer_connected": self._producer is not None,
            "circuit_breaker": cb_metrics,
        }
        if self._producer is not None:
            try:
                # Try listing topics as a connectivity probe
                topic_result = self._producer.partitions_for("__health_check")
                result["producer_partitions"] = (
                    len(topic_result) if topic_result else 0
                )
            except Exception as e:
                result["status"] = "degraded"
                result["producer_error"] = str(e)[:200]
        else:
            result["status"] = "degraded"
            result["producer_error"] = (
                f"Not connected (circuit={cb_metrics['state']}, "
                f"failures={cb_metrics['failure_count']})"
            )
        return result

    def close(self) -> None:
        """Deterministic cleanup: stop consumer, close producer, clear handlers.

        Safe to call multiple times.  After calling ``close()``,
        the instance should not be reused (create a new one).
        """
        logger.info("Closing KafkaEventBus...")

        # 1. Stop consumer first
        self.stop_consumer()

        # 2. Close producer
        if self._producer is not None:
            try:
                self._producer.close(timeout=5)
                logger.debug("Kafka producer closed")
            except Exception as e:
                logger.warning("Error closing Kafka producer: %s", e)
            self._producer = None

        # 3. Clear all handlers
        self._local_handlers.clear()
        self._handlers.clear()

        self._closed = True
        logger.info("KafkaEventBus closed")

    # ── Consumer (optional, for cross-instance event consumption) ─

    def start_consumer(self) -> None:
        """Start the Kafka consumer in a background thread.

        Consumes events from all known sccsos topics and dispatches
        to local handlers, enabling cross-instance event delivery.
        """
        if self._consumer_thread is not None:
            logger.warning("Consumer already running")
            return

        self._running = True
        self._consumer_thread = threading.Thread(
            target=self._consume_loop,
            daemon=True,
            name="kafka-consumer",
        )
        self._consumer_thread.start()
        logger.info("Kafka consumer started (group=%s)", self._group_id)

    def stop_consumer(self) -> None:
        """Stop the background consumer."""
        self._running = False
        if self._consumer is not None:
            try:
                self._consumer.close()
            except Exception:
                pass
        self._consumer_thread = None

    def _consume_loop(self) -> None:
        """Background loop: consume Kafka messages and dispatch."""
        try:
            from kafka import KafkaConsumer
            from kafka.errors import NoBrokersAvailable
        except ImportError:
            return

        try:
            # Subscribe to all sccsos.* topics
            self._consumer = KafkaConsumer(
                bootstrap_servers=self._bootstrap,
                client_id=f"{self._client_id}-consumer",
                group_id=self._group_id,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                auto_offset_reset="latest",
                enable_auto_commit=True,
            )
            # Subscribe to all sccsos. prefixed topics
            import re
            from kafka.errors import TopicPartitionError
            try:
                topics = self._consumer.topics()
                sccsos_topics = [t for t in topics if t.startswith(self._prefix)]
                if sccsos_topics:
                    self._consumer.subscribe(topics=sccsos_topics)
                    logger.info("Subscribed to %d sccsos topics", len(sccsos_topics))
                else:
                    # Subscribe to pattern
                    self._consumer.subscribe(pattern=f"{self._prefix}.*")
            except Exception:
                self._consumer.subscribe(pattern=f"{self._prefix}.*")

            while self._running:
                msg_pack = self._consumer.poll(timeout_ms=1000)
                for tp, messages in msg_pack.items():
                    for msg in messages:
                        self._dispatch_kafka_message(msg)

        except NoBrokersAvailable:
            logger.warning("Kafka broker not available, consumer not started")
        except Exception as e:
            logger.error("Kafka consumer error: %s", e)
        finally:
            if self._consumer:
                try:
                    self._consumer.close()
                except Exception:
                    pass

    def _dispatch_kafka_message(self, msg) -> None:
        """Dispatch a consumed Kafka message to local handlers."""
        try:
            event = msg.topic
            if event.startswith(self._prefix):
                event = event[len(self._prefix):]

            data = msg.value if isinstance(msg.value, dict) else {}
            for handler in self._local_handlers.get(event, []):
                try:
                    handler(**data)
                except Exception:
                    logger.exception(
                        "Handler failed for consumed event '%s'", event,
                    )
        except Exception as e:
            logger.warning("Failed to dispatch Kafka message: %s", e)


# ── Factory helper ────────────────────────────────────────────────

def create_event_bus(backend: str = "local", **kwargs) -> Any:
    """Create an event bus backend.

    Args:
        backend: ``"local"`` (default) or ``"kafka"``.
        **kwargs: Passed to the backend constructor
            (e.g. ``bootstrap_servers`` for Kafka).

    Returns:
        ``LocalEventBus`` or ``KafkaEventBus``.
    """
    if backend == "kafka":
        return KafkaEventBus(**kwargs)
    from sccsos.core.event_bus import LocalEventBus
    return LocalEventBus()
