"""AgentOS CLI — click-based command line interface.

Integrated with: AgentRuntime (config, database, registry, lifecycle,
hermes_adapter, orchestrator, observability).
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from sccsos.core.agent_runtime import AgentRuntime, get_runtime as _get_runtime, set_runtime as _set_runtime
from sccsos.core.config import get_config
from sccsos.core.lifecycle import AgentStatus, TransitionError
from sccsos.core.orchestrator import WorkflowDef, WorkflowValidationError
from sccsos.observability.logger import get_logger


def _ensure_initialized() -> bool:
    """Ensure runtime services are initialized."""
    runtime = _get_runtime()
    try:
        return runtime.initialize()
    except Exception:
        return False


# ── version ────────────────────────────────────────────────────────


@click.command()
def version():
    """Show sccsos version."""
    cfg = get_config()
    click.echo(f"sccsos v{cfg.project.version}")


# ── init ───────────────────────────────────────────────────────────


@click.command()
@click.option("--dir", "-d", default=".", help="Project directory (default: current)")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing files")
def init(dir, force):
    """Initialize a new sccsos project in DIR."""
    target = Path(dir).resolve()
    click.echo(f"Initializing sccsos project at: {target}")

    # Create runtime directories (flat, no namespace conflict with pip package)
    dirs = [
        target / "data",
        target / "logs",
        target / "traces",
        target / "agents",
        target / "workflows",
        target / "personalities",
        target / "wiki",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # sccsos.yaml
    cfg_path = target / "sccsos.yaml"
    if not cfg_path.exists() or force:
        cfg_path.write_text(_DEFAULT_YAML, encoding="utf-8")
        click.echo(f"  Created: sccsos.yaml")

    # Sample agent
    sample = target / "agents" / "architect.yaml"
    if not sample.exists() or force:
        sample.write_text(_SAMPLE_AGENT, encoding="utf-8")
        click.echo(f"  Created: agents/architect.yaml")

    click.echo("\nsccsos project initialized.")
    click.echo("Run: sccsos agent list")


# ── agent commands ─────────────────────────────────────────────────


@click.group()
def agent():
    """Manage agents."""
    pass


@agent.command("list")
@click.option("--tenant", "-t", default="", help="Filter by tenant ID")
def agent_list(tenant):
    """List all registered agents."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    agents = runtime.registry.list()
    if tenant:
        agents = [a for a in agents if a.tenant_id == tenant]
    if not agents:
        click.echo("No agents registered.")
        return

    click.echo(f"{'Name':<20} {'Version':<10} {'Tenant':<14} {'Status':<14} {'Runner':<10} {'Description'}")
    click.echo("-" * 90)
    for a in agents:
        instance = runtime.lifecycle.get_instance(a.name)
        status = instance.status.value if instance else "registered"
        runner = "running" if runtime.runner.is_running(a.name) else "-"
        click.echo(f"{a.name:<20} {a.version:<10} {a.tenant_id:<14} {status:<14} {runner:<10} {a.description[:40]}")


@agent.command()
@click.argument("name")
@click.option("--file", "-f", "file_path", help="Agent YAML file path")
def create(name, file_path):
    """Create a new agent definition."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    agents_dir = Path(runtime.config.agents.path)
    if not agents_dir.is_absolute():
        agents_dir = Path.cwd() / agents_dir

    if file_path:
        try:
            from sccsos.core.registry import AgentSpec
            spec = AgentSpec.from_yaml(file_path)
            runtime.registry.register(spec)
            click.echo(f"Registered agent: {spec.name} v{spec.version}")
            # Copy to agents directory for persistence
            dst = agents_dir / f"{spec.name}.yaml"
            if not dst.exists():
                import shutil
                shutil.copy2(Path(file_path), dst)
                click.echo(f"  Copied to: {dst}")
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
        return

    # Create inline
    agents_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = agents_dir / f"{name}.yaml"

    if yaml_path.exists():
        click.echo(f"Agent '{name}' already exists at {yaml_path}")
        return

    yaml_path.write_text(f"name: {name}\nversion: 1.0\ndescription: ''\npersonality: helpful\nprofile: sccsos\ntoolsets: []\ntags: []\n", encoding="utf-8")
    click.echo(f"Created: {yaml_path}")
    click.echo("Edit the YAML file to configure, then run: sccsos agent list")


@agent.command()
@click.argument("name")
def start(name):
    """Start an agent (DB state + background process)."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    spec = runtime.registry.find(name)
    if not spec:
        click.echo(f"Agent '{name}' not found in registry.", err=True)
        return

    try:
        instance = runtime.lifecycle.create(spec)
        runtime.lifecycle.start(instance.id)
        # Start background runner
        profile = spec.profile or "sccsos"
        runner_started = runtime.runner.start_agent(
            name, profile=profile,
            policy_engine=runtime.policy_engine,
            model=spec.model,
        )
        if runner_started:
            click.echo(f"Started: {instance.spec.name} ({instance.id}) [background]")
        else:
            click.echo(f"Started: {instance.spec.name} ({instance.id}) [already running]")
    except TransitionError as e:
        click.echo(f"Error: {e}", err=True)


