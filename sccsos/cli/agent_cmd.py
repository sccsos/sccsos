"""sccsos CLI — agent management commands."""

from __future__ import annotations

import shutil
from pathlib import Path

import click

from sccsos.core.agent_runtime import get_runtime as _get_runtime
from sccsos.core.lifecycle import AgentStatus, TransitionError


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

    life_status: dict[str, str] = {}
    for inst in runtime.lifecycle.list_instances():
        life_status[inst.spec.name] = inst.status.value

    click.echo(f"{'Name':<20} {'Version':<10} {'Tenant':<14} {'Status':<14} {'Runner':<10} {'Description'}")
    click.echo("-" * 90)
    for a in agents:
        status = life_status.get(a.name, "registered")
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
            dst = agents_dir / f"{spec.name}.yaml"
            if not dst.exists():
                shutil.copy2(Path(file_path), dst)
                click.echo(f"  Copied to: {dst}")
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
        return

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

    runner_stopped = runtime.runner.stop_agent(name)
    if runner_stopped:
        click.echo(f"Stopped background process: {name}")

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
    """Restart an agent from any state."""
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
                    runtime.lifecycle.fail(inst.id, "restart requested")
                    runtime.lifecycle.restart(inst.id)
                elif inst.status == AgentStatus.PAUSED:
                    runtime.lifecycle.stop(inst.id)
                    new_inst = runtime.lifecycle.create(inst.spec)
                    runtime.lifecycle.start(new_inst.id)
                    inst = new_inst
                elif inst.status == AgentStatus.CREATED:
                    runtime.lifecycle.start(inst.id)
                else:
                    click.echo(f"Cannot restart agent in '{inst.status.value}' state")
                    return

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
    """Send a prompt to a running agent and print response."""
    import json as _json
    import urllib.request as _urllib

    full_prompt = " ".join(prompt)
    click.echo(f"Asking agent '{name}'...")

    # ── Try API Server first (persistent agent process) ──────────
    try:
        req = _urllib.Request("http://127.0.0.1:8765/health", method="GET")
        resp = _urllib.urlopen(req, timeout=1)
        if resp.status == 200:
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

    # ── Local fallback ──────────────────────────────────────────────
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized. Run 'sccsos init' first.")
        return

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
