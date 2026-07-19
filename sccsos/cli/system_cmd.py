"""sccsos CLI — system management commands (trace, audit, memory, session)."""

from __future__ import annotations

import click

from sccsos.core.agent_runtime import get_runtime as _get_runtime


# ── trace commands ─────────────────────────────────────────────────


@click.group()
def trace():
    """View trace data."""
    pass


@trace.command("list")
def trace_list():
    """List recent traces."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    tracer = runtime.tracer
    traces = tracer.list_traces(limit=20)
    if not traces:
        click.echo("No traces found.")
        return

    click.echo(f"{'Trace ID':<24} {'Spans':<8} {'Total (ms)':<12} {'First Span'}")
    click.echo("-" * 70)
    for t in traces:
        first = (t.get('first_span') or '')[:19]
        click.echo(f"{t['trace_id']:<24} {t['span_count']:<8} {t['total_duration_ms']:<12} {first}")


@trace.command()
@click.argument("trace_id")
def show(trace_id):
    """Show details of a specific trace."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    tracer = runtime.tracer
    spans = tracer.get_trace(trace_id)
    if not spans:
        click.echo(f"Trace '{trace_id}' not found.")
        return

    click.echo(f"Trace: {trace_id}")
    click.echo(f"Spans: {len(spans)}")
    click.echo("")

    span_map = {}
    for s in spans:
        span_map[s['span_id']] = s

    def print_span_tree(s, indent=0):
        prefix = "  " * indent + ("└─ " if indent > 0 else "")
        dur = s.get('duration_ms') or 0
        dur_str = f"{dur}ms" if dur < 1000 else f"{dur/1000:.1f}s"
        status = "✅" if s['status'] == 'ok' else "❌"
        click.echo(f"{prefix}{status} {s['name']} ({dur_str})")
        for child in spans:
            if child.get('parent_span_id') == s['span_id']:
                print_span_tree(child, indent + 1)

    roots = [s for s in spans if not s.get('parent_span_id')]
    for root in roots:
        print_span_tree(root)


# ── audit commands ─────────────────────────────────────────────────


@click.group()
def audit():
    """View audit data and reports."""
    pass


@audit.command("report")
@click.option("--since", default="", help="Start date (ISO format, e.g. 2026-07-01)")
@click.option("--agent", default="", help="Filter by agent name")
def audit_report(since, agent):
    """Generate an audit summary report."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    auditor = runtime.auditor
    report = auditor.generate_report(
        since=since if since else None,
        agent_id=agent if agent else None,
    )

    summary = report["summary"]
    click.echo("Audit Report")
    click.echo(f"  Generated: {report['generated_at'][:19]}")
    click.echo("")
    click.echo(f"  Total calls:    {summary['total_calls']}")
    click.echo(f"  Total tokens:   {summary['total_tokens']:,}")
    click.echo(f"  Total cost:     ${summary['total_cost']:.4f}")
    click.echo(f"  Avg duration:   {summary['avg_duration_ms']:.0f}ms")
    click.echo(f"  Success rate:   {summary['success_count']}/{summary['total_calls']}")

    if report["by_event_type"]:
        click.echo("\n  By event type:")
        for item in report["by_event_type"]:
            click.echo(f"    {item['event_type']:<16} {item['count']:>4} calls, {item['tokens']:>6} tokens, ${item['cost']:.4f}")

    if report["by_model"]:
        click.echo("\n  By model:")
        for item in report["by_model"]:
            click.echo(f"    {item['model_name']:<24} {item['count']:>4} calls, ${item['cost']:.4f}")

    if report["cost_by_day"]:
        click.echo("\n  Cost over time:")
        for item in report["cost_by_day"]:
            click.echo(f"    {item['day']}: ${item['cost']:.4f}")


@audit.command("log")
@click.option("--limit", "-n", default=20, help="Number of entries")
@click.option("--agent", default="", help="Filter by agent name")
def audit_log(limit, agent):
    """View recent audit log entries."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    auditor = runtime.auditor
    entries = auditor.list_recent(
        limit=limit,
        agent_id=agent if agent else None,
    )
    if not entries:
        click.echo("No audit entries found.")
        return

    click.echo(f"{'Time':<22} {'Type':<14} {'Tokens':<8} {'Cost':<10} {'Detail'}")
    click.echo("-" * 90)
    for e in entries:
        ts = (e.get('timestamp') or '')[:19]
        type_ = e.get('event_type', '')
        tokens = e.get('tokens_used', 0)
        cost = e.get('cost_usd', 0)
        detail = (e.get('detail') or '')[:40]
        click.echo(f"{ts:<22} {type_:<14} {tokens:<8} ${cost:<7.4f} {detail}")


# ── memory commands ─────────────────────────────────────────────


@click.group()
def memory():
    """Manage agent persistent memory (cross-session KV store)."""
    pass


