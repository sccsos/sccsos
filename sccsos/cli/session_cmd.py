""""Session CLI commands.

Extracted from system_cmd.py.
"""

from __future__ import annotations
from pathlib import Path
import click
from sccsos.core.agent_runtime import get_runtime as _get_runtime



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