@agent.command()
@click.argument("name")
def stop(name):
    """Stop an agent (DB state + background process)."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    # Stop background runner first
    runner_stopped = runtime.runner.stop_agent(name)
    if runner_stopped:
        click.echo(f"Stopped background process: {name}")

    # Find instance by spec name
    for inst in runtime.lifecycle.list_instances():
        if inst.spec.name == name and inst.status in (
            AgentStatus.RUNNING, AgentStatus.PAUSED, AgentStatus.FAILED
        ):
            try:
                runtime.lifecycle.stop(inst.id)
                click.echo(f"Stopped: {name} ({inst.id})")
                return
            except TransitionError as e:
                click.echo(f"Error: {e}", err=True)
                return

    if not runner_stopped:
        click.echo(f"No running/paused instance found for '{name}'")


@agent.command()
@click.argument("name")
def pause(name):
    """Pause a running agent: RUNNING → PAUSED + stop runner."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    for inst in runtime.lifecycle.list_instances():
        if inst.spec.name == name and inst.status == AgentStatus.RUNNING:
            try:
                runtime.lifecycle.pause(inst.id)
                # Also pause the background runner
                runner_paused = runtime.runner.pause_agent(name)
                if runner_paused:
                    click.echo(f"Paused runner: {name}")
                click.echo(f"Paused: {name} ({inst.id})")
                return
            except TransitionError as e:
                click.echo(f"Error: {e}", err=True)
                return

    click.echo(f"No running instance found for '{name}'")


@agent.command()
@click.argument("name")
def resume(name):
    """Resume a paused agent: PAUSED → RUNNING + resume runner."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    for inst in runtime.lifecycle.list_instances():
        if inst.spec.name == name and inst.status == AgentStatus.PAUSED:
            try:
                runtime.lifecycle.resume(inst.id)
                # Also resume the background runner
                runner_resumed = runtime.runner.resume_agent(name)
                if runner_resumed:
                    click.echo(f"Resumed runner: {name}")
                click.echo(f"Resumed: {name} ({inst.id})")
                return
            except TransitionError as e:
                click.echo(f"Error: {e}", err=True)
                return

    click.echo(f"No paused instance found for '{name}'")


@agent.command()
@click.argument("name")
def restart(name):
    """Restart an agent from any state.

    - RUNNING → stop + start (true restart)
    - PAUSED  → stop + start
    - FAILED  → restart
    - CREATED → start directly
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    for inst in runtime.lifecycle.list_instances():
        if inst.spec.name == name:
            try:
                if inst.status == AgentStatus.FAILED:
                    runtime.lifecycle.restart(inst.id)
                elif inst.status == AgentStatus.RUNNING:
                    # RUNNING → fail → FAILED → restart → RUNNING
                    runtime.lifecycle.fail(inst.id, "restart requested")
                    runtime.lifecycle.restart(inst.id)
                elif inst.status == AgentStatus.PAUSED:
                    # PAUSED → stop → new instance (clean start)
                    runtime.lifecycle.stop(inst.id)
                    new_inst = runtime.lifecycle.create(inst.spec)
                    runtime.lifecycle.start(new_inst.id)
                    inst = new_inst
                elif inst.status == AgentStatus.CREATED:
                    runtime.lifecycle.start(inst.id)
                else:
                    click.echo(f"Cannot restart agent in '{inst.status.value}' state")
                    return

                # (Re)start background runner
                profile = inst.spec.profile or "sccsos"
                runtime.runner.stop_agent(name)
                runtime.runner.start_agent(
                    name, profile=profile,
                    policy_engine=runtime.policy_engine,
                    model=inst.spec.model,
                )
                click.echo(f"Restarted: {name} ({inst.id})")
                return
            except Exception as e:
                click.echo(f"Error: {e}", err=True)
                return

    # No instance exists — try to create + start from registry
    spec = runtime.registry.find(name)
    if spec:
        try:
            instance = runtime.lifecycle.create(spec)
            runtime.lifecycle.start(instance.id)
            profile = spec.profile or "sccsos"
            runtime.runner.start_agent(
                name, profile=profile,
                policy_engine=runtime.policy_engine,
                model=spec.model,
            )
            click.echo(f"Started: {name} ({instance.id})")
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
        return

    click.echo(f"Agent '{name}' not found in registry or lifecycle.")


