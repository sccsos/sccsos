"""Redis PubSub Bridge — cross-process EventBus broadcast via Redis.

Bridges EventBus events across multiple uvicorn workers (or any
multi-process deployment) using Redis PubSub. Each worker subscribes
to a shared Redis channel; events emitted on any worker are forwarded
to all workers' local EventBus instances.

Architecture::

    Worker-1                          Worker-2
    ┌─────────────────┐              ┌─────────────────┐
    │ EventBus        │              │ EventBus        │
    │   └→ RedisPub   │───Redis────▶│   ┌→ subscribers │
    │   ┌← RedisSub   │◀──channel───│   └← RedisPub    │
    └─────────────────┘              └─────────────────┘

Usage::

    from sccsos.core.event_bus_redis import RedisPubSubBridge
    from sccsos.core.event_bus import get_bus

    bridge = RedisPubSubBridge(
        redis_url="redis://localhost:6379/0",
        channel="sccsos:events",
        worker_id="worker-1",
    )

    # Wire: local emit → Redis publish
    bridge.wire_publish(get_bus())

    # Wire: Redis subscribe → local EventBus re-emit
    # Run this in an asyncio task or background thread
    bridge.start_subscriber(get_bus())
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("sccsos.event_bus_redis")


class RedisPubSubBridge:
    """Cross-process EventBus bridge using Redis PubSub.

    Each uvicorn worker creates one bridge instance. The bridge:

    1. Listens for ALL events on the local EventBus and publishes them
       to a Redis channel (via ``wire_publish()``).
    2. Subscribes to the same Redis channel and re-emits received
       events to the local EventBus (via ``start_subscriber()``).

    A ``_source_worker`` field in the Redis message prevents
    infinite loops — events published by THIS worker are skipped
    when received back from Redis.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        channel: str = "sccsos:events",
        worker_id: Optional[str] = None,
    ):
        self._redis_url = redis_url
        self._channel = channel
        self._worker_id = worker_id or os.environ.get(
            "HOSTNAME", f"worker-{os.getpid()}"
        )
        self._pubsub: Any = None  # redis PubSub object
        self._redis_client: Any = None
        self._subscriber_thread: Optional[threading.Thread] = None
        self._running = False
        self._redis_available: bool | None = None  # None = untested

    # ── Publish side (called from EventBus handler) ──────────────

    def _get_client(self):
        """Lazy-init Redis client.

        Returns None if redis-py is not installed or connection fails.
        """
        if self._redis_client is not None:
            return self._redis_client
        try:
            import redis as _redis
            self._redis_client = _redis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            self._redis_client.ping()
            self._redis_available = True
            logger.info(
                "Redis connected: %s (channel: %s, worker: %s)",
                self._redis_url, self._channel, self._worker_id,
            )
            return self._redis_client
        except ImportError:
            logger.warning(
                "redis-py not installed. Install with: pip install sccsos[redis]"
            )
            self._redis_available = False
            return None
        except Exception as e:
            logger.warning(
                "Redis not available at %s: %s", self._redis_url, e,
            )
            self._redis_available = False
            return None

    def wire_publish(self, local_bus: Any) -> None:
        """Wire a catch-all handler on the local EventBus to publish
        all events to Redis.  Best-effort — Redis failures are logged
        but never propagated.

        Args:
            local_bus: An ``EventBusABC`` instance (from ``get_bus()``).
        """
        def _publish(event: str, **data: Any) -> None:
            try:
                client = self._get_client()
                if client is None:
                    return
                message = json.dumps({
                    "event": event,
                    "data": data,
                    "_source_worker": self._worker_id,
                }, ensure_ascii=False, default=str)
                client.publish(self._channel, message)
            except Exception:
                logger.debug("Redis publish failed for '%s'", event, exc_info=True)

        # Wrap in a closure that captures the raw event name — EventBus
        # passes it as the function name, not as a kwarg
        def make_handler(evt: str) -> Callable[..., None]:
            def handler(**kw: Any) -> None:
                _publish(evt, **kw)
            return handler

        # Register for all known event types from events.py
        from sccsos.core.events import (
            WORKFLOW_STARTED, WORKFLOW_COMPLETED, WORKFLOW_FAILED, WORKFLOW_CANCELLED,
            STEP_STARTED, STEP_COMPLETED, STEP_FAILED, STEP_SKIPPED,
        )
        for evt in [
            WORKFLOW_STARTED, WORKFLOW_COMPLETED, WORKFLOW_FAILED, WORKFLOW_CANCELLED,
            STEP_STARTED, STEP_COMPLETED, STEP_FAILED, STEP_SKIPPED,
            "agent.created", "agent.started", "agent.stopped",
            "agent.paused", "agent.resumed", "agent.failed",
            "skill.submitted", "skill.approved", "skill.rejected", "skill.rated",
            "workflow.started", "workflow.completed", "workflow.failed",
            "system.health",
        ]:
            local_bus.on(evt, make_handler(evt))

        logger.info(
            "Redis publish wired: %d events → channel '%s'",
            len([
                WORKFLOW_STARTED, WORKFLOW_COMPLETED, WORKFLOW_FAILED, WORKFLOW_CANCELLED,
                STEP_STARTED, STEP_COMPLETED, STEP_FAILED, STEP_SKIPPED,
                "agent.created", "agent.started", "agent.stopped",
                "agent.paused", "agent.resumed", "agent.failed",
                "skill.submitted", "skill.approved", "skill.rejected", "skill.rated",
                "workflow.started", "workflow.completed", "workflow.failed",
                "system.health",
            ]),
            self._channel,
        )

    # ── Subscribe side (background thread) ──────────────────────

    def start_subscriber(self, local_bus: Any) -> None:
        """Start a daemon thread that subscribes to the Redis channel
        and re-emits received events to the local EventBus.

        Events originating from THIS worker (same ``_source_worker``)
        are silently skipped to prevent infinite loops.

        Must be called after ``wire_publish()`` on each worker.

        Args:
            local_bus: An ``EventBusABC`` instance.
        """
        if self._subscriber_thread is not None and self._subscriber_thread.is_alive():
            logger.warning("Redis subscriber already running")
            return

        self._running = True
        self._subscriber_thread = threading.Thread(
            target=self._subscriber_loop,
            args=(local_bus,),
            daemon=True,
            name="redis-pubsub-subscriber",
        )
        self._subscriber_thread.start()
        logger.info(
            "Redis subscriber started: channel '%s' (worker: %s)",
            self._channel, self._worker_id,
        )

    def stop_subscriber(self) -> None:
        """Stop the subscriber thread gracefully."""
        self._running = False
        if self._pubsub is not None:
            try:
                self._pubsub.close()
            except Exception:
                pass

    def _subscriber_loop(self, local_bus: Any) -> None:
        """Background loop: listen on Redis channel, re-emit to local EventBus."""
        reconnect_delay = 1.0
        while self._running:
            try:
                client = self._get_client()
                if client is None:
                    time.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 30)
                    continue

                pubsub = client.pubsub()
                pubsub.subscribe(self._channel)
                self._pubsub = pubsub
                reconnect_delay = 1.0  # Reset on successful connect

                for message in pubsub.listen():
                    if not self._running:
                        break
                    if message["type"] != "message":
                        continue
                    self._handle_redis_message(message, local_bus)

            except Exception as e:
                logger.warning(
                    "Redis subscriber error (reconnect in %.0fs): %s",
                    reconnect_delay, e,
                )
                self._pubsub = None
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30)

    def _handle_redis_message(self, message: dict[str, Any], local_bus: Any) -> None:
        """Parse a Redis PubSub message and re-emit to local EventBus.

        Skips events from the same worker (infinite loop prevention).
        """
        try:
            payload = json.loads(message["data"])
        except (json.JSONDecodeError, TypeError, KeyError):
            return

        # Skip our own events
        if payload.get("_source_worker") == self._worker_id:
            return

        event = payload.get("event", "")
        data = payload.get("data", {})
        if not event:
            return

        try:
            local_bus.emit(event, **data)
        except Exception:
            logger.debug(
                "Redis re-emit failed for '%s'", event, exc_info=True,
            )

    # ── Status ──────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        """Check if Redis is connected and the subscriber is running."""
        return (
            self._redis_available is True
            and self._subscriber_thread is not None
            and self._subscriber_thread.is_alive()
        )

    def get_status(self) -> dict[str, Any]:
        """Return current bridge status for health checks."""
        return {
            "redis_url": self._redis_url,
            "channel": self._channel,
            "worker_id": self._worker_id,
            "redis_available": self._redis_available,
            "subscriber_running": (
                self._subscriber_thread is not None
                and self._subscriber_thread.is_alive()
            ),
        }
