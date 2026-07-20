"""Tests for AgentMessageBus — inter-agent communication."""

from __future__ import annotations

import os
import tempfile

import pytest

from sccsos.core.db import Database


@pytest.fixture
def db():
    tmp = tempfile.mktemp(suffix=".db")
    database = Database(db_path=tmp)
    database.initialize()
    yield database
    database.close()
    os.unlink(tmp)


class TestAgentMessageBus:
    """Tests for AgentMessageBus with LocalEventBus backend."""

    def test_send_and_receive(self, db):
        """Send a message and verify it's published on the event bus."""
        from sccsos.core.agent_message_bus import AgentMessageBus, AgentMessage

        bus_a = AgentMessageBus("agent-alpha", db)
        bus_b = AgentMessageBus("agent-beta", db)
        bus_b.connect()

        received = []
        bus_b.on_message(lambda msg: received.append(msg))

        # Send from alpha to beta
        msg_id = bus_a.send("agent-beta", {"action": "hello", "value": 42})

        assert len(received) >= 1
        msg = received[-1]
        assert msg.from_agent == "agent-alpha"
        assert msg.to_agent == "agent-beta"
        assert msg.payload["action"] == "hello"
        assert msg.msg_id == msg_id

    def test_broadcast(self, db):
        """Broadcast reaches all listeners."""
        from sccsos.core.agent_message_bus import AgentMessageBus

        bus_a = AgentMessageBus("agent-alpha", db)
        bus_b = AgentMessageBus("agent-beta", db)
        bus_c = AgentMessageBus("agent-gamma", db)
        bus_b.connect()
        bus_c.connect()

        received_b = []
        received_c = []
        bus_b.on_message(lambda msg: received_b.append(msg))
        bus_c.on_message(lambda msg: received_c.append(msg))

        bus_a.broadcast({"event": "system-update"})

        assert len(received_b) >= 1
        assert len(received_c) >= 1
        assert received_b[0].msg_type.value == "broadcast"
        assert received_c[0].msg_type.value == "broadcast"

    def test_request_response(self, db):
        """Request/response pattern works."""
        from sccsos.core.agent_message_bus import AgentMessageBus, MessageType

        bus_a = AgentMessageBus("agent-alpha", db)
        bus_b = AgentMessageBus("agent-beta", db)
        bus_a.connect()
        bus_b.connect()

        responses = []
        bus_a.on_type(MessageType.RESPONSE, lambda msg: responses.append(msg))

        # Alpha sends request
        corr_id = bus_a.send("agent-beta", {"query": "status"},
                             msg_type=MessageType.REQUEST)

        bus_b.listen(timeout=1)

        # Beta responds
        bus_b.respond("agent-alpha", {"status": "ok"}, correlation_id=corr_id)

        assert len(responses) >= 1
        assert responses[-1].correlation_id == corr_id
        assert responses[-1].payload["status"] == "ok"

    def test_persistence(self, db):
        """Messages are persisted to DB when db is provided."""
        from sccsos.core.agent_message_bus import AgentMessageBus

        bus_a = AgentMessageBus("agent-alpha", db)
        bus_b = AgentMessageBus("agent-beta", db)
        bus_b.connect()

        bus_a.send("agent-beta", {"test": "persistence"})

        # Check DB for the persisted message
        row = db.fetchone(
            "SELECT msg_id, from_agent, to_agent FROM agent_messages "
            "WHERE from_agent = ?",
            ("agent-alpha",),
        )
        assert row is not None
        assert row["from_agent"] == "agent-alpha"
        assert row["to_agent"] == "agent-beta"

    def test_agent_message_from_dict(self):
        """AgentMessage.from_dict reconstructs correctly."""
        from sccsos.core.agent_message_bus import AgentMessage, MessageType

        data = {
            "msg_id": "test-123",
            "from_agent": "src",
            "to_agent": "dst",
            "msg_type": "request",
            "payload": {"key": "value"},
            "timestamp": "2026-07-22T12:00:00Z",
            "correlation_id": "corr-456",
        }
        msg = AgentMessage.from_dict(data)
        assert msg.msg_id == "test-123"
        assert msg.msg_type == MessageType.REQUEST
        assert msg.payload["key"] == "value"
        assert msg.to_dict()["msg_type"] == "request"
