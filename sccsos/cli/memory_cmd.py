""""Memory CLI commands.

Extracted from system_cmd.py.
"""

from __future__ import annotations
from pathlib import Path
import click
from sccsos.core.agent_runtime import get_runtime as _get_runtime



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