@agent.command()
@click.argument("name")
def status(name):
    """Show agent status."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    # Check DB for agent instances by name
    record = runtime.db.get_agent_by_name(name)
    if not record:
        click.echo(f"No instances found for agent '{name}'")
        return

    click.echo(f"Agent: {name}")
    click.echo(f"  ID:     {record['id']}")
    click.echo(f"  Status: {record['status']}")
    click.echo(f"  Spec:   v{record['spec_version']}")
    click.echo(f"  Profile: {record['hermes_profile']}")

    if record['session_id']:
        click.echo(f"  Session: {record['session_id']}")

    # Events
    events = runtime.db.get_events(record['id'], limit=5)
    if events:
        click.echo(f"  Recent events ({len(events)}):")
        for e in events:
            click.echo(f"    [{e['event']}] {e.get('detail', '')}")


@agent.command()
@click.argument("name")
@click.option("--limit", "-n", default=20, help="Number of log lines")
def logs(name, limit):
    """Show agent logs."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    record = runtime.db.get_agent_by_name(name)
    if not record:
        click.echo(f"No instances found for agent '{name}'")
        return

    events = runtime.db.get_events(record['id'], limit=limit)
    if not events:
        click.echo(f"No events for agent '{name}'")
        return

    click.echo(f"Events for '{name}' (last {len(events)}):")
    for e in reversed(events):
        click.echo(f"  {e['timestamp']} [{e['event']}] {e.get('detail', '')}")


