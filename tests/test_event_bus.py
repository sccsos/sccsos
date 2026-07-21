"""Tests for EventBus and Config auto-merge."""
from __future__ import annotations

import pytest

from sccsos.core.event_bus import get_bus, LocalEventBus, WORKFLOW_STARTED, WORKFLOW_COMPLETED, WORKFLOW_FAILED
from sccsos.core.config import AgentOSConfig


# ═══════════════════════════════════════════════════════════════════
# EventBus tests
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def bus():
    """Fresh EventBus for each test (no state leakage)."""
    LocalEventBus.reset_instance()
    b = get_bus()
    yield b
    LocalEventBus.reset_instance()


class TestEventBusCore:
    """Core pub/sub semantics."""

    def test_register_handler(self, bus):
        events = []
        bus.on("test.event", lambda **kw: events.append(kw))
        bus.emit("test.event", msg="hello")
        assert len(events) == 1
        assert events[0]["msg"] == "hello"

    def test_multiple_handlers(self, bus):
        results = []

        def h1(**kw):
            results.append("h1")

        def h2(**kw):
            results.append("h2")

        bus.on("test.event", h1)
        bus.on("test.event", h2)
        bus.emit("test.event")
        assert results == ["h1", "h2"]

    def test_unregister_handler(self, bus):
        results = []

        def handler(**kw):
            results.append("called")

        bus.on("test.event", handler)
        bus.emit("test.event")
        assert len(results) == 1

        bus.off("test.event", handler)
        bus.emit("test.event")
        assert len(results) == 1  # No change — handler was removed

    def test_no_handlers_emits_safely(self, bus):
        """Emit with no registered handlers should not raise."""
        bus.emit("nonexistent.event", data=42)

    def test_handler_failure_does_not_block_others(self, bus):
        results = []

        def failing(**kw):
            raise RuntimeError("oops")

        def good(**kw):
            results.append("ok")

        bus.on("test.event", failing)
        bus.on("test.event", good)
        # Should not raise
        bus.emit("test.event")
        assert results == ["ok"]

    def test_has_handlers(self, bus):
        assert not bus.has_handlers("test.event")
        bus.on("test.event", lambda **kw: None)
        assert bus.has_handlers("test.event")

    def test_clear_handlers(self, bus):
        bus.on("a", lambda **kw: None)
        bus.on("b", lambda **kw: None)
        bus.clear()
        assert not bus.has_handlers("a")
        assert not bus.has_handlers("b")

    def test_singleton(self):
        """get_bus() should return the same instance."""
        LocalEventBus.reset_instance()
        a = get_bus()
        b = get_bus()
        assert a is b


class TestEventBusWorkflowEvents:
    """Workflow lifecycle event payload semantics."""

    def test_workflow_started(self, bus):
        results = []
        bus.on(WORKFLOW_STARTED, lambda **kw: results.append(kw))

        bus.emit(WORKFLOW_STARTED, run_id="wf_abc", workflow_name="test", status="running")
        assert len(results) == 1
        assert results[0]["run_id"] == "wf_abc"
        assert results[0]["workflow_name"] == "test"
        assert results[0]["status"] == "running"

    def test_workflow_completed(self, bus):
        results = []
        bus.on(WORKFLOW_COMPLETED, lambda **kw: results.append(kw))

        bus.emit(WORKFLOW_COMPLETED, run_id="wf_abc", workflow_name="test",
                 status="completed", steps=["s1", "s2"])
        assert results[0]["steps"] == ["s1", "s2"]

    def test_workflow_failed(self, bus):
        results = []
        bus.on(WORKFLOW_FAILED, lambda **kw: results.append(kw))

        bus.emit(WORKFLOW_FAILED, run_id="wf_abc", workflow_name="test",
                 status="failed", error="Something went wrong")
        assert "error" in results[0]
        assert results[0]["error"] == "Something went wrong"

    def test_workflow_events_are_independent(self, bus):
        """Subscribing to WORKFLOW_STARTED should not receive WORKFLOW_COMPLETED."""
        results = []
        bus.on(WORKFLOW_STARTED, lambda **kw: results.append("started"))

        bus.emit(WORKFLOW_COMPLETED, run_id="wf_x")
        assert len(results) == 0  # No started handler called

    def test_multiple_subscribers_same_event(self, bus):
        """WORKFLOW_COMPLETED can have both webhook and alert subscribers."""
        webhook_calls = []
        alert_calls = []

        bus.on(WORKFLOW_COMPLETED, lambda **kw: webhook_calls.append(kw.get("status")))
        bus.on(WORKFLOW_COMPLETED, lambda **kw: alert_calls.append(kw.get("run_id")))

        bus.emit(WORKFLOW_COMPLETED, run_id="wf_1", status="completed")
        assert webhook_calls == ["completed"]
        assert alert_calls == ["wf_1"]


