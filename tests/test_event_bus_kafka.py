"""Tests for KafkaEventBus — distributed event bus backend.

Uses mocking to avoid requiring a real Kafka cluster.
Integration tests are gated on ``sccsos[kafka]`` being installed
and a running Kafka broker.
"""

from __future__ import annotations

import sys
from unittest import mock

import pytest


@pytest.fixture
def mock_kafka():
    """Mock the kafka-python module with all submodules."""
    mock_module = mock.MagicMock()

    # Mock errors submodule
    mock_errors = mock.MagicMock()
    mock_errors.NoBrokersAvailable = Exception("No broker available")
    mock_module.errors = mock_errors

    # Mock KafkaProducer
    mock_producer = mock.MagicMock()
    mock_producer.send.return_value = mock.MagicMock()
    mock_producer.send.return_value.get.return_value = None
    mock_module.KafkaProducer.return_value = mock_producer

    # Mock KafkaConsumer
    mock_consumer = mock.MagicMock()
    mock_consumer.topics.return_value = {"sccsos.wf.started", "sccsos.wf.done"}
    mock_consumer.poll.return_value = {}
    mock_module.KafkaConsumer.return_value = mock_consumer

    with mock.patch.dict(
        sys.modules,
        {
            "kafka": mock_module,
            "kafka.errors": mock_errors,
            "kafka.producer": mock.MagicMock(),
            "kafka.consumer": mock.MagicMock(),
        },
    ):
        yield mock_module, mock_producer, mock_consumer


class TestKafkaEventBusUnit:
    """Unit tests with mocked kafka-python."""

    def test_init_defaults(self, mock_kafka):
        """Default init sets sensible defaults."""
        from sccsos.core.event_bus_kafka import KafkaEventBus

        bus = KafkaEventBus()
        assert bus._bootstrap == "localhost:9092"
        assert bus._client_id == "sccsos"
        assert bus._prefix == "sccsos."
        assert bus._producer is None

    def test_init_custom(self, mock_kafka):
        """Custom parameters are accepted."""
        from sccsos.core.event_bus_kafka import KafkaEventBus

        bus = KafkaEventBus(
            bootstrap_servers="kafka:9092",
            client_id="myapp",
            group_id="mygroup",
            topic_prefix="myapp.",
        )
        assert bus._bootstrap == "kafka:9092"
        assert bus._topic("test") == "myapp.test"

    def test_on_registers_handler(self, mock_kafka):
        """on() registers a handler locally."""
        from sccsos.core.event_bus_kafka import KafkaEventBus

        bus = KafkaEventBus()

        def handler(**data):
            pass

        bus.on("workflow.completed", handler)
        assert len(bus._local_handlers["workflow.completed"]) == 1

    def test_off_removes_handler(self, mock_kafka):
        """off() removes a handler."""
        from sccsos.core.event_bus_kafka import KafkaEventBus

        bus = KafkaEventBus()

        def handler(**data):
            pass

        bus.on("workflow.completed", handler)
        bus.off("workflow.completed", handler)
        assert "workflow.completed" not in bus._local_handlers or \
               len(bus._local_handlers["workflow.completed"]) == 0

    def test_emit_calls_local_handlers(self, mock_kafka):
        """emit() dispatches to local handlers."""
        from sccsos.core.event_bus_kafka import KafkaEventBus

        bus = KafkaEventBus()
        calls = []

        def handler(**data):
            calls.append(data)

        bus.on("test.event", handler)
        bus.emit("test.event", key="val")

        assert len(calls) == 1
        assert calls[0]["key"] == "val"

    def test_emit_publishes_to_kafka(self, mock_kafka):
        """emit() also publishes to Kafka topic."""
        mock_module, mock_producer, _ = mock_kafka
        from sccsos.core.event_bus_kafka import KafkaEventBus

        bus = KafkaEventBus()
        bus.emit("workflow.completed", run_id="abc")

        # Producer was created
        assert mock_module.KafkaProducer.called
        # Topic is prefixed
        topic_arg = mock_producer.send.call_args[0][0]
        assert topic_arg == "sccsos.workflow.completed"

    def test_emit_producer_unavailable(self, mock_kafka):
        """emit() works gracefully when Kafka is unavailable."""
        mock_module, mock_producer, _ = mock_kafka
        mock_module.KafkaProducer.side_effect = Exception("No broker")

        from sccsos.core.event_bus_kafka import KafkaEventBus

        bus = KafkaEventBus()
        calls = []

        def handler(**data):
            calls.append(data)

        bus.on("local.event", handler)
        bus.emit("local.event", msg="works")

        # Local handlers still fire
        assert len(calls) == 1

    def test_has_handlers(self, mock_kafka):
        """has_handlers checks local handlers."""
        from sccsos.core.event_bus_kafka import KafkaEventBus

        bus = KafkaEventBus()
        assert not bus.has_handlers("test")

        bus.on("test", lambda **x: None)
        assert bus.has_handlers("test")

    def test_clear(self, mock_kafka):
        """clear removes all handlers."""
        from sccsos.core.event_bus_kafka import KafkaEventBus

        bus = KafkaEventBus()
        bus.on("test", lambda **x: None)
        bus.clear()
        assert not bus.has_handlers("test")

    def test_topic_mapping(self, mock_kafka):
        """_topic() maps event names to Kafka topics."""
        from sccsos.core.event_bus_kafka import KafkaEventBus

        bus = KafkaEventBus(topic_prefix="sccsos.")
        assert bus._topic("workflow.started") == "sccsos.workflow.started"
        assert bus._topic("step.completed") == "sccsos.step.completed"

    def test_consumer_start_stop(self, mock_kafka):
        """Consumer can be started and stopped."""
        from sccsos.core.event_bus_kafka import KafkaEventBus

        bus = KafkaEventBus(bootstrap_servers="localhost:9092")
        bus.start_consumer()
        assert bus._running
        assert bus._consumer_thread is not None

        bus.stop_consumer()
        assert not bus._running

    def test_dispatch_kafka_message(self, mock_kafka):
        """Consumed Kafka messages are dispatched to local handlers."""
        from sccsos.core.event_bus_kafka import KafkaEventBus

        bus = KafkaEventBus()
        calls = []

        def handler(**data):
            calls.append(data)

        bus.on("wf.done", handler)

        # Simulate a consumed message
        class FakeMsg:
            topic = "sccsos.wf.done"
            value = {"status": "ok", "run_id": "r1"}

        bus._dispatch_kafka_message(FakeMsg())
        assert len(calls) == 1
        assert calls[0]["status"] == "ok"


class TestCreateEventBus:
    """Test the create_event_bus factory."""

    def test_local_backend(self):
        """'local' backend creates LocalEventBus."""
        from sccsos.core.event_bus_kafka import create_event_bus

        bus = create_event_bus("local")
        from sccsos.core.event_bus import LocalEventBus
        assert isinstance(bus, LocalEventBus)

    def test_kafka_backend(self, mock_kafka):
        """'kafka' backend creates KafkaEventBus."""
        from sccsos.core.event_bus_kafka import create_event_bus

        bus = create_event_bus("kafka", bootstrap_servers="localhost:9092")
        from sccsos.core.event_bus_kafka import KafkaEventBus
        assert isinstance(bus, KafkaEventBus)
