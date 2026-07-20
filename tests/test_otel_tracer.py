"""Tests for OpenTelemetry tracer bridge.

Tests the bridge's ability to gracefully degrade when OTel SDK is
not installed, and its integration with the core Tracer.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sccsos.core.db import Database
from sccsos.observability.tracer import Tracer


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    db = Database(path)
    db.initialize()
    yield db
    Path(path).unlink(missing_ok=True)


class TestOTelBridgeGracefulDegradation:
    """OTel bridge should be a no-op when OTel SDK is missing."""

    def test_otel_bridge_without_endpoint(self, db):
        """No OTLP endpoint → bridge is disabled."""
        from sccsos.observability.otel_tracer import OTelTracerBridge
        bridge = OTelTracerBridge()  # No endpoint
        assert not bridge.enabled

    def test_tracer_without_otel_works_normally(self, db):
        """Tracer without otel_bridge should work as before."""
        tracer = Tracer(db)
        span = tracer.start_span("test", agent="tester")
        assert span is not None
        assert span.name == "test"
        tracer.end_span(span.span_id)

        spans = tracer.get_trace(span.trace_id)
        assert len(spans) == 1

    def test_tracer_with_disabled_bridge(self, db):
        """Tracer with disabled OTel bridge should still trace to SQLite."""
        from sccsos.observability.otel_tracer import OTelTracerBridge
        bridge = OTelTracerBridge()  # disabled (no endpoint)
        tracer = Tracer(db, otel_bridge=bridge)

        span = tracer.start_span("workflow:test", agent="architect")
        assert span is not None
        tracer.end_span(span.span_id)

        traces = tracer.list_traces()
        assert len(traces) >= 1

    def test_span_with_parent(self, db):
        """Parent-child span relationship should work."""
        tracer = Tracer(db)
        parent = tracer.start_span("parent", agent="arch")
        child = tracer.start_span("child", agent="arch",
                                  parent_span_id=parent.span_id,
                                  trace_id=parent.trace_id)

        assert child.parent_span_id == parent.span_id
        assert child.trace_id == parent.trace_id

        tracer.end_span(child.span_id)
        tracer.end_span(parent.span_id)

    def test_span_events(self, db):
        """Adding events to a span should work."""
        tracer = Tracer(db)
        span = tracer.start_span("eventful")
        tracer.add_event(span.span_id, "tool.call",
                         {"tool": "read_file", "path": "/tmp/test"})
        tracer.end_span(span.span_id)

        trace = tracer.get_trace(span.trace_id)
        # Events are stored as JSON in the span's events column
        assert len(trace) == 1

    def test_multiple_traces(self, db):
        """Multiple independent traces should be isolated."""
        tracer = Tracer(db)
        s1 = tracer.start_span("trace1", trace_id="trc_aaa")
        s2 = tracer.start_span("trace2", trace_id="trc_bbb")
        tracer.end_span(s1.span_id)
        tracer.end_span(s2.span_id)

        t1 = tracer.get_trace("trc_aaa")
        t2 = tracer.get_trace("trc_bbb")
        assert len(t1) == 1
        assert len(t2) == 1

    def test_span_already_ended(self, db):
        """Ending an already-ended span should return None (defensive)."""
        tracer = Tracer(db)
        span = tracer.start_span("brief")
        assert tracer.end_span(span.span_id) is not None
        assert tracer.end_span(span.span_id) is None  # Already ended

    def test_bridge_shutdown_no_crash(self, db):
        """Shutting down an uninitialized bridge should not crash."""
        from sccsos.observability.otel_tracer import OTelTracerBridge
        bridge = OTelTracerBridge()
        bridge.shutdown()  # Should not raise
