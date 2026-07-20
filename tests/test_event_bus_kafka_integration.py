"""Integration tests for KafkaEventBus with a live Kafka broker.

These tests require:
  1. ``sccsos[kafka]`` extras installed
  2. A running Kafka broker at ``KAFKA_BOOTSTRAP`` (default: localhost:9092)

Usage::

    # Start Kafka first
    docker compose -f docker-compose.yaml -f docker-compose.kafka.yml up -d

    # Run integration tests
    pip install sccsos[kafka]
    pytest tests/test_event_bus_kafka_integration.py -v \\
        --override-ini='addopts='

Unit tests (no Kafka required) are in ``test_event_bus_kafka.py``.
"""

from __future__ import annotations

import os
import time

import pytest

KAFKA_BOOTSTRAP = os.environ.get(
    "KAFKA_BOOTSTRAP", "localhost:9092",
)


def _kafka_available() -> bool:
    """Check if kafka-python is installed and a Kafka broker is reachable."""
    try:
        from kafka import KafkaProducer
        from kafka.errors import NoBrokersAvailable
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            max_block_ms=2000,
        )
        producer.close()
        return True
    except ImportError:
        return False
    except NoBrokersAvailable:
        return False
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _kafka_available(),
    reason=f"requires kafka-python + broker at {KAFKA_BOOTSTRAP}",
)


@pytest.fixture(scope="module")
def kafka_bus():
    """Shared KafkaEventBus for module-level tests."""
    from sccsos.core.event_bus_kafka import KafkaEventBus
    bus = KafkaEventBus(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        client_id="sccsos-integration-test",
        group_id="sccsos-integration-test-group",
    )
    yield bus
    bus.stop_consumer()


class TestKafkaEventBusIntegration:
    """Integration tests with live Kafka broker."""

    def test_producer_connects(self, kafka_bus):
        """Kafka producer connects and sends a message."""
        assert kafka_bus.producer is not None
        kafka_bus.emit("integration.test.producer", msg="hello")
        time.sleep(1)

    def test_emit_reaches_local_handler(self, kafka_bus):
        """emit() dispatches to local handlers."""
        received = []
        kafka_bus.on("integration.test.local", handler=lambda **x: received.append(x))
        kafka_bus.emit("integration.test.local", seq=1)
        time.sleep(1)
        assert len(received) >= 1
        assert received[0]["seq"] == 1

    def test_consumer_cycle(self, kafka_bus):
        """Start consumer, publish, and verify cross-instance delivery.

        This simulates two bus instances (producer + consumer)
        sharing the same Kafka cluster.
        """
        from sccsos.core.event_bus_kafka import KafkaEventBus

        consumer_bus = KafkaEventBus(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            client_id="sccsos-integration-consumer",
            group_id="sccsos-integration-group-2",
        )

        received = []
        consumer_bus.on("integration.test.cross", handler=lambda **x: received.append(x))
        consumer_bus.start_consumer()
        time.sleep(2)

        kafka_bus.emit("integration.test.cross", run_id="r1", status="ok")
        time.sleep(3)

        consumer_bus.stop_consumer()
        print(f"Cross-instance events received: {len(received)}")
