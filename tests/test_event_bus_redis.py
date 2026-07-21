"""Tests for RedisPubSubBridge (multi-process EventBus bridge)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from sccsos.core.event_bus_redis import RedisPubSubBridge


class TestRedisPubSubBridge:
    """Unit tests for RedisPubSubBridge."""

    def test_init_defaults(self):
        """Default constructor uses sensible values."""
        bridge = RedisPubSubBridge()
        assert "worker-" in bridge._worker_id
        assert bridge._channel == "sccsos:events"
        assert bridge._redis_url == "redis://localhost:6379/0"
        assert bridge._redis_available is None

    def test_init_custom(self):
        """Custom parameters override defaults."""
        bridge = RedisPubSubBridge(
            redis_url="redis://redis-cluster:7000",
            channel="myapp:events",
            worker_id="worker-42",
        )
        assert bridge._redis_url == "redis://redis-cluster:7000"
        assert bridge._channel == "myapp:events"
        assert bridge._worker_id == "worker-42"

    def test_get_status_before_connect(self):
        """Status returns baseline values before any connection."""
        bridge = RedisPubSubBridge(worker_id="test-1")
        status = bridge.get_status()
        assert status["worker_id"] == "test-1"
        assert status["redis_available"] is None
        assert not status["subscriber_running"]
        assert status["channel"] == "sccsos:events"

    @patch("sccsos.core.event_bus_redis.RedisPubSubBridge._get_client")
    def test_wire_publish_registers_handlers(self, mock_get_client):
        """wire_publish registers EventBus handlers for known events."""
        mock_get_client.return_value = None
        local_bus = MagicMock()
        bridge = RedisPubSubBridge(worker_id="test-1")

        bridge.wire_publish(local_bus)

        # Should have registered handlers for all event types
        # Workflow events (4) + step events (4) + agent events (6)
        # + skill events (4) + workflow string events (3) + system (1)
        # = ~22 event types
        assert local_bus.on.call_count >= 20

    def test_wire_publish_redis_unavailable(self):
        """wire_publish does not crash when Redis is unavailable."""
        local_bus = MagicMock()
        bridge = RedisPubSubBridge(
            redis_url="redis://nonexistent:6379",
            worker_id="test-1",
        )
        # Should not raise
        bridge.wire_publish(local_bus)
        assert bridge._redis_available is False or bridge._redis_available is None

    def test_handle_redis_message_skips_own_events(self):
        """Events from the same worker are skipped (loop prevention)."""
        local_bus = MagicMock()
        bridge = RedisPubSubBridge(worker_id="worker-1")

        message = {
            "type": "message",
            "data": json.dumps({
                "event": "workflow.started",
                "data": {"run_id": "test-1"},
                "_source_worker": "worker-1",  # Same as bridge
            }),
        }
        bridge._handle_redis_message(message, local_bus)
        # Should NOT re-emit
        local_bus.emit.assert_not_called()

    def test_handle_redis_message_forwards_other_workers(self):
        """Events from other workers are re-emitted to local EventBus."""
        local_bus = MagicMock()
        bridge = RedisPubSubBridge(worker_id="worker-1")

        message = {
            "type": "message",
            "data": json.dumps({
                "event": "workflow.started",
                "data": {"run_id": "test-42"},
                "_source_worker": "worker-2",  # Different worker
            }),
        }
        bridge._handle_redis_message(message, local_bus)
        local_bus.emit.assert_called_once_with(
            "workflow.started", run_id="test-42",
        )

    def test_handle_redis_message_skips_invalid_json(self):
        """Invalid JSON payloads are silently ignored."""
        local_bus = MagicMock()
        bridge = RedisPubSubBridge(worker_id="worker-1")

        message = {"type": "message", "data": "{invalid json}"}
        bridge._handle_redis_message(message, local_bus)
        local_bus.emit.assert_not_called()

    def test_handle_redis_message_skips_missing_event(self):
        """Messages without an event field are silently ignored."""
        local_bus = MagicMock()
        bridge = RedisPubSubBridge(worker_id="worker-1")

        message = {
            "type": "message",
            "data": json.dumps({"data": {"x": 1}, "_source_worker": "worker-2"}),
        }
        bridge._handle_redis_message(message, local_bus)
        local_bus.emit.assert_not_called()

    def test_handle_redis_message_skips_non_message_type(self):
        """Non-message PubSub types (subscribe, psubscribe) are ignored."""
        local_bus = MagicMock()
        bridge = RedisPubSubBridge(worker_id="worker-1")

        message = {
            "type": "subscribe",
            "data": 1,  # Real Redis subscribe message carries an int (subscription count)
        }
        bridge._handle_redis_message(message, local_bus)
        local_bus.emit.assert_not_called()

    def test_handle_redis_message_without_source_worker(self):
        """Messages without _source_worker are forwarded (backward compat)."""
        local_bus = MagicMock()
        bridge = RedisPubSubBridge(worker_id="worker-1")

        message = {
            "type": "message",
            "data": json.dumps({
                "event": "workflow.completed",
                "data": {"run_id": "test-99"},
                # No _source_worker field — old format
            }),
        }
        bridge._handle_redis_message(message, local_bus)
        local_bus.emit.assert_called_once_with(
            "workflow.completed", run_id="test-99",
        )

    @patch("sccsos.core.event_bus_redis.RedisPubSubBridge._get_client")
    def test_is_connected_false_by_default(self, mock_get_client):
        """is_connected returns False before any connection."""
        bridge = RedisPubSubBridge(worker_id="test-1")
        assert not bridge.is_connected

    def test_stop_subscriber_graceful(self):
        """stop_subscriber cleans up without error."""
        bridge = RedisPubSubBridge(worker_id="test-1")
        # Should not raise even if never started
        bridge.stop_subscriber()
        assert not bridge._running

    @patch("sccsos.core.event_bus_redis.RedisPubSubBridge._get_client")
    def test_wire_publish_does_not_register_before_publish(self, mock_get_client):
        """wire_publish is lazy — it only registers EventBus handlers,
        not Redis connections."""
        mock_get_client.return_value = None
        local_bus = MagicMock()
        bridge = RedisPubSubBridge(worker_id="test-1")

        bridge.wire_publish(local_bus)

        # _get_client should NOT be called during wire_publish
        mock_get_client.assert_not_called()