@memory.command("save")
@click.argument("agent_name")
@click.argument("key")
@click.argument("value")
@click.option("--tenant", "-t", default="default", help="Tenant ID")
def memory_save(agent_name, key, value, tenant):
    """Save a memory entry for an agent.

    Usage: sccsos memory save architect preferred_lang Python
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return
    runtime.memory.save(agent_name, key, value, tenant_id=tenant)
    click.echo(f"Saved: {agent_name}/{key} = {value[:60]}")


@memory.command("get")
@click.argument("agent_name")
@click.argument("key")
@click.option("--tenant", "-t", default="default", help="Tenant ID")
def memory_get(agent_name, key, tenant):
    """Get a memory entry for an agent."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return
    value = runtime.memory.get(agent_name, key, tenant_id=tenant)
    if value is None:
        click.echo(f"Key '{key}' not found for agent '{agent_name}'")
    else:
        click.echo(value)


@memory.command("list")
@click.argument("agent_name")
@click.option("--tenant", "-t", default="default", help="Tenant ID")
def memory_list(agent_name, tenant):
    """List all memory keys for an agent."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return
    keys = runtime.memory.list_keys(agent_name, tenant_id=tenant)
    if not keys:
        click.echo(f"No memory entries for agent '{agent_name}'")
        return
    click.echo(f"Memory keys for '{agent_name}':")
    for k in keys:
        click.echo(f"  - {k}")


@memory.command("delete")
@click.argument("agent_name")
@click.argument("key")
@click.option("--tenant", "-t", default="default", help="Tenant ID")
def memory_delete(agent_name, key, tenant):
    """Delete a memory entry for an agent."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return
    deleted = runtime.memory.delete(agent_name, key, tenant_id=tenant)
    if deleted:
        click.echo(f"Deleted: {agent_name}/{key}")
    else:
        click.echo(f"Key '{key}' not found for agent '{agent_name}'")


@memory.command("clear")
@click.argument("agent_name")
@click.option("--tenant", "-t", default="default", help="Tenant ID")
def memory_clear(agent_name, tenant):
    """Clear all memory entries for an agent."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return
    count = runtime.memory.clear_agent(agent_name, tenant_id=tenant)
    click.echo(f"Cleared {count} entries for agent '{agent_name}'")


# ── session commands ────────────────────────────────────────────────


@click.group()
def session():
    """Manage agent conversation sessions."""
    pass


@session.command("list")
@click.option("--agent", "-a", "agent_name", default=None,
              help="Filter by agent name")
@click.option("--tenant", "-t", default="default", help="Tenant ID")
@click.option("--status", "-s", default=None,
              help="Filter by status (active|paused|closed)")
def session_list(agent_name, tenant, status):
    """List conversation sessions.

    Usage:
        sccsos session list
        sccsos session list --agent architect
        sccsos session list --status active
        sccsos session list --agent arch --status paused
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return
    sessions = runtime.session_manager.list_sessions(
        agent_name=agent_name, tenant_id=tenant, status=status,
    )
    if not sessions:
        click.echo("No sessions found.")
        return
    click.echo(f"{'Session ID':<24} {'Agent':<16} {'Status':<10} {'Updated':<22} {'Summary'}")
    click.echo("-" * 120)
    for s in sessions:
        summary = s.context_summary[:50] + "..." if len(s.context_summary) > 50 else s.context_summary
        click.echo(f"{s.id:<24} {s.agent_name:<16} {s.status:<10} {s.updated_at:<22} {summary}")


@session.command("show")
@click.argument("session_id")
def session_show(session_id):
    """Show the message history for a session.

    Usage:
        sccsos session show ses_abc123
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    sessions = runtime.session_manager.list_sessions()
    session_obj = next((s for s in sessions if s.id == session_id), None)
    if session_obj is None:
        click.echo(f"Session '{session_id}' not found.")
        return

    click.echo(f"Session: {session_obj.id}")
    click.echo(f"  Agent:  {session_obj.agent_name}")
    click.echo(f"  Status: {session_obj.status}")
    click.echo(f"  Created: {session_obj.created_at}")
    click.echo(f"  Updated: {session_obj.updated_at}")
    if session_obj.context_summary:
        click.echo(f"  Summary: {session_obj.context_summary}")
    click.echo("")

    messages = runtime.session_manager.get_history(session_id, limit=50)
    if not messages:
        click.echo("No messages in this session.")
        return

    click.echo(f"Messages ({len(messages)}):")
    click.echo("-" * 60)
    for msg in messages:
        prefix = "🧑" if msg.role == "user" else "🤖"
        content = msg.content[:200]
        if len(msg.content) > 200:
            content += "..."
        click.echo(f"{prefix} [{msg.role}] {content}")


@session.command("close")
@click.argument("session_id")
@click.option("--force", "-f", is_flag=True,
              help="Close even if not in active status")
def session_close(session_id, force):
    """Close a session.

    Usage:
        sccsos session close ses_abc123
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    sessions = runtime.session_manager.list_sessions()
    session_obj = next((s for s in sessions if s.id == session_id), None)
    if session_obj is None:
        click.echo(f"Session '{session_id}' not found.", err=True)
        return

    if session_obj.status == "closed":
        click.echo(f"Session '{session_id}' is already closed.")
        return

    runtime.session_manager.close_session(session_id, new_status="closed")
    click.echo(f"Session '{session_id}' closed.")
