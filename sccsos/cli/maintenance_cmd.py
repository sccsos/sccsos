"""Maintenance CLI commands.

Usage:
    sccsos maintenance run        # Run a single maintenance pass
    sccsos maintenance start      # Start background scheduler (daemon)
    sccsos maintenance stop       # Stop background scheduler
    sccsos maintenance status     # Show scheduler status
"""

from __future__ import annotations

import click

from sccsos.core.agent_runtime import get_runtime as _get_runtime

# Global scheduler reference for CLI start/stop
_scheduler = None


def _get_scheduler(runtime):
    global _scheduler
    if _scheduler is None:
        from sccsos.core.maintenance import MaintenanceScheduler
        _scheduler = MaintenanceScheduler(runtime.db)
    return _scheduler


@click.group()
def maintenance():
    """Periodic maintenance tasks (skill cleanup, verification)."""
    pass


@maintenance.command("run")
def maintenance_run():
    """Run a single maintenance pass now."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    scheduler = _get_scheduler(runtime)
    click.echo("Running maintenance...")
    results = scheduler.run_once()

    total = results["_meta"]["total_removed"]
    click.echo(f"Maintenance complete:")
    click.echo(f"  Stale skills pruned: {sum(results['prune_stale'].values())}")
    for status, count in results["prune_stale"].items():
        if count > 0:
            click.echo(f"    - {status}: {count}")
    click.echo(f"  Broken skills pruned: {results['prune_orphaned']}")
    click.echo(f"  Published skills verified: {results['verify']['valid']}/{results['verify']['total']}")
    if results["verify"]["invalid"] > 0:
        click.echo(f"  ⚠️  {results['verify']['invalid']} invalid skills found")
    if total == 0:
        click.echo("  Nothing to clean.")


@maintenance.command("start")
@click.option("--interval", "-i", default=24, help="Interval in hours (default: 24)")
def maintenance_start(interval):
    """Start background maintenance scheduler."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    scheduler = _get_scheduler(runtime)
    scheduler.start(interval_hours=interval)
    click.echo(f"Maintenance scheduler started (interval={interval}h)")


@maintenance.command("stop")
def maintenance_stop():
    """Stop background maintenance scheduler."""
    global _scheduler
    if _scheduler is None:
        click.echo("Scheduler not running.")
        return
    _scheduler.stop()
    _scheduler = None
    click.echo("Maintenance scheduler stopped.")


@maintenance.command("status")
def maintenance_status():
    """Show maintenance scheduler status."""
    global _scheduler
    if _scheduler and hasattr(_scheduler, '_thread') and _scheduler._thread and _scheduler._thread.is_alive():
        click.echo("Maintenance scheduler: 🟢 running")
    else:
        click.echo("Maintenance scheduler: ⚪ stopped")
