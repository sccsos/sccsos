"""Agent Message Bus — inter-agent communication layer.

Provides a publish/subscribe API for agents to send and receive
messages across instances.  Built on top of the event bus backend
(LocalEventBus for in-process, KafkaEventBus for distributed).

Message Protocol::

    {
        "msg_id": "uuid",
        "from_agent": "agent-architect",
        "to_agent": "agent-reviewer",        # or "__broadcast__"
        "msg_type": "request | response | broadcast",
        "payload": { ... },
        "timestamp": "2026-07-22T12:00:00Z",
        "correlation_id": "uuid"             # for request/response pairing
    }

Usage::

    from sccsos.core.agent_message_bus import AgentMessageBus

    bus = AgentMessageBus("agent-architect", db)

    # Send a message to a specific agent
    bus.send("agent-reviewer", {"action": "review", "doc_id": "42"})

    # Broadcast to all agents
    bus.broadcast({"action": "maintenance", "type": "restart"})

    # Listen for messages
    for msg in bus.listen(timeout=5):
        print(f"From {msg.from_agent}: {msg.payload}")
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

from sccsos.core.db import Database

logger = logging.getLogger("sccsos.agent.message_bus")

# EventBus topic prefix for agent messages
_AGENT_MESSAGE_TOPIC = "agent.msg"
_BROADCAST_AGENT = "__broadcast__"


class MessageType(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    BROADCAST = "broadcast"


@dataclass
class AgentMessage:
    """A message exchanged between agents."""

    msg_id: str
    from_agent: str
    to_agent: str
    msg_type: MessageType
    payload: dict = field(default_factory=dict)
    timestamp: str = ""
    correlation_id: str = ""

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "msg_type": self.msg_type.value,
            "payload": self.payload,
            "timestamp": self.timestamp or datetime.now(timezone.utc).isoformat(),
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentMessage":
        return cls(
            msg_id=data.get("msg_id", ""),
            from_agent=data.get("from_agent", ""),
            to_agent=data.get("to_agent", ""),
            msg_type=MessageType(data.get("msg_type", "broadcast")),
            payload=data.get("payload", {}),
            timestamp=data.get("timestamp", ""),
            correlation_id=data.get("correlation_id", ""),
        )


class AgentMessageBus:
    """Inter-agent communication bus.

    Args:
        agent_name: Name of the local agent instance.
        db: Optional database for durable message storage.
    """

    def __init__(self, agent_name: str, db: Optional[Database] = None):
        self._agent_name = agent_name
        self._db = db
        self._handlers: dict[str, list[Callable]] = {}
        self._running = False

        # Event bus routing prefix
        self._topic = f"{_AGENT_MESSAGE_TOPIC}.{agent_name}"
        self._broadcast_topic = f"{_AGENT_MESSAGE_TOPIC}.{_BROADCAST_AGENT}"

    # ── Send API ──────────────────────────────────────────────────

    def send(self, to_agent: str, payload: dict,
             msg_type: MessageType = MessageType.REQUEST,
             correlation_id: str = "") -> str:
        """Send a message to a specific agent.

        Args:
            to_agent: Target agent name.
            payload: Message payload dict.
            msg_type: Message type (request/response/broadcast).
            correlation_id: Optional correlation ID for response pairing.

        Returns:
            The message ID.
        """
        msg = AgentMessage(
            msg_id=str(uuid.uuid4()),
            from_agent=self._agent_name,
            to_agent=to_agent,
            msg_type=msg_type,
            payload=payload,
            timestamp=datetime.now(timezone.utc).isoformat(),
            correlation_id=correlation_id or str(uuid.uuid4()),
        )
        self._publish(msg)
        return msg.msg_id

    def respond(self, to_agent: str, payload: dict,
                correlation_id: str) -> str:
        """Respond to a previous message.

        Args:
            to_agent: Original sender agent name.
            payload: Response payload.
            correlation_id: Correlation ID from the original message.

        Returns:
            The response message ID.
        """
        return self.send(
            to_agent, payload,
            msg_type=MessageType.RESPONSE,
            correlation_id=correlation_id,
        )

    def broadcast(self, payload: dict) -> None:
        """Broadcast a message to all connected agents.

        Args:
            payload: Message payload dict.
        """
        msg = AgentMessage(
            msg_id=str(uuid.uuid4()),
            from_agent=self._agent_name,
            to_agent=_BROADCAST_AGENT,
            msg_type=MessageType.BROADCAST,
            payload=payload,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._publish_broadcast(msg)

    # ── Receive API ───────────────────────────────────────────────

    def on_message(self, handler: Callable) -> None:
        """Register a handler for all incoming messages.

        Args:
            handler: Callable that accepts an ``AgentMessage``.
        """
        self._handlers.setdefault("*", []).append(handler)

    def on_type(self, msg_type: MessageType, handler: Callable) -> None:
        """Register a handler for a specific message type.

        Args:
            msg_type: MessageType to filter on.
            handler: Callable that accepts an ``AgentMessage``.
        """
        self._handlers.setdefault(msg_type.value, []).append(handler)

    def connect(self) -> None:
        """Register EventBus handlers for continuous message delivery.

        After calling ``connect()``, all incoming messages are
        automatically dispatched to registered handlers via the
        EventBus in-process callback mechanism (or Kafka consumer
        for distributed setups).

        Safe to call multiple times — only registers once.
        """
        if self._running:
            return
        self._running = True

        try:
            from sccsos.core.event_bus import get_bus
            bus = get_bus()
        except Exception:
            logger.warning("Event bus not available")
            return

        def _on_event(**data: Any) -> None:
            try:
                msg_data = data.get("message", data)
                msg = AgentMessage.from_dict(msg_data)
                if msg.to_agent in (self._agent_name, _BROADCAST_AGENT):
                    self._dispatch(msg)
            except Exception as e:
                logger.warning("Failed to process message: %s", e)

        bus.on(self._topic, _on_event)
        bus.on(self._broadcast_topic, _on_event)
        logger.debug("AgentMessageBus connected for '%s'", self._agent_name)

    def listen(self, timeout: float = 1.0) -> list[AgentMessage]:
        """Listen for incoming messages (blocking, with timeout).

        This polls the event bus for messages routed to this agent.
        In production, use ``start_consumer()`` for continuous delivery.

        Args:
            timeout: Max seconds to wait.

        Returns:
            List of received AgentMessage objects.
        """
        try:
            from sccsos.core.event_bus import get_bus
            bus = get_bus()
        except Exception:
            logger.warning("Event bus not available")
            return []

        received = []
        import threading
        event = threading.Event()

        def _on_event(**data: Any) -> None:
            try:
                msg_data = data.get("message", data)
                msg = AgentMessage.from_dict(msg_data)
                if msg.to_agent in (self._agent_name, _BROADCAST_AGENT):
                    received.append(msg)
                    self._dispatch(msg)
            except Exception as e:
                logger.warning("Failed to process message: %s", e)

        # Register handler on the event bus
        bus.on(self._topic, _on_event)
        bus.on(self._broadcast_topic, _on_event)

        event.wait(timeout=timeout)
        return received

    # ── Internal ──────────────────────────────────────────────────

    def _publish(self, msg: AgentMessage) -> None:
        """Publish a message to the target agent's topic."""
        try:
            from sccsos.core.event_bus import get_bus
            bus = get_bus()
            topic = f"{_AGENT_MESSAGE_TOPIC}.{msg.to_agent}"
            bus.emit(topic, message=msg.to_dict())
            self._persist(msg, direction="outgoing")
            logger.debug(
                "Sent message %s → %s (type=%s)",
                msg.from_agent, msg.to_agent, msg.msg_type.value,
            )
        except Exception as e:
            logger.warning("Failed to publish message: %s", e)

    def _publish_broadcast(self, msg: AgentMessage) -> None:
        """Publish a broadcast to all agents."""
        try:
            from sccsos.core.event_bus import get_bus
            bus = get_bus()
            bus.emit(self._broadcast_topic, message=msg.to_dict())
            self._persist(msg, direction="outgoing")
            logger.debug(
                "Broadcast from %s (type=%s)",
                msg.from_agent, msg.msg_type.value,
            )
        except Exception as e:
            logger.warning("Failed to broadcast message: %s", e)

    def _dispatch(self, msg: AgentMessage) -> None:
        """Dispatch a received message to registered handlers."""
        handlers = list(self._handlers.get("*", []))
        handlers.extend(self._handlers.get(msg.msg_type.value, []))
        for handler in handlers:
            try:
                handler(msg)
            except Exception:
                logger.exception(
                    "Handler failed for message %s", msg.msg_id,
                )

    def _persist(self, msg: AgentMessage, direction: str = "incoming") -> None:
        """Persist a message to the database (if configured)."""
        if self._db is None:
            return
        try:
            self._db.execute(
                "INSERT INTO agent_messages "
                "(msg_id, from_agent, to_agent, msg_type, payload_json, "
                "correlation_id, direction, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (msg.msg_id, msg.from_agent, msg.to_agent,
                 msg.msg_type.value,
                 json.dumps(msg.payload, ensure_ascii=False, default=str),
                 msg.correlation_id, direction, msg.timestamp),
            )
            self._db.commit()
        except Exception as e:
            logger.warning("Failed to persist message: %s", e)