# ═══════════════════════════════════════════════════════════════════
# Config auto-merge tests
# ═══════════════════════════════════════════════════════════════════


class TestConfigAutoMerge:
    """Verify _from_dict auto-merge covers all fields correctly."""

    def test_full_config(self):
        """Load a complete config YAML and verify all fields."""
        data = {
            "project": {"name": "myproject", "version": "2.0"},
            "database": {"path": "/tmp/mydb.sqlite"},
            "defaults": {"hermes_profile": "prod", "max_turns": 50, "timeout": 3600},
            "logging": {"level": "DEBUG", "format": "text", "directory": "/logs", "retention_days": 90},
            "tracing": {"enabled": False, "export_path": "/traces/"},
            "pricing": {"path": "./config/pricing.json"},
            "agents": {"path": "./agents", "wiki_path": "./docs", "personalities_path": "./personas"},
            "policies": {
                "default": {"max_cost_usd": 10.0},
                "restricted": {"max_cost_usd": 2.0},
            },
        }
        cfg = AgentOSConfig._from_dict(data)

        # Project
        assert cfg.project.name == "myproject"
        assert cfg.project.version == '2.0'

        # Database
        assert cfg.database.path == "/tmp/mydb.sqlite"

        # Defaults
        assert cfg.defaults.hermes_profile == "prod"
        assert cfg.defaults.max_turns == 50
        assert cfg.defaults.timeout == 3600

        # Logging
        assert cfg.logging.level == "DEBUG"
        assert cfg.logging.format == "text"
        assert cfg.logging.directory == "/logs"
        assert cfg.logging.retention_days == 90

        # Tracing
        assert cfg.tracing.enabled is False
        assert cfg.tracing.export_path == "/traces/"

        # Pricing
        assert cfg.pricing.path == "./config/pricing.json"

        # Agents
        assert cfg.agents.path == "./agents"
        assert cfg.agents.wiki_path == "./docs"
        assert cfg.agents.personalities_path == "./personas"

        # Policies (uses special-case from_dict)
        assert cfg.policies.default.max_cost_usd == 10.0
        assert cfg.policies.named["restricted"].max_cost_usd == 2.0

    def test_default_config(self):
        """Empty data should produce all defaults."""
        cfg = AgentOSConfig._from_dict({})
        assert cfg.project.name == "sccsos"
        assert cfg.project.version == '0.15.0'
        assert cfg.database.path == "./data/sccsos.db"
        assert cfg.defaults.hermes_profile == "sccsos"
        assert cfg.defaults.max_turns == 90
        assert cfg.logging.level == "INFO"
        assert cfg.pricing.path == "./config/pricing.json"

    def test_partial_overrides(self):
        """Partial data should override only specified fields, leave defaults."""
        data = {"project": {"name": "custom"}}
        cfg = AgentOSConfig._from_dict(data)
        assert cfg.project.name == "custom"
        # Unspecified fields keep defaults
        assert cfg.project.version == '0.15.0'
        assert cfg.database.path == "./data/sccsos.db"
        assert cfg.tracing.enabled is True
        assert cfg.pricing.path == "./config/pricing.json"

    def test_nested_none_overrides_default(self):
        """Setting a nested value to 'false' or 0 should work."""
        data = {"tracing": {"enabled": False}}
        cfg = AgentOSConfig._from_dict(data)
        assert cfg.tracing.enabled is False

    def test_legacy_pricing_path_fallback(self):
        """tracing.pricing_path is only used when pricing.path is empty."""
        data = {
            "pricing": {"path": ""},
            "tracing": {"pricing_path": "./config/old_pricing.json"},
        }
        cfg = AgentOSConfig._from_dict(data)
        assert cfg.pricing.path == "./config/old_pricing.json"

    def test_pricing_path_takes_precedence(self):
        """New pricing.path should take precedence over legacy tracing.pricing_path."""
        data = {
            "pricing": {"path": "./config/new_pricing.json"},
            "tracing": {"pricing_path": "./config/old_pricing.json"},
        }
        cfg = AgentOSConfig._from_dict(data)
        assert cfg.pricing.path == "./config/new_pricing.json"

    def test_webhooks_empty(self):
        """Empty webhooks config should not raise."""
        cfg = AgentOSConfig._from_dict({})
        assert cfg.webhooks.enabled is False
        assert cfg.webhooks.endpoints == []

    # ── EventBusConfig tests ────────────────────────────────────

    def test_event_bus_default(self):
        """Event bus defaults to local backend."""
        cfg = AgentOSConfig._from_dict({})
        assert cfg.event_bus.backend == "local"
        assert cfg.event_bus.bootstrap_servers == "localhost:9092"
        assert cfg.event_bus.client_id == "sccsos"
        assert cfg.event_bus.group_id == "sccsos-events"

    def test_event_bus_kafka_config(self):
        """Kafka backend config parses correctly."""
        data = {
            "event_bus": {
                "backend": "kafka",
                "bootstrap_servers": "kafka:9092",
                "client_id": "myapp",
                "group_id": "mygroup",
            }
        }
        cfg = AgentOSConfig._from_dict(data)
        assert cfg.event_bus.backend == "kafka"
        assert cfg.event_bus.bootstrap_servers == "kafka:9092"
        assert cfg.event_bus.client_id == "myapp"
        assert cfg.event_bus.group_id == "mygroup"


