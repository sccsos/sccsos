"""WebSocket endpoint and EventBus broadcast for sccsos API."""
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
    """Wire EventBus events to WebSocket broadcast."""
    from sccsos.core.event_bus import EventBus, WORKFLOW_STARTED, WORKFLOW_COMPLETED, WORKFLOW_FAILED
    bus = EventBus.get_instance()
    bus.on(WORKFLOW_STARTED, lambda **kw: broadcast("workflow.started", **kw))
    bus.on(WORKFLOW_COMPLETED, lambda **kw: broadcast("workflow.completed", **kw))
    bus.on(WORKFLOW_FAILED, lambda **kw: broadcast("workflow.failed", **kw))
