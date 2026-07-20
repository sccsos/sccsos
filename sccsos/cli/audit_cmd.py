""""Audit CLI commands.

Extracted from system_cmd.py.
"""

from __future__ import annotations
from datetime import datetime
import click
from sccsos.core.agent_runtime import get_runtime as _get_runtime



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


@audit.command("billing")
@click.option("--since", default="", help="Start date (YYYY-MM-DD)")
@click.option("--agent", default="", help="Filter by agent name")
@click.option("--csv", is_flag=True, help="Export as CSV")
def audit_billing(since, agent, csv):
    """Show billing summary — cost breakdown by model and day.

    Use --csv to export cost-by-day data as CSV for spreadsheet import.
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    auditor = runtime.auditor
    report = auditor.generate_report(
        since=since if since else None,
        agent_id=agent if agent else None,
    )

    if csv:
        _export_billing_csv(report)
        return

    from sccsos.observability.auditor import print_billing_summary
    click.echo(print_billing_summary(report))


def _export_billing_csv(report: dict) -> None:
    """Print billing data as CSV to stdout."""
    import csv
    import sys
    writer = csv.writer(sys.stdout)

    s = report.get("summary", {})
    writer.writerow(["Billing Report", report.get("generated_at", "")[:10]])
    writer.writerow(["Metric", "Value"])
    writer.writerow(["Total Calls", s.get("total_calls", 0)])
    writer.writerow(["Total Tokens", s.get("total_tokens", 0)])
    writer.writerow(["Total Cost ($)", f"{s.get('total_cost', 0):.4f}"])
    writer.writerow(["Avg Duration (ms)", f"{s.get('avg_duration_ms', 0):.0f}"])
    writer.writerow([])

    writer.writerow(["Cost by Day"])
    writer.writerow(["Date", "Cost ($)"])
    for d in report.get("cost_by_day", []):
        writer.writerow([d.get("day", ""), f"{d.get('cost', 0):.4f}"])
    writer.writerow([])

    writer.writerow(["Cost by Model"])
    writer.writerow(["Model", "Calls", "Tokens", "Cost ($)"])
    for m in report.get("by_model", []):
        writer.writerow([
            m.get("model_name", ""),
            m.get("count", 0),
            m.get("tokens", 0),
            f"{m.get('cost', 0):.4f}",
        ])
