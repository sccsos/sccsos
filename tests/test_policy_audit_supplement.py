"""Supplement tests for PolicyEngine and Auditor — edge cases.

Covers remaining uncovered lines:
  - PolicyEngine: named policy ref resolution, per-agent policy with
    inline override, check_delegation with fallback
  - Auditor: record_tool_call, list_recent with agent_id filter,
    billing summary formatting
"""

from __future__ import annotations

import os
import tempfile

import pytest

from sccsos.core.config import AgentOSConfig, PoliciesConfig, PolicyDefaults
from sccsos.core.db import Database
from sccsos.observability.auditor import Auditor, AuditEntry, print_billing_summary
from sccsos.observability.pricing import PricingTable
from sccsos.security.policy import PolicyEngine


@pytest.fixture
def db():
    tmp = tempfile.mktemp(suffix=".db")
    database = Database(db_path=tmp)
    database.initialize()
    yield database
    database.close()
    os.unlink(tmp)


@pytest.fixture
def pricing():
    return PricingTable()


@pytest.fixture
def auditor(db, pricing):
    return Auditor(db, pricing)


@pytest.fixture
def config_with_named_policy():
    """Config with a named policy that can be referenced by agents."""
    return AgentOSConfig(
        policies=PoliciesConfig(
            default=PolicyDefaults(
                max_cost_usd=10.0,
                allowed_tools=["read_file", "web_search"],
                blocked_tools=["terminal"],
            ),
            named={
                "restricted": PolicyDefaults(
                    max_cost_usd=1.0,
                    allowed_tools=["read_file"],
                    blocked_tools=["terminal", "web_search"],
                ),
            },
        )
    )


# ── PolicyEngine supplement ──────────────────────────────────────────


class TestPolicyEngineNamedPolicy:
    """Per-agent policies with named ref resolution."""

    def test_named_policy_ref_resolved(self, db, config_with_named_policy):
        """Agent with policy.ref should use the named policy."""
        engine = PolicyEngine(db, config_with_named_policy)
        engine.set_agent_policy("restricted-agent", {"ref": "restricted"})

        # Restricted agent should have max_cost_usd=1.0
        result = engine.check_delegation(
            agent_name="restricted-agent", estimated_cost=2.0,
        )
        assert not result.allowed
        assert "Budget exceeded" in result.reason

    def test_named_policy_nonexistent_ref_falls_back(self, db, config_with_named_policy):
        """Referencing a non-existent named policy should fall back to default."""
        engine = PolicyEngine(db, config_with_named_policy)
        engine.set_agent_policy("ghost-agent", {"ref": "nonexistent-policy"})

        result = engine.check_delegation(
            agent_name="ghost-agent", estimated_cost=5.0,
        )
        assert result.allowed  # Falls back to default max_cost_usd=10.0

    def test_inline_policy_override(self, db, config_with_named_policy):
        """Per-agent inline policy fields should override defaults."""
        engine = PolicyEngine(db, config_with_named_policy)
        engine.set_agent_policy("budget-agent", {"max_cost_usd": 0.5})

        result = engine.check_delegation(
            agent_name="budget-agent", estimated_cost=1.0,
        )
        assert not result.allowed

    def test_set_agent_policy_none_clears(self, db, config_with_named_policy):
        """Passing None to set_agent_policy should clear the override."""
        engine = PolicyEngine(db, config_with_named_policy)
        engine.set_agent_policy("temp-agent", {"max_cost_usd": 0.0})
        engine.set_agent_policy("temp-agent", None)  # Clear

        result = engine.check_delegation(
            agent_name="temp-agent", estimated_cost=100.0,
        )
        assert not result.allowed  # Falls to default with max_cost_usd=10.0

    def test_tool_access_no_config(self, db):
        """Without config, check_tool_access should allow everything."""
        engine = PolicyEngine(db, config=None)
        result = engine.check_tool_access("any-agent", "terminal")
        assert result.allowed


# ── Auditor supplement ──────────────────────────────────────────────


