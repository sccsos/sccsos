"""sccsos CLI — workflow management commands."""

from __future__ import annotations

import json
from pathlib import Path

import click

from sccsos.core.agent_runtime import get_runtime as _get_runtime
from sccsos.core.workflow import WorkflowDef, WorkflowValidationError


# ── workflow commands ──────────────────────────────────────────────


@click.group()
def workflow():
    """Manage workflows."""
    pass


@workflow.command()
@click.argument("file")
def validate(file):
    """Validate a workflow YAML file."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    try:
        wf = WorkflowDef.from_yaml(file)
        warnings = runtime.engine.validate(wf)
        click.echo(f"Workflow: {wf.name} v{wf.version}")
        click.echo(f"  Steps: {len(wf.steps)}")
        click.echo(f"  Validation: {'PASSED' if not warnings else 'WARNINGS'}")
        for w in warnings:
            click.echo(f"  ⚠ {w}")
    except WorkflowValidationError as e:
        click.echo(f"Validation FAILED: {e}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


@workflow.command()
@click.argument("file")
@click.option("--input", "-i", "input_text", default="",
              help="Input text (injected as steps.input.context)")
@click.option("--input-file", "input_path", default="",
              help="Read input from file (injected as steps.input)")
@click.option("--async", "async_mode", is_flag=True,
              help="Submit and return immediately (background thread)")
def run(file, input_text, input_path, async_mode):
    """Run a workflow.

    Provide input with --input "text" or --input-file path.yaml.

    Inside workflow YAML steps, use:
      {{ steps.input.context }}   -- the input text
      {{ steps.input.query }}     -- if input is structured (JSON/YAML)

    With --async, the workflow runs in a background daemon thread
    and the CLI returns immediately. Check progress via:
      sccsos workflow list
      sccsos workflow status <run_id>
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    try:
        wf = WorkflowDef.from_yaml(file)
        click.echo(f"Running workflow: {wf.name} ({len(wf.steps)} steps)...")

        input_data = None
        if input_path:
            path_obj = Path(input_path)
            if not path_obj.exists():
                click.echo(f"Error: input file '{input_path}' does not exist.", err=True)
                return
            raw = path_obj.read_text(encoding="utf-8")
            try:
                input_data = json.loads(raw)
            except ValueError:
                input_data = {"context": raw}
        elif input_text:
            input_data = {"context": input_text}

        if async_mode:
            import threading
            def _background():
                try:
                    runtime.engine.execute(wf, input_data=input_data)
                except Exception as e:
                    click.echo(f"Background workflow failed: {e}", err=True)
            t = threading.Thread(target=_background, daemon=True)
            t.start()
            click.echo(f"Workflow submitted in background!")
            click.echo(f"  Use 'sccsos workflow list' to see progress.")
        else:
            run_id = runtime.engine.execute(wf, input_data=input_data)
            click.echo(f"Workflow completed!")
            click.echo(f"  Run ID: {run_id}")
            click.echo(f"  Status: {runtime.engine.get_run_status(run_id)['status']}")
    except WorkflowValidationError as e:
        click.echo(f"Validation FAILED: {e}", err=True)
    except Exception as e:
        click.echo(f"Workflow failed: {e}", err=True)


@workflow.command()
@click.argument("run_id")
def status(run_id):
    """Show workflow run status."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    try:
        status_data = runtime.engine.get_run_status(run_id)
        click.echo(f"Run: {status_data['workflow_name']} ({run_id})")
        click.echo(f"  Status: {status_data['status']}")
        click.echo(f"  Started: {status_data.get('started_at', '-')}")
        click.echo(f"  Finished: {status_data.get('finished_at', '-')}")
        if status_data.get('error'):
            click.echo(f"  Error: {status_data['error']}")

        click.echo(f"\nSteps:")
        for s in status_data.get('steps', []):
            dur = s.get('duration_ms') or 0
            dur_str = f"{dur}ms" if dur < 1000 else f"{dur/1000:.1f}s"
            status_icon = "✅" if s['status'] == 'completed' else "❌" if s['status'] == 'failed' else "⏳"
            click.echo(f"  {status_icon} {s['step_id']}: {s['status']} ({dur_str})")
    except KeyError:
        click.echo(f"Run '{run_id}' not found.", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


@workflow.command()
@click.argument("run_id")
def cancel(run_id):
    """Cancel a running workflow."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    try:
        runtime.engine.cancel_run(run_id)
        click.echo(f"Cancelled: {run_id}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


@workflow.command("list")
@click.option("--tenant", "-t", default="", help="Filter by tenant ID")
def workflow_list(tenant):
    """List recent workflow runs."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    runs = runtime.engine.list_runs(limit=10)
    if tenant:
        runs = [r for r in runs if r.get("tenant_id", "") == tenant]
    if not runs:
        click.echo("No workflow runs yet.")
        return

    click.echo(f"{'Run ID':<24} {'Workflow':<24} {'Status':<14} {'Started':<22} {'Tenant'}")
    click.echo("-" * 90)
    for r in runs:
        started = (r.get('started_at') or '')[:19]
        tid = r.get('tenant_id', 'default')
        click.echo(f"{r['id']:<24} {r['workflow_name']:<24} {r['status']:<14} {started:<22} {tid}")


@workflow.command()
@click.argument("file")
@click.option("--output", "-o", default="", help="Save to file (default: stdout)")
def visualize(file, output):
    """Render a workflow DAG as a Mermaid flowchart."""
    try:
        wf = WorkflowDef.from_yaml(file)
        mermaid = wf.to_mermaid()
        if output:
            Path(output).write_text(mermaid, encoding="utf-8")
            click.echo(f"Mermaid diagram saved to: {output}")
        else:
            click.echo(mermaid)
    except WorkflowValidationError as e:
        click.echo(f"Validation FAILED: {e}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
