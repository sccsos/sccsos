""""Trace CLI commands.

Extracted from system_cmd.py.
"""

from __future__ import annotations
from pathlib import Path
import click
from sccsos.core.agent_runtime import get_runtime as _get_runtime



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