class TestConfigureEventBus:
    """Tests for configure_event_bus() and get_bus()."""

    def teardown_method(self):
        """Reset bus singleton after each test."""
        from sccsos.core.event_bus import configure_event_bus
        configure_event_bus("local")

    def test_configure_local(self):
        """configure_event_bus('local') creates LocalEventBus."""
        from sccsos.core.event_bus import configure_event_bus, get_bus, _local_bus
        configure_event_bus("local")
        bus = get_bus()
        from sccsos.core.event_bus import LocalEventBus
        assert isinstance(bus, LocalEventBus)

    def test_configure_kafka(self, monkeypatch):
        """configure_event_bus('kafka') creates KafkaEventBus."""
        # Mock kafka-python import so the test doesn't need the library
        import sys

        mock_errors = type(sys)("errors")
        mock_errors.NoBrokersAvailable = type("NoBrokersAvailable", (Exception,), {})

        mock_kafka = type(sys)("kafka")
        mock_kafka.KafkaProducer = type(sys)("KafkaProducer")
        mock_kafka.KafkaConsumer = type(sys)("KafkaConsumer")
        mock_kafka.errors = mock_errors
        monkeypatch.setitem(sys.modules, "kafka", mock_kafka)
        monkeypatch.setitem(sys.modules, "kafka.errors", mock_errors)
        monkeypatch.setitem(sys.modules, "kafka.producer", type(sys)("producer"))
        monkeypatch.setitem(sys.modules, "kafka.consumer", type(sys)("consumer"))

        from sccsos.core.event_bus import configure_event_bus, get_bus
        configure_event_bus("kafka", bootstrap_servers="localhost:9092")
        bus = get_bus()
        from sccsos.core.event_bus_kafka import KafkaEventBus
        assert isinstance(bus, KafkaEventBus)
        assert bus._bootstrap == "localhost:9092"
