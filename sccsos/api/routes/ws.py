"""WebSocket endpoint and EventBus broadcast for sccsos API.

Provides real-time event streaming to the Vue admin console.
All EventBus events are broadcast to all connected WebSocket clients.

Event types broadcast:
- workflow.started / completed / failed
- agent.created / started / stopped / paused / resumed / failed
- skill.submitted / approved / rejected / rated
- system.health (periodic status summary)

Multi-process support via Redis PubSub:
When ``sccsos.yaml redis.enabled = true``, a ``RedisPubSubBridge`` is
wired during ``wire_eventbus()`` to bridge events across all uvicorn
workers. Every worker's EventBus publishes to (and subscribes from)
a shared Redis channel, so WebSocket clients on any worker receive
events from all workers.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("sccsos.ws")

# Module-level set of connected WebSocket clients
connected_clients: set[WebSocket] = set()

# Module-level Redis bridge reference (initialized by wire_eventbus)
_redis_bridge: Any = None


async def websocket_handler(websocket: WebSocket) -> None:
    """Handle a single WebSocket connection."""
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # Keep alive
    except WebSocketDisconnect:
        connected_clients.discard(websocket)


def broadcast(event: str, **data: Any) -> None:
    """Broadcast a JSON message to all connected WebSocket clients."""
    message = json.dumps({"event": event, **data}, ensure_ascii=False, default=str)
    for ws in list(connected_clients):
        try:
            asyncio.ensure_future(ws.send_text(message))
        except Exception:
            connected_clients.discard(ws)


def wire_eventbus() -> None:
    """Wire EventBus events to WebSocket broadcast.

    Listens for all major event types and broadcasts them
    to connected admin console clients.

    When Redis PubSub is configured, also wires a
    ``RedisPubSubBridge`` for cross-process event delivery.
    """
    from sccsos.core.event_bus import get_bus

    bus = get_bus()

    # Workflow events
    bus.on("workflow.started", lambda **kw: broadcast("workflow.started", **kw))
    bus.on("workflow.completed", lambda **kw: broadcast("workflow.completed", **kw))
    bus.on("workflow.failed", lambda **kw: broadcast("workflow.failed", **kw))

    # Agent lifecycle events
    bus.on("agent.created", lambda **kw: broadcast("agent.created", **kw))
    bus.on("agent.started", lambda **kw: broadcast("agent.started", **kw))
    bus.on("agent.stopped", lambda **kw: broadcast("agent.stopped", **kw))
    bus.on("agent.paused", lambda **kw: broadcast("agent.paused", **kw))
    bus.on("agent.resumed", lambda **kw: broadcast("agent.resumed", **kw))
    bus.on("agent.failed", lambda **kw: broadcast("agent.failed", **kw))

    # Skill market events
    bus.on("skill.submitted", lambda **kw: broadcast("skill.submitted", **kw))
    bus.on("skill.approved", lambda **kw: broadcast("skill.approved", **kw))
    bus.on("skill.rejected", lambda **kw: broadcast("skill.rejected", **kw))
    bus.on("skill.rated", lambda **kw: broadcast("skill.rated", **kw))

    # ── Redis PubSub bridge (multi-process support) ──────────────
    _wire_redis_bridge(bus)


def _wire_redis_bridge(bus: Any) -> None:
    """Optionally wire Redis PubSub bridge from config.

    Activated when ``sccsos.yaml redis.enabled = true``.
    Best-effort — Redis or config issues are logged but do not
    prevent the server from starting.
    """
    global _redis_bridge
    try:
        from sccsos.core.config import get_config

        cfg = get_config().redis
        if not cfg.enabled:
            return

        from sccsos.core.event_bus_redis import RedisPubSubBridge

        bridge = RedisPubSubBridge(
            redis_url=cfg.url,
            channel=cfg.channel,
        )
        bridge.wire_publish(bus)
        bridge.start_subscriber(bus)
        _redis_bridge = bridge
        logger.info(
            "Redis PubSub bridge enabled: %s (channel: %s)",
            cfg.url, cfg.channel,
        )
    except Exception as e:
        logger.warning("Redis PubSub bridge setup failed: %s", e)


def get_redis_bridge_status() -> dict[str, Any]:
    """Return Redis bridge status for health endpoint."""
    if _redis_bridge is None:
        return {"enabled": False}
    return {"enabled": True, **_redis_bridge.get_status()}
