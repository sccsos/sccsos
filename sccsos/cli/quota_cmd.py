"""Quota management CLI commands.

Usage:
    sccsos quota show [--tenant <id>]
    sccsos quota list
    sccsos quota set <tenant> [options]
    sccsos quota reset <tenant>
"""

from __future__ import annotations

import click

from sccsos.core.agent_runtime import get_runtime as _get_runtime


@click.group()
def quota():
    """Manage per-tenant resource quotas."""
    pass


@quota.command("show")
@click.option("--tenant", "-t", default="default", help="Tenant ID (default: default)")
def quota_show(tenant):
    """Show quota limits and current usage for a tenant."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.core.quota_manager import QuotaManager
    mgr = QuotaManager(runtime.db)

    limit = mgr.get_quota(tenant)
    usage = mgr.get_usage(tenant)

    click.echo(f"Resource Quota — Tenant: {tenant}")
    click.echo("")
    click.echo("  Limits:")
    click.echo(f"    Max Agents:          {limit.max_agents}")
    click.echo(f"    Max Tokens/Day:      {limit.max_tokens_per_day:,}")
    click.echo(f"    Max Cost/Day:        ${limit.max_cost_per_day:.2f}")
    click.echo(f"    Max Cost Total:      ${limit.max_cost_total:.2f}")
    click.echo(f"    Max Memory Entries:  {limit.max_memory_entries:,}")
    click.echo(f"    Max Storage (MB):    {limit.max_storage_mb}")
    click.echo("")
    click.echo("  Current Usage:")
    click.echo(f"    Active Agents:       {usage.agent_count}")
    click.echo(f"    Tokens Today:        {usage.tokens_today:,}")
    click.echo(f"    Cost Today:          ${usage.cost_today:.4f}")
    click.echo(f"    Cost Total:          ${usage.cost_total:.4f}")
    click.echo(f"    Memory Entries:      {usage.memory_entries:,}")


@quota.command("list")
def quota_list():
    """List all configured tenant quotas."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.core.quota_manager import QuotaManager
    mgr = QuotaManager(runtime.db)

    quotas = mgr.list_quotas()
    if not quotas:
        click.echo("No custom quotas configured (all tenants use defaults).")
        return

    click.echo(f"{'Tenant':<20} {'Agents':<8} {'Tokens/Day':<14} {'Cost/Day':<12} {'Cost Total':<12}")
    click.echo("-" * 66)
    for q in quotas:
        click.echo(
            f"{q.tenant_id:<20} {q.max_agents:<8} "
            f"{q.max_tokens_per_day:<14,} ${q.max_cost_per_day:<8.2f} "
            f"${q.max_cost_total:<8.2f}"
        )


@quota.command("set")
@click.argument("tenant", default="default")
@click.option("--max-agents", "-a", default=None, type=int, help="Max concurrent agents")
@click.option("--max-tokens", "-t", default=None, type=int, help="Max tokens per day")
@click.option("--max-cost-day", "-c", default=None, type=float, help="Max cost per day (USD)")
@click.option("--max-cost-total", "-C", default=None, type=float, help="Max total cost (USD)")
@click.option("--max-memory", "-m", default=None, type=int, help="Max memory store entries")
@click.option("--max-storage", "-s", default=None, type=int, help="Max DB storage (MB)")
def quota_set(tenant, max_agents, max_tokens, max_cost_day,
              max_cost_total, max_memory, max_storage):
    """Set quota limits for a tenant.

    Only specified limits are updated; unspecified fields keep
    their current or default values.

    Example:
        sccsos quota set tenant-1 --max-agents 5 --max-tokens 200000
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.core.quota_manager import QuotaManager
    mgr = QuotaManager(runtime.db)

    # Get current limits as base, then override specified fields
    current = mgr.get_quota(tenant)

    new_agents = max_agents if max_agents is not None else current.max_agents
    new_tokens = max_tokens if max_tokens is not None else current.max_tokens_per_day
    new_cost_day = max_cost_day if max_cost_day is not None else current.max_cost_per_day
    new_cost_total = max_cost_total if max_cost_total is not None else current.max_cost_total
    new_memory = max_memory if max_memory is not None else current.max_memory_entries
    new_storage = max_storage if max_storage is not None else current.max_storage_mb

    mgr.set_quota(
        tenant_id=tenant,
        max_agents=new_agents,
        max_tokens_per_day=new_tokens,
        max_cost_per_day=new_cost_day,
        max_cost_total=new_cost_total,
        max_memory_entries=new_memory,
        max_storage_mb=new_storage,
    )

    click.echo(f"✅ Quota updated for tenant '{tenant}'")
    click.echo(f"  Agents: {current.max_agents} → {new_agents}")
    click.echo(f"  Tokens/Day: {current.max_tokens_per_day:,} → {new_tokens:,}")
    click.echo(f"  Cost/Day: ${current.max_cost_per_day:.2f} → ${new_cost_day:.2f}")
    click.echo(f"  Cost Total: ${current.max_cost_total:.2f} → ${new_cost_total:.2f}")
    click.echo(f"  Memory: {current.max_memory_entries:,} → {new_memory:,}")
    click.echo(f"  Storage: {current.max_storage_mb} → {new_storage} MB")


@quota.command("reset")
@click.argument("tenant", default="default")
def quota_reset(tenant):
    """Reset quota to defaults for a tenant."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.core.quota_manager import QuotaManager
    mgr = QuotaManager(runtime.db)

    mgr.reset_quota(tenant)
    click.echo(f"✅ Quota reset to defaults for tenant '{tenant}'")
