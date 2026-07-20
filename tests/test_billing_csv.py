"""Tests for the BillingExporter — CSV export and report generation."""

from __future__ import annotations

import csv
import io
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture
def db_with_audit_log():
    """Create a temporary runtime with populated audit_log records."""
    from sccsos.core.agent_runtime import AgentRuntime, reset_runtime, set_runtime

    reset_runtime()
    tmp_dir = Path(tempfile.mkdtemp(prefix="sccsos_billing_test_"))
    db_path = str(tmp_dir / "test_billing.db")

    from sccsos.core.config import AgentOSConfig, DatabaseConfig
    cfg = AgentOSConfig(database=DatabaseConfig(path=db_path))

    rt = AgentRuntime(config=cfg)
    rt.initialize()
    set_runtime(rt)

    db = rt.db
    now = datetime.now(timezone.utc).isoformat()

    records = [
        ("tenant-1", now, "agent-a", "llm_call", "read_file", "gpt-4", 500, 0.01, 1000, 1),
        ("tenant-1", now, "agent-b", "tool_call", "terminal", "gpt-4", 200, 0.004, 500, 1),
        ("tenant-2", now, "agent-c", "llm_call", "web_search", "claude-3", 800, 0.02, 2000, 1),
        ("tenant-1", now, "agent-a", "llm_call", "read_file", "gpt-4", 300, 0.006, 800, 1),
        ("tenant-2", now, "agent-c", "tool_call", "terminal", "claude-3", 100, 0.002, 300, 0),
    ]
    for t_id, ts, a_id, e_type, tool, model, tokens, cost, dur, success in records:
        db.execute(
            "INSERT INTO audit_log (tenant_id, timestamp, agent_id, event_type, "
            "tool_name, model_name, tokens_used, cost_usd, duration_ms, success) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (t_id, ts, a_id, e_type, tool, model, tokens, cost, dur, success),
        )
    db.commit()

    yield rt, db

    rt.close()


