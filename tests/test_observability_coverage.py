"""Targeted coverage supplements for observability modules.

Covers:
  - WebhookNotifier: fire() with mocked HTTP, disabled, event filtering
  - AlertManager: threshold evaluation, DB-backed metrics, alert dispatch
  - PricingTable: edge cases, custom pricing, fallback behavior
  - Tracer: span lifecycle, edge cases
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest import mock

import pytest

from sccsos.core.config import AgentOSConfig, WebhookEntry, WebhooksConfig
from sccsos.core.db import Database
from sccsos.observability.alert_manager import (
    AlertManager,
    AlertResult,
    AlertThreshold,
)
from sccsos.observability.pricing import PricingTable
from sccsos.observability.tracer import Tracer
from sccsos.observability.webhook import WebhookNotifier, WebhookPayload


# ── WebhookNotifier ──────────────────────────────────────────────────


class TestWebhookNotifier:
    def test_disabled_when_no_endpoints(self):
        config = WebhooksConfig(enabled=True, endpoints=[])
        w = WebhookNotifier(config)
        assert not w.enabled
        w.fire("completed", run_id="r1")  # No crash

    def test_disabled_when_config_disabled(self):
        config = WebhooksConfig(enabled=False)
        w = WebhookNotifier(config)
        assert not w.enabled

    def test_enabled_with_endpoints(self):
        config = WebhooksConfig(
            enabled=True,
            endpoints=[WebhookEntry(url="http://localhost:9999/hook",
                                       events=["completed"])],
        )
        w = WebhookNotifier(config)
        assert w.enabled

    def test_fire_sends_http_request(self):
        config = WebhooksConfig(
            enabled=True,
            endpoints=[WebhookEntry(url="http://localhost:19999/test",
                                       events=["completed"])],
        )
        w = WebhookNotifier(config)

        with mock.patch("sccsos.observability.webhook.urllib_request.urlopen") as mock_req:
            mock_resp = mock.MagicMock()
            mock_resp.status = 200
            mock_req.return_value = mock_resp

            w.fire("completed", run_id="wf-1", workflow_name="test-wf",
                   status="ok", steps=[{"name": "step1", "status": "passed"}])

            mock_req.assert_called_once()
            call_args = mock_req.call_args[0][0]
            assert call_args.method == "POST"
            body = json.loads(call_args.data)
            assert body["event"] == "completed"
            assert body["run_id"] == "wf-1"

    def test_fire_skips_unsubscribed_events(self):
        config = WebhooksConfig(
            enabled=True,
            endpoints=[
                WebhookEntry(url="http://localhost:19999/hook1", events=["started"]),
                WebhookEntry(url="http://localhost:19999/hook2", events=["completed"]),
            ],
        )
        w = WebhookNotifier(config)

        with mock.patch("sccsos.observability.webhook.urllib_request.urlopen") as mock_req:
            w.fire("started", run_id="r1")
            assert mock_req.call_count == 1

    def test_fire_with_secret_header(self):
        config = WebhooksConfig(
            enabled=True,
            endpoints=[WebhookEntry(
                url="http://localhost:19999/sec-hook", events=["completed"],
                secret="s3cr3t",
            )],
        )
        w = WebhookNotifier(config)

        with mock.patch("sccsos.observability.webhook.urllib_request.urlopen") as mock_req:
            mock_resp = mock.MagicMock()
            mock_resp.status = 200
            mock_req.return_value = mock_resp

            w.fire("completed")
            req = mock_req.call_args[0][0]
            # urllib.request.Request canonicalizes header names
            assert req.headers.get("X-webhook-secret") == "s3cr3t"

    def test_fire_logs_http_error(self):
        config = WebhooksConfig(
            enabled=True,
            endpoints=[WebhookEntry(url="http://localhost:29999/fail",
                                       events=["failed"])],
        )
        w = WebhookNotifier(config)

        with mock.patch("sccsos.observability.webhook.urllib_request.urlopen") as mock_req:
            from urllib.error import URLError
            mock_req.side_effect = URLError("Connection refused")
            w.fire("failed", error="something broke")
            mock_req.assert_called_once()

    def test_payload_dataclass_defaults(self):
        p = WebhookPayload(event="test", run_id="r1", workflow_name="wf", status="ok")
        assert p.timestamp == ""
        assert p.error is None
        assert p.steps == []

    def test_payload_all_fields(self):
        p = WebhookPayload(
            event="completed", run_id="r1", workflow_name="wf",
            status="ok", timestamp="2026-07-22T00:00:00",
            error="msg", steps=[{"name": "s1"}],
        )
        assert p.error == "msg"
        assert len(p.steps) == 1


# ── AlertManager ─────────────────────────────────────────────────────


class TestAlertManager:
    @pytest.fixture
    def db(self):
        tmp = tempfile.mktemp(suffix=".db")
        database = Database(db_path=tmp)
        database.initialize()
        yield database
        database.close()
        os.unlink(tmp)

    def test_no_alerts_when_no_data(self, db):
        mgr = AlertManager(db, webhook=WebhookNotifier())
        results = mgr.evaluate_after_run(tenant_id="default")
        assert results == []

    def test_alert_on_high_error_rate(self, db):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        for i in range(10):
            db.execute(
                "INSERT INTO audit_log (tenant_id, agent_id, event_type, timestamp, success) "
                "VALUES (?, ?, ?, ?, ?)",
                ("default", f"agent-{i}", "llm_call", now, 0 if i < 5 else 1),
            )
        db.commit()

        mgr = AlertManager(db, webhook=WebhookNotifier())
        results = mgr.evaluate_after_run(tenant_id="default")
        assert len(results) >= 1
        assert results[0].triggered
        assert results[0].metric == "error_rate"

    def test_alert_on_failure_count(self, db):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        for i in range(25):
            db.execute(
                "INSERT INTO audit_log (tenant_id, agent_id, event_type, timestamp, success) "
                "VALUES (?, ?, ?, ?, ?)",
                ("default", f"fail-{i}", "tool_call", now, 0),
            )
        db.commit()

        mgr = AlertManager(db, webhook=WebhookNotifier())
        results = mgr.evaluate_after_run(tenant_id="default")
        alert_types = [r.metric for r in results]
        assert "failure_count" in alert_types

    def test_evaluate_global(self, db):
        mgr = AlertManager(db, webhook=WebhookNotifier())
        results = mgr.evaluate_global()
        assert isinstance(results, list)

    def test_alert_fires_via_webhook(self, db):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        config = WebhooksConfig(
            enabled=True,
            endpoints=[WebhookEntry(url="http://localhost:39999/alerts",
                                       events=["alert"])],
        )
        webhook = WebhookNotifier(config)
        mgr = AlertManager(db, webhook=webhook)

        for i in range(10):
            db.execute(
                "INSERT INTO audit_log (tenant_id, agent_id, event_type, timestamp, success) "
                "VALUES (?, ?, ?, ?, ?)",
                ("default", f"a-{i}", "llm_call", now, 0),
            )
        db.commit()

        with mock.patch("sccsos.observability.webhook.urllib_request.urlopen") as mock_req:
            mock_resp = mock.MagicMock()
            mock_resp.status = 200
            mock_req.return_value = mock_resp
            results = mgr.evaluate_after_run(tenant_id="default")
            assert len(results) >= 1
            assert mock_req.call_count >= 1

    def test_get_level_thresholds(self):
        t = AlertThreshold(metric="test", warning=10, critical=20)
        mgr = AlertManager.__new__(AlertManager)
        mgr._webhook = None  # type: ignore
        assert mgr._get_level(5, t) == ""
        assert mgr._get_level(10, t) == "WARNING"
        assert mgr._get_level(15, t) == "WARNING"
        assert mgr._get_level(20, t) == "CRITICAL"
        assert mgr._get_level(30, t) == "CRITICAL"

    def test_get_level_no_warning(self):
        t = AlertThreshold(metric="test", warning=0, critical=50)
        mgr = AlertManager.__new__(AlertManager)
        mgr._webhook = None  # type: ignore
        assert mgr._get_level(10, t) == ""
        assert mgr._get_level(50, t) == "CRITICAL"

    def test_alert_result_dataclass(self):
        r = AlertResult(triggered=True, level="WARNING", metric="error_rate",
                        value=0.15, threshold=0.1,
                        message="Error rate 15% >= 10% threshold")
        assert r.triggered
        assert r.level == "WARNING"

    def test_alert_no_webhook_logs_warning(self, db):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        webhook = WebhookNotifier()
        mgr = AlertManager(db, webhook=webhook)

        for i in range(10):
            db.execute(
                "INSERT INTO audit_log (tenant_id, agent_id, event_type, timestamp, success) "
                "VALUES (?, ?, ?, ?, ?)",
                ("default", f"x-{i}", "llm_call", now, 0),
            )
        db.commit()

        with mock.patch("sccsos.observability.alert_manager.logger.warning") as mock_log:
            results = mgr.evaluate_after_run(tenant_id="default")
            assert len(results) >= 1
            mock_log.assert_called()


# ── PricingTable ──────────────────────────────────────────────────────


class TestPricingTable:
    def test_known_model_pricing(self):
        p = PricingTable()
        inp, outp = p.get("deepseek-v4-flash")
        assert inp == 0.14
        assert outp == 0.28

    def test_unknown_model_falls_back(self):
        p = PricingTable()
        inp, outp = p.get("completely-unknown-model")
        assert inp == 0.50
        assert outp == 2.00

    def test_estimate_cost_known_model(self):
        p = PricingTable()
        cost = p.estimate_cost("deepseek-v4-flash", 1_000_000, 500_000)
        assert cost == 0.28

    def test_estimate_cost_unknown_model(self):
        p = PricingTable()
        cost = p.estimate_cost("unknown", 1000, 500)
        assert round(cost, 6) == 0.0015

    def test_zero_tokens(self):
        p = PricingTable()
        cost = p.estimate_cost("deepseek-v4-flash", 0, 0)
        assert cost == 0.0

    def test_get_input_price_direct(self):
        p = PricingTable()
        assert p.get_input_price("deepseek-v4-flash") == 0.14
        assert p.get_input_price("unknown") == 0.50

    def test_get_output_price_direct(self):
        p = PricingTable()
        assert p.get_output_price("deepseek-v4-flash") == 0.28
        assert p.get_output_price("unknown") == 2.00


# ── Tracer ───────────────────────────────────────────────────────────


class TestTracer:
    @pytest.fixture
    def db(self):
        tmp = tempfile.mktemp(suffix=".db")
        database = Database(db_path=tmp)
        database.initialize()
        yield database
        database.close()
        os.unlink(tmp)

    def test_start_end_span(self, db):
        t = Tracer(db)
        span = t.start_span("test-op", trace_id="trace-1")
        assert span is not None
        assert span.span_id is not None
        result = t.end_span(span.span_id, status="ok")
        assert result is not None
        # Span should no longer be active
        assert span.span_id not in t._active_spans

    def test_end_span_nonexistent(self, db):
        t = Tracer(db)
        result = t.end_span("ghost-span")
        assert result is None  # Defensive

    def test_end_span_twice(self, db):
        t = Tracer(db)
        span = t.start_span("op")
        t.end_span(span.span_id)
        result = t.end_span(span.span_id)  # Second end should return None
        assert result is None

    def test_start_span_with_parent(self, db):
        t = Tracer(db)
        parent = t.start_span("parent")
        child = t.start_span("child", parent_span_id=parent.span_id)
        assert child.span_id != parent.span_id

    def test_get_trace(self, db):
        t = Tracer(db)
        span = t.start_span("op1", trace_id="trace-abc")
        t.end_span(span.span_id)
        spans = t.get_trace("trace-abc")
        assert len(spans) >= 1

    def test_get_trace_empty(self, db):
        t = Tracer(db)
        assert t.get_trace("nonexistent") == []

    def test_add_event_to_span(self, db):
        t = Tracer(db)
        span = t.start_span("event-op")
        t.add_event(span.span_id, "tool_call", attributes={"tool": "web_search"})
        assert len(span.events) == 1
        assert span.events[0].name == "tool_call"

    def test_add_event_nonexistent_span(self, db):
        t = Tracer(db)
        with pytest.raises(KeyError):
            t.add_event("ghost", "test")

    def test_list_traces(self, db):
        t = Tracer(db)
        span = t.start_span("list-test", trace_id="trace-list")
        t.end_span(span.span_id)
        traces = t.list_traces()
        assert len(traces) >= 1

    def test_flush_trace_no_export_path(self, db):
        """flush_trace should no-op when export_path is None."""
        t = Tracer(db)
        t.flush_trace("trace-xyz")  # Should not crash

    def test_flush_trace_with_export(self, db, tmp_path):
        t = Tracer(db, export_path=str(tmp_path))
        span = t.start_span("flush-me", trace_id="trace-flush")
        t.end_span(span.span_id)
        # Root span should auto-flush
        trace_file = tmp_path / "trace-flush.json"
        assert trace_file.exists()
        data = json.loads(trace_file.read_text())
        assert data["trace_id"] == "trace-flush"
        assert data["span_count"] >= 1