@agent.command()
@click.argument("name")
@click.argument("prompt", nargs=-1, required=True)
@click.option("--timeout", "-t", default=300, help="Max wait seconds")
def ask(name, prompt, timeout):
    """Send a prompt to a running agent and print response.

    Tries to use a running API Server first (localhost:8765 for persistence).
    Falls back to local auto-start if no API Server is detected.

    Usage:
        sccsos agent ask architect "Design a user auth module"
        sccsos agent ask reviewer "Review this design" --timeout 600
    """
    import urllib.request as _urllib
    import json as _json

    full_prompt = " ".join(prompt)
    click.echo(f"Asking agent '{name}'...")

    # ── Try API Server first (persistent agent process) ──────────
    try:
        req = _urllib.Request("http://127.0.0.1:8765/health",
                              method="GET")
        resp = _urllib.urlopen(req, timeout=1)
        if resp.status == 200:
            # API Server is running — delegate the ask
            body = _json.dumps({
                "prompt": full_prompt,
                "timeout": timeout,
            }).encode("utf-8")
            req2 = _urllib.Request(
                f"http://127.0.0.1:8765/agents/{name}/ask",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp2 = _urllib.urlopen(req2, timeout=timeout + 5)
            data = _json.loads(resp2.read())
            if data.get("success"):
                click.echo(data["response"])
            else:
                click.echo(f"Error: {data.get('error', 'unknown')}", err=True)
            return
    except Exception:
        pass  # API Server unreachable — fall back to local

    # ── Local fallback (auto-start temporary agent process) ──────
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

    # Auto-start if registered but not running
    if not runtime.runner.is_running(name):
        spec = runtime.registry.find(name)
        if spec is not None:
            try:
                instance = runtime.lifecycle.create(spec)
                runtime.lifecycle.start(instance.id)
                profile = spec.profile or "sccsos"
                runtime.runner.start_agent(
                    name, profile=profile,
                    policy_engine=runtime.policy_engine,
                    model=spec.model,
                )
            except Exception:
                pass

    result = runtime.runner.ask_agent(name, full_prompt, timeout=timeout)
    if result.success:
        click.echo(result.response)
    else:
        click.echo(f"Error: {result.error}", err=True)


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

        # Build input_data from --input or --input-file
        input_data = None
        if input_path:
            path_obj = Path(input_path)
            if not path_obj.exists():
                click.echo(f"Error: input file '{input_path}' does not exist.", err=True)
                return
            raw = path_obj.read_text(encoding="utf-8")
            try:
                import json as _json
                input_data = _json.loads(raw)
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
    """Render a workflow DAG as a Mermaid flowchart.

    Output is a Markdown-fenced Mermaid diagram that renders
    natively in GitHub, GitLab, and Obsidian.
    """
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


# ── health ─────────────────────────────────────────────────────────


@click.command()
def health():
    """Check sccsos system health."""
    runtime = _get_runtime()
    cfg = get_config()
    click.echo(f"sccsos v{cfg.project.version}")
    click.echo(f"  Config: {cfg.project.name} v{cfg.project.version}")

    if runtime.initialize():
        h = runtime.health()
        db_h = h.get("database", {})
        click.echo(f"  Database: {db_h.get('status', '?')} ({db_h.get('agent_count', 0)} agents)")
        click.echo(f"  Hermes:   {'OK' if h.get('hermes') else 'unreachable'}")
        click.echo(f"  Agents:   {h.get('agents', 0)} registered")
        click.echo(f"  Traces:   {'available' if h.get('traces_available') else 'none'}")
    else:
        click.echo(f"  Database: not initialized")
        click.echo(f"  Hermes:   not checked")
        click.echo(f"  Agents:   0 registered")


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

    # Build tree
    span_map = {}
    for s in spans:
        span_map[s['span_id']] = s

    def print_span_tree(s, indent=0):
        prefix = "  " * indent + ("└─ " if indent > 0 else "")
        dur = s.get('duration_ms') or 0
        dur_str = f"{dur}ms" if dur < 1000 else f"{dur/1000:.1f}s"
        status = "✅" if s['status'] == 'ok' else "❌"
        click.echo(f"{prefix}{status} {s['name']} ({dur_str})")
        # Recursively print children
        for child in spans:
            if child.get('parent_span_id') == s['span_id']:
                print_span_tree(child, indent + 1)

    # Find root spans (no parent) and print tree
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
    click.echo(f"")
    click.echo(f"  Total calls:    {summary['total_calls']}")
    click.echo(f"  Total tokens:   {summary['total_tokens']:,}")
    click.echo(f"  Total cost:     ${summary['total_cost']:.4f}")
    click.echo(f"  Avg duration:   {summary['avg_duration_ms']:.0f}ms")
    click.echo(f"  Success rate:   {summary['success_count']}/{summary['total_calls']}")

    if report["by_event_type"]:
        click.echo(f"\n  By event type:")
        for item in report["by_event_type"]:
            click.echo(f"    {item['event_type']:<16} {item['count']:>4} calls, {item['tokens']:>6} tokens, ${item['cost']:.4f}")

    if report["by_model"]:
        click.echo(f"\n  By model:")
        for item in report["by_model"]:
            click.echo(f"    {item['model_name']:<24} {item['count']:>4} calls, ${item['cost']:.4f}")

    if report["cost_by_day"]:
        click.echo(f"\n  Cost over time:")
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


# ── main entry point ──────────────────────────────────────────────


@click.group()
def main():
    """sccsos — Smart Agent Runtime Platform for SCCS-T Product Ecosystem."""
    pass


main.add_command(version)
main.add_command(init)
main.add_command(agent)
main.add_command(workflow)
main.add_command(trace)
main.add_command(audit)
main.add_command(memory)
main.add_command(health)


# ── template constants ────────────────────────────────────────────


_DEFAULT_YAML = """# sccsos v0.7.0 project configuration
project:
  name: sccsos
  version: 0.7.0
database:
  path: ./data/sccsos.db
defaults:
  hermes_profile: sccsos
  max_turns: 90
  timeout: 1800
logging:
  level: INFO
  format: json
  directory: ./logs
  retention_days: 30
tracing:
  enabled: true
  export_path: ./traces/
  pricing_path: ./config/pricing.json
agents:
  path: ./agents
  wiki_path: ./wiki
  personalities_path: ./personalities
policies:
  default:
    max_tokens_per_session: 100000
    max_cost_usd: 5.0
    allowed_tools:
      - read_file
      - search_files
      - web_search
      - web_extract
      - terminal
      - delegate_task
    blocked_tools: []
"""

_SAMPLE_AGENT = """name: architect
version: 1.0
description: 智能体架构设计师
personality: agent-architect
profile: sccsos
toolsets:
  - llm-wiki
  - filesystem
  - web-search
tags:
  - core
  - architecture
lifecycle:
  max_turns: 90
  timeout: 1800
  auto_recover: true
"""


if __name__ == "__main__":
    main()