class TestAuditorSupplement:
    """Auditor methods including tool calls and querying."""

    def test_record_tool_call(self, auditor):
        """record_tool_call should create an audit entry and return an ID."""
        entry_id = auditor.record_tool_call(
            agent_id="agent-x",
            tool="web_search",
            duration_ms=150,
            success=True,
            tenant_id="t1",
        )
        assert entry_id > 0

        # Query it back
        rows = auditor._db.execute(
            "SELECT event_type, tool_name, agent_id, tenant_id FROM audit_log WHERE id = ?",
            (entry_id,),
        ).fetchone()
        assert rows is not None
        assert rows[0] == "tool_call"
        assert rows[1] == "web_search"
        assert rows[2] == "agent-x"
        assert rows[3] == "t1"

    def test_record_tool_call_failure(self, auditor):
        """Failed tool calls should still be recorded."""
        entry_id = auditor.record_tool_call(
            agent_id="agent-y",
            tool="terminal",
            duration_ms=5000,
            success=False,
        )
        assert entry_id > 0

    def test_record_llm_call(self, auditor):
        """record_llm_call should estimate cost from token counts."""
        entry_id = auditor.record_llm_call(
            agent_id="agent-z",
            model="deepseek-v4-flash",
            tokens_input=1000,
            tokens_output=500,
            tenant_id="t2",
        )
        assert entry_id > 0

        row = auditor._db.execute(
            "SELECT cost_usd, tokens_used FROM audit_log WHERE id = ?",
            (entry_id,),
        ).fetchone()
        assert row is not None
        assert row[1] == 1500  # 1000 + 500

    def test_list_recent_all(self, auditor):
        """list_recent without agent_id returns all entries."""
        auditor.record_llm_call("agent-a", "gpt-4", 100, 50)
        auditor.record_llm_call("agent-b", "claude-3", 200, 100)
        entries = auditor.list_recent(limit=10)
        assert len(entries) >= 2

    def test_list_recent_by_agent(self, auditor):
        """list_recent with agent_id filters by agent."""
        auditor.record_llm_call("agent-filter", "gpt-4", 100, 50)
        auditor.record_llm_call("agent-other", "claude-3", 200, 100)
        entries = auditor.list_recent(agent_id="agent-filter")
        assert len(entries) == 1
        assert entries[0]["agent_id"] == "agent-filter"

    def test_list_recent_empty_for_unknown_agent(self, auditor):
        """Unknown agent_id should return empty list."""
        entries = auditor.list_recent(agent_id="ghost")
        assert entries == []


class TestAuditReport:
    """Audit report generation and billing summary."""

    def test_generate_report_with_data(self, auditor):
        """generate_report should produce a structured summary dict."""
        auditor.record_llm_call("agent-a", "deepseek-v4-flash", 1000, 500)
        auditor.record_llm_call("agent-a", "deepseek-v4-flash", 2000, 1000)
        auditor.record_tool_call("agent-a", "web_search")
        auditor.record_tool_call("agent-b", "terminal", success=False)

        report = auditor.generate_report()
        assert report["summary"]["total_calls"] >= 4
        assert report["summary"]["total_tokens"] >= 4500  # 1500 + 3000
        assert report["summary"]["success_count"] >= 3
        assert report["summary"]["fail_count"] >= 1
        assert len(report["by_event_type"]) >= 2
        assert len(report["cost_by_day"]) >= 1

    def test_generate_report_with_filters(self, auditor):
        """generate_report should support temporal and agent filters."""
        auditor.record_llm_call("agent-f", "gpt-4", 500, 250)
        auditor.record_llm_call("agent-g", "claude-3", 300, 150)

        report = auditor.generate_report(agent_id="agent-f")
        assert report["summary"]["total_calls"] == 1

    def test_print_billing_summary(self, auditor):
        """print_billing_summary should format a readable string."""
        auditor.record_llm_call("agent-a", "deepseek-v4-flash", 1000, 500)
        report = auditor.generate_report()
        summary = print_billing_summary(report)

        assert "Billing Summary" in summary
        assert "Total calls" in summary
        assert "Total cost" in summary
        assert "deepseek" in summary

    def test_print_billing_summary_empty(self):
        """Empty report should still produce valid output."""
        report = {
            "summary": {
                "total_calls": 0, "total_tokens": 0, "total_cost": 0,
                "avg_duration_ms": 0, "success_count": 0, "fail_count": 0,
            },
            "by_event_type": [],
            "by_model": [],
            "cost_by_day": [],
            "generated_at": "2026-07-22T00:00:00",
        }
        summary = print_billing_summary(report)
        assert "Billing Summary" in summary
        assert "Total calls:     0" in summary


class TestAuditEntry:
    """AuditEntry dataclass defaults and construction."""

    def test_defaults(self):
        e = AuditEntry(agent_id="test", event_type="llm_call")
        assert e.tenant_id == "default"
        assert e.tool_name == ""
        assert e.success
        assert e.cost_usd == 0.0

    def test_all_fields(self):
        e = AuditEntry(
            agent_id="agent-x",
            event_type="tool_call",
            tenant_id="t1",
            tool_name="terminal",
            model_name="gpt-4",
            tokens_input=100,
            tokens_output=50,
            cost_usd=0.01,
            duration_ms=200,
            success=False,
            detail="something went wrong",
        )
        assert e.agent_id == "agent-x"
        assert not e.success
