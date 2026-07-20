"""Tests for BillingExporter — CSV export and cost reporting."""

from __future__ import annotations

import csv
import os
import tempfile

import pytest

from sccsos.core.db import Database
from sccsos.observability.billing import BillingExporter, BillingSummary


@pytest.fixture
def db():
    """Temporary SQLite database."""
    tmp = tempfile.mktemp(suffix=".db")
    database = Database(db_path=tmp)
    database.initialize()
    yield database
    database.close()
    os.unlink(tmp)


@pytest.fixture
def seeded_db(db):
    """DB with audit_log entries for billing tests."""
    entries = [
        ("2026-07-15T10:00:00", "tenant-1", "agent-a", "llm_call",
         "chat", "gpt-4", 1000, 0.05, 500, 1),
        ("2026-07-15T11:00:00", "tenant-1", "agent-a", "llm_call",
         "chat", "gpt-4", 2000, 0.10, 800, 1),
        ("2026-07-15T12:00:00", "tenant-1", "agent-b", "tool_call",
         "terminal", "", 0, 0.0, 200, 1),
        ("2026-07-16T10:00:00", "tenant-1", "agent-a", "llm_call",
         "chat", "gpt-3.5", 500, 0.01, 300, 1),
        ("2026-07-16T11:00:00", "tenant-2", "agent-c", "llm_call",
         "code", "claude-3", 3000, 0.15, 1200, 1),
    ]
    for entry in entries:
        db.execute(
            """INSERT INTO audit_log
               (timestamp, tenant_id, agent_id, event_type, tool_name,
                model_name, tokens_used, cost_usd, duration_ms, success)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            entry,
        )
    db.commit()
    return db


@pytest.fixture
def exporter(seeded_db):
    return BillingExporter(seeded_db)


class TestBillingQuery:
    """Record querying tests."""

    def test_query_all(self, exporter):
        """query_records returns all records in range."""
        records = exporter.query_records("2026-07-15", "2026-07-16")
        assert len(records) == 5

    def test_query_date_filter(self, exporter):
        """query_records filters by date range."""
        records = exporter.query_records("2026-07-15", "2026-07-15")
        assert len(records) == 3

    def test_query_tenant_filter(self, exporter):
        """query_records filters by tenant."""
        records = exporter.query_records(
            "2026-07-15", "2026-07-16", tenant_id="tenant-2"
        )
        assert len(records) == 1
        assert records[0].agent_id == "agent-c"

    def test_query_empty_range(self, exporter):
        """query_records returns empty for no-data range."""
        records = exporter.query_records("2025-01-01", "2025-01-02")
        assert len(records) == 0


class TestBillingSummary:
    """Summary aggregation tests."""

    def test_summary_total_cost(self, exporter):
        """summary calculates total cost correctly."""
        s = exporter.summary("2026-07-15", "2026-07-16")
        assert s.total_cost == pytest.approx(0.31, abs=0.001)  # 0.05+0.10+0.00+0.01+0.15
        assert s.total_tokens == 6500  # 1000+2000+0+500+3000
        assert s.total_calls == 5

    def test_summary_by_agent(self, exporter):
        """summary breaks down cost by agent."""
        s = exporter.summary("2026-07-15", "2026-07-16")
        assert "agent-a" in s.by_agent
        assert s.by_agent["agent-a"] == pytest.approx(0.16, abs=0.001)

    def test_summary_by_model(self, exporter):
        """summary breaks down cost by model."""
        s = exporter.summary("2026-07-15", "2026-07-16")
        assert s.by_model["gpt-4"] == pytest.approx(0.15, abs=0.001)

    def test_summary_by_day(self, exporter):
        """summary breaks down cost by day."""
        s = exporter.summary("2026-07-15", "2026-07-16")
        assert "2026-07-15" in s.by_day
        assert "2026-07-16" in s.by_day

    def test_summary_by_tool(self, exporter):
        """summary counts calls by tool."""
        s = exporter.summary("2026-07-15", "2026-07-16")
        assert s.by_tool.get("chat", 0) >= 2

    def test_summary_tenant_filter(self, exporter):
        """summary respects tenant filter."""
        s = exporter.summary("2026-07-15", "2026-07-16", tenant_id="tenant-2")
        assert s.total_calls == 1
        assert s.total_cost == pytest.approx(0.15, abs=0.001)


class TestBillingCSV:
    """CSV export tests."""

    def test_export_csv_creates_file(self, exporter):
        """export_csv creates a CSV file."""
        path = exporter.export_csv("2026-07-15", "2026-07-16")
        assert os.path.exists(path)
        os.unlink(path)

    def test_export_csv_content(self, exporter):
        """export_csv writes correct data."""
        path = exporter.export_csv("2026-07-15", "2026-07-16")
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        assert len(rows) == 6  # Header + 5 data rows
        assert rows[0] == [
            "timestamp", "tenant_id", "agent_id", "event_type",
            "tool_name", "model_name", "tokens_used", "cost_usd",
            "duration_ms", "success",
        ]
        os.unlink(path)

    def test_export_csv_custom_path(self, exporter):
        """export_csv accepts custom output path."""
        custom_path = tempfile.mktemp(suffix=".csv")
        result = exporter.export_csv("2026-07-15", "2026-07-16", output_path=custom_path)
        assert result == custom_path
        assert os.path.exists(custom_path)
        os.unlink(custom_path)

    def test_export_summary_csv(self, exporter):
        """export_summary_csv creates daily summary."""
        path = exporter.export_summary_csv("2026-07-15", "2026-07-16")
        assert os.path.exists(path)
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        assert len(rows) >= 2  # Header + at least 1 data row
        assert rows[0] == ["date", "tenant_id", "calls", "tokens", "cost_usd"]
        os.unlink(path)