class TestBillingExporter:
    """Integration tests for BillingExporter."""

    def test_query_records_all(self, db_with_audit_log):
        """query_records returns all records in date range."""
        rt, db = db_with_audit_log
        from sccsos.observability.billing import BillingExporter
        exporter = BillingExporter(db)
        records = exporter.query_records("2026-07-01", "2026-07-31")
        assert len(records) == 5

    def test_query_records_tenant_filter(self, db_with_audit_log):
        """query_records filters by tenant_id."""
        rt, db = db_with_audit_log
        from sccsos.observability.billing import BillingExporter
        exporter = BillingExporter(db)
        records = exporter.query_records("2026-07-01", "2026-07-31", tenant_id="tenant-1")
        assert len(records) == 3
        assert all(r.tenant_id == "tenant-1" for r in records)

    def test_query_records_agent_filter(self, db_with_audit_log):
        """query_records filters by agent_id."""
        rt, db = db_with_audit_log
        from sccsos.observability.billing import BillingExporter
        exporter = BillingExporter(db)
        records = exporter.query_records("2026-07-01", "2026-07-31", agent_id="agent-c")
        assert len(records) == 2

    def test_summary_totals(self, db_with_audit_log):
        """summary returns correct aggregated totals."""
        rt, db = db_with_audit_log
        from sccsos.observability.billing import BillingExporter
        exporter = BillingExporter(db)
        s = exporter.summary("2026-07-01", "2026-07-31")
        assert s.total_tokens == 1900  # 500 + 200 + 800 + 300 + 100
        assert abs(s.total_cost - 0.042) < 0.0001  # 0.01 + 0.004 + 0.02 + 0.006 + 0.002
        assert s.total_calls == 5
        assert s.total_duration_ms == 4600

    def test_summary_by_agent(self, db_with_audit_log):
        """summary breaks down cost by agent."""
        rt, db = db_with_audit_log
        from sccsos.observability.billing import BillingExporter
        exporter = BillingExporter(db)
        s = exporter.summary("2026-07-01", "2026-07-31", tenant_id="tenant-1")
        assert len(s.by_agent) == 2
        assert abs(s.by_agent.get("agent-a", 0) - 0.016) < 0.0001

    def test_summary_by_model(self, db_with_audit_log):
        """summary breaks down cost by model."""
        rt, db = db_with_audit_log
        from sccsos.observability.billing import BillingExporter
        exporter = BillingExporter(db)
        s = exporter.summary("2026-07-01", "2026-07-31")
        assert len(s.by_model) == 2  # gpt-4, claude-3

    def test_summary_by_tool(self, db_with_audit_log):
        """summary breaks down calls by tool."""
        rt, db = db_with_audit_log
        from sccsos.observability.billing import BillingExporter
        exporter = BillingExporter(db)
        s = exporter.summary("2026-07-01", "2026-07-31")
        assert s.by_tool.get("read_file", 0) == 2
        assert s.by_tool.get("terminal", 0) == 2

    def test_export_csv_content(self, db_with_audit_log):
        """export_csv writes valid CSV with correct headers."""
        rt, db = db_with_audit_log
        from sccsos.observability.billing import BillingExporter
        exporter = BillingExporter(db)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            output_path = f.name

        try:
            path = exporter.export_csv("2026-07-01", "2026-07-31",
                                       output_path=output_path)
            assert path == output_path

            with open(path, newline="") as csvfile:
                reader = csv.reader(csvfile)
                rows = list(reader)

            assert len(rows) == 6  # header + 5 records
            assert rows[0] == [
                "timestamp", "tenant_id", "agent_id", "event_type",
                "tool_name", "model_name", "tokens_used", "cost_usd",
                "duration_ms", "success",
            ]
            # Check that all tenant_ids appear (order is timestamp DESC)
            tenant_ids = {r[1] for r in rows[1:]}
            assert "tenant-1" in tenant_ids
            assert "tenant-2" in tenant_ids
        finally:
            os.unlink(output_path)

    def test_export_csv_auto_path(self, db_with_audit_log):
        """export_csv generates a default path when output_path is None."""
        rt, db = db_with_audit_log
        from sccsos.observability.billing import BillingExporter
        exporter = BillingExporter(db)

        path = exporter.export_csv("2026-07-01", "2026-07-31")
        assert path.endswith(".csv")
        assert "billing_" in path
        assert os.path.exists(path)
        os.unlink(path)

    def test_export_summary_csv(self, db_with_audit_log):
        """export_summary_csv writes valid summary CSV."""
        rt, db = db_with_audit_log
        from sccsos.observability.billing import BillingExporter
        exporter = BillingExporter(db)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            output_path = f.name

        try:
            path = exporter.export_summary_csv("2026-07-01", "2026-07-31",
                                               output_path=output_path)
            assert path == output_path

            with open(path, newline="") as csvfile:
                reader = csv.reader(csvfile)
                rows = list(reader)

            assert len(rows) >= 2  # header + at least 1 day summary
            assert rows[0] == ["date", "tenant_id", "calls", "tokens", "cost_usd"]
        finally:
            os.unlink(output_path)

    def test_export_csv_empty_range(self, db_with_audit_log):
        """export_csv handles empty date ranges gracefully."""
        rt, db = db_with_audit_log
        from sccsos.observability.billing import BillingExporter
        exporter = BillingExporter(db)

        path = exporter.export_csv("2025-01-01", "2025-01-31")
        with open(path, newline="") as csvfile:
            reader = csv.reader(csvfile)
            rows = list(reader)
        assert len(rows) == 1  # header only
        os.unlink(path)

    def test_summary_empty_tenant(self, db_with_audit_log):
        """summary with non-existent tenant returns empty aggregates."""
        rt, db = db_with_audit_log
        from sccsos.observability.billing import BillingExporter
        exporter = BillingExporter(db)
        s = exporter.summary("2026-07-01", "2026-07-31", tenant_id="nonexistent")
        assert s.total_calls == 0
        assert s.total_cost == 0.0
        assert len(s.by_agent) == 0
