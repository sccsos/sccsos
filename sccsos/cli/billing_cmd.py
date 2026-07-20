"""Billing CLI commands.

Usage:
    sccsos billing report <start> <end> [--tenant <id>]
    sccsos billing export <start> <end> [--tenant <id>] [--output <path>]
    sccsos billing summary <start> <end> [--output <path>]
"""

from __future__ import annotations

import click

from sccsos.core.agent_runtime import get_runtime as _get_runtime


@click.group()
def billing():
    """Usage billing and cost reporting."""
    pass


@billing.command("report")
@click.argument("start_date")
@click.argument("end_date")
@click.option("--tenant", "-t", default=None, help="Tenant ID filter")
def billing_report(start_date, end_date, tenant):
    """Show billing report for a date range.

    Dates in ISO format: YYYY-MM-DD

    Example:
        sccsos billing report 2026-07-01 2026-07-31
        sccsos billing report 2026-07-01 2026-07-31 --tenant tenant-1
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.observability.billing import BillingExporter
    exporter = BillingExporter(runtime.db)

    s = exporter.summary(start_date, end_date, tenant_id=tenant)

    tenant_label = f" (tenant: {tenant})" if tenant else ""
    click.echo(f"Billing Report: {start_date} → {end_date}{tenant_label}")
    click.echo("")
    click.echo("  Summary:")
    click.echo(f"    Total Calls:     {s.total_calls:,}")
    click.echo(f"    Total Tokens:    {s.total_tokens:,}")
    click.echo(f"    Total Cost:      ${s.total_cost:.4f}")
    click.echo(f"    Total Duration:  {s.total_duration_ms / 1000:.1f}s")
    click.echo("")
    click.echo("  Cost by Agent:")
    for agent, cost in sorted(s.by_agent.items(), key=lambda x: x[1], reverse=True):
        pct = (cost / s.total_cost * 100) if s.total_cost > 0 else 0
        click.echo(f"    {agent:<20} ${cost:.4f} ({pct:.1f}%)")
    click.echo("")
    click.echo("  Cost by Model:")
    for model, cost in sorted(s.by_model.items(), key=lambda x: x[1], reverse=True):
        pct = (cost / s.total_cost * 100) if s.total_cost > 0 else 0
        click.echo(f"    {model:<25} ${cost:.4f} ({pct:.1f}%)")
    click.echo("")
    click.echo("  Cost by Day:")
    for day, cost in sorted(s.by_day.items()):
        click.echo(f"    {day}  ${cost:.4f}")
    click.echo("")
    click.echo("  Calls by Tool:")
    for tool, count in sorted(s.by_tool.items(), key=lambda x: x[1], reverse=True):
        click.echo(f"    {tool:<20} {count}")


@billing.command("export")
@click.argument("start_date")
@click.argument("end_date")
@click.option("--tenant", "-t", default=None, help="Tenant ID filter")
@click.option("--output", "-o", default=None, help="Output CSV file path")
def billing_export(start_date, end_date, tenant, output):
    """Export detailed billing records to CSV.

    Example:
        sccsos billing export 2026-07-01 2026-07-31
        sccsos billing export 2026-07-01 2026-07-31 --tenant prod --output report.csv
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.observability.billing import BillingExporter
    exporter = BillingExporter(runtime.db)

    path = exporter.export_csv(
        start_date, end_date,
        tenant_id=tenant,
        output_path=output,
    )
    click.echo(f"✅ Billing CSV exported: {path}")


@billing.command("summary")
@click.argument("start_date")
@click.argument("end_date")
@click.option("--output", "-o", default=None, help="Output CSV file path")
def billing_summary(start_date, end_date, output):
    """Export daily billing summary to CSV.

    Groups cost by day and tenant.

    Example:
        sccsos billing summary 2026-07-01 2026-07-31
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.observability.billing import BillingExporter
    exporter = BillingExporter(runtime.db)

    path = exporter.export_summary_csv(
        start_date, end_date,
        output_path=output,
    )
    click.echo(f"✅ Billing summary exported: {path}")
