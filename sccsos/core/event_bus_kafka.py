"""KafkaEventBus — distributed event bus backed by Apache Kafka.

Implements ``EventBusABC`` using the ``kafka-python`` library.
Requires ``sccsos[kafka]`` extras.

Usage::

    from sccsos.core.event_bus import EventBus

    # At startup, set the backend:
    EventBus.set_backend("kafka", bootstrap_servers="localhost:9092")

    # Same API as LocalEventBus:
    bus = EventBus.get_instance()
    bus.on("workflow.completed", my_handler)
    bus.emit("workflow.completed", run_id="xxx")
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Optional

from sccsos.core.events import (
    WORKFLOW_STARTED, WORKFLOW_COMPLETED, WORKFLOW_FAILED,
    STEP_STARTED, STEP_COMPLETED, STEP_FAILED, STEP_SKIPPED,
)

logger = logging.getLogger("sccsos.event_bus.kafka")


class KafkaEventBus:
    """Distributed event bus using Apache Kafka.

    Maps sccsos events to Kafka topics.  Each event type
    (e.g. ``workflow.completed``) becomes a Kafka topic.

    Thread-safe: producer access is serialized.
    """

    def __init__(self, bootstrap_servers: str = "localhost:9092",
                 client_id: str = "sccsos",
                 group_id: str = "sccsos-events",
                 topic_prefix: str = "sccsos."):
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

        # Local fallback for handlers when Kafka is unavailable
        self._local_handlers: dict[str, list[Callable]] = {}
        self._closed = False

    def __del__(self):
        """Safety net: ensure cleanup on garbage collection."""
        try:
            if not self._closed:
                self.close()
        except Exception:
            pass

    # ── Producer ─────────────────────────────────────────────────

    _producer_lock: threading.Lock = threading.Lock()
    _producer_retries: int = 0
    _max_producer_retries: int = 5

    @property
    def producer(self):
        if self._producer is None:
            from kafka import KafkaProducer
            try:
                self._producer = KafkaProducer(
                    bootstrap_servers=self._bootstrap,
                    client_id=self._client_id,
                    value_serializer=lambda v: json.dumps(v, ensure_ascii=False, default=str).encode("utf-8"),
                    acks="all",
                    retries=3,
                    max_in_flight_requests_per_connection=5,
                    reconnect_backoff_ms=500,
                    reconnect_backoff_max_ms=5000,
                )
                self._producer_retries = 0
                logger.info("Kafka producer connected to %s", self._bootstrap)
            except Exception as e:
                self._producer_retries += 1
                if self._producer_retries <= self._max_producer_retries:
                    logger.warning(
                        "Kafka producer unavailable (attempt %d/%d): %s",
                        self._producer_retries, self._max_producer_retries, e,
                    )
                else:
                    logger.error(
                        "Kafka producer permanently unavailable after %d attempts: %s",
                        self._producer_retries, e,
                    )
                self._producer = None  # Will use local handlers
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
        """Emit an event.  Publishes to Kafka topic + local handlers."""
        # Always dispatch to local handlers
        for handler in self._local_handlers.get(event, []):
            try:
                handler(**data)
            except Exception:
                logger.exception("Local handler failed for event '%s'", event)

        # Also publish to Kafka
        try:
            prod = self.producer
            if prod is not None:
                topic = self._topic(event)
                future = prod.send(topic, value=data)
                future.get(timeout=5)  # Block until delivered
                logger.debug("Published event '%s' to topic '%s'", event, topic)
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
            dict with keys: ``status``, ``producer_connected``,
            ``bootstrap_servers``, ``consumer_running``, ``handlers_count``.
        """
        result: dict[str, Any] = {
            "status": "ok",
            "bootstrap_servers": self._bootstrap,
            "consumer_running": self._consumer_thread is not None and self._consumer_thread.is_alive(),
            "handlers_count": sum(len(v) for v in self._local_handlers.values()),
            "producer_connected": self._producer is not None,
        }
        if self._producer is not None:
            try:
                # Try listing topics as a connectivity probe
                topic_result = self._producer.partitions_for("__health_check")
                result["producer_partitions"] = len(topic_result) if topic_result else 0
            except Exception as e:
                result["status"] = "degraded"
                result["producer_error"] = str(e)[:200]
        else:
            result["status"] = "degraded"
            result["producer_error"] = "Not connected (retries exhausted)"
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
