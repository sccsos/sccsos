"""WebSocket endpoint and EventBus broadcast for sccsos API.

Provides real-time event streaming to the Vue admin console.
All EventBus events are broadcast to all connected WebSocket clients.

Event types broadcast:
- workflow.started / completed / failed
- agent.created / started / stopped / paused / resumed / failed
- skill.submitted / approved / rejected / rated
- system.health (periodic status summary)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

# Module-level set of connected WebSocket clients
connected_clients: set[WebSocket] = set()


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
    """
    from sccsos.core.event_bus import EventBus

    bus = EventBus.get_instance()

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
