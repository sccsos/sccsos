"""sccsos CLI — main entry point, top-level commands, group wiring."""

from __future__ import annotations

from pathlib import Path

import click

from sccsos.core.agent_runtime import get_runtime as _get_runtime
from sccsos.core.config import get_config
from sccsos.cli.agent_cmd import agent
from sccsos.cli.workflow_cmd import workflow
from sccsos.cli.trace_cmd import trace
from sccsos.cli.audit_cmd import audit
from sccsos.cli.memory_cmd import memory
from sccsos.cli.session_cmd import session
from sccsos.cli.personality_cmd import personality
from sccsos.cli.skill_cmd import skill
from sccsos.cli.quota_cmd import quota
from sccsos.cli.billing_cmd import billing
from sccsos.cli.benchmark_cmd import benchmark
from sccsos.cli.config_cmd import config_show, webhook
from sccsos.cli.maintenance_cmd import maintenance
from sccsos.cli.plugin_cmd import plugin
from sccsos.cli.hermes_cmd import hermes_cmd
from sccsos.cli.init_cmd import init
from sccsos.cli.role_cmd import role_cmd
from sccsos.cli.sample_templates import SAMPLE_FILES, SAMPLE_PRICING, SAMPLE_YAML_FULL


# ── version ────────────────────────────────────────────────────────


@click.command()
def version():
    """Show sccsos version."""
    cfg = get_config()
    click.echo(f"sccsos v{cfg.project.version}")


# ── init (imported from init_cmd) ────────────────────────────────────
# The ``init`` command is defined in ``cli/init_cmd.py`` and imported above.


# ── doctor ─────────────────────────────────────────────────────────


@click.command()
def doctor():
    """Check sccsos installation and optional dependencies."""
    cfg = get_config()
    click.echo(f"sccsos v{cfg.project.version} — System Check")
    click.echo("")

    checks = []

    # Core
    try:
        import yaml
        checks.append(("pyyaml", True, "core"))
    except ImportError:
        checks.append(("pyyaml", False, "core"))
    try:
        import jinja2
        checks.append(("jinja2", True, "core"))
    except ImportError:
        checks.append(("jinja2", False, "core"))

    # Optional: API
    try:
        import fastapi
        checks.append(("fastapi + uvicorn", True, "api"))
    except ImportError:
        checks.append(("fastapi + uvicorn", False, "api"))

    # Optional: OTEL
    try:
        from opentelemetry import trace
        checks.append(("opentelemetry", True, "otel"))
    except ImportError:
        checks.append(("opentelemetry", False, "otel"))

    # Optional: PostgreSQL
    try:
        import psycopg2
        checks.append(("psycopg2 (PostgreSQL)", True, "pg"))
    except ImportError:
        checks.append(("psycopg2 (PostgreSQL)", False, "pg"))

    # Optional: Kafka
    try:
        import kafka
        checks.append(("kafka-python", True, "kafka"))
    except ImportError:
        checks.append(("kafka-python", False, "kafka"))

    # Optional: Hermes Agent
    import shutil
    hermes_ok = shutil.which("hermes") is not None
    checks.append(("Hermes Agent CLI", hermes_ok, "runtime"))

    # Print results
    for name, ok, group in checks:
        status = "✅" if ok else "⬜"
        click.echo(f"  {status}  {name}")
        if not ok and group != "core":
            pip_cmd = {
                "api": "pip install \"sccsos[api]\"",
                "otel": "pip install \"sccsos[otel]\"",
                "pg": "pip install \"sccsos[pg]\"",
                "kafka": "pip install \"sccsos[kafka]\"",
                "runtime": "Install Hermes Agent manually (see docs)",
            }.get(group, "")
            if pip_cmd:
                click.echo(f"       → Install: {pip_cmd}")

    click.echo("")
    all_ok = all(ok for _, ok, _ in checks if ok)
    if all_ok:
        click.echo("✅ All dependencies satisfied.")
    else:
        missing = [n for n, ok, _ in checks if not ok]
        click.echo(f"⚠️  Missing: {', '.join(missing)}")
        click.echo("   Run: pip install \"sccsos[all]\"  (installs everything)")


# ── config ─────────────────────────────────────────────────────────


@click.group()
def config():
    """Manage sccsos configuration."""
    pass


config.add_command(config_show)
config.add_command(webhook)


@config.command("reload")
def config_reload():
    """Reload configuration from disk (sccsos.yaml).

    Applies changes to logging, tracing, pricing, agents path,
    and policies without restarting the system.

    Use this after editing sccsos.yaml to apply the new settings.
    """
    from sccsos.core.config import reload_config
    new_cfg = reload_config()
    click.echo(f"Config reloaded: {new_cfg.project.name} v{new_cfg.project.version}")
    click.echo(f"  Database:        {new_cfg.database.path}")
    click.echo(f"  Logging level:   {new_cfg.logging.level}")
    click.echo(f"  Tracing:         {'enabled' if new_cfg.tracing.enabled else 'disabled'}")
    click.echo(f"  Pricing path:    {new_cfg.pricing.path or '(default)'}")
    click.echo(f"  Policies:        {len(new_cfg.policies.named)} named policies")


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


# ── serve ──────────────────────────────────────────────────────────


@click.command()
@click.option("--port", "-p", default=8765, help="Port (default: 8765)")
@click.option("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
@click.option("--legacy", is_flag=True, help="Use legacy http.server instead of FastAPI (DEPRECATED)")
def serve(port, host, legacy):
    """Start the sccsos HTTP API server.

    By default uses the FastAPI server (requires ``pip install sccsos[api]``).
    Falls back to the legacy ``http.server`` implementation if FastAPI is
    not available, or if ``--legacy`` is specified.

    .. note::
        The legacy ``http.server`` is **deprecated** and will be removed
        in v0.12.0. Migrate to FastAPI: ``pip install sccsos[api]``

    Endpoints:
      GET  /health          — System health
      GET  /agents          — List agents
      POST /agents/{n}/ask  — Send prompt to agent
      POST /workflows/run   — Execute a workflow
      GET  /docs            — OpenAPI docs (FastAPI only)
      WS   /ws              — Workflow progress stream (FastAPI only)
    """
    if not legacy:
        try:
            from sccsos.api.fastapi_app import run_server as run_fastapi
            click.echo(f"Starting sccsos API server (FastAPI) on {host}:{port}")
            run_fastapi(host=host, port=port)
            return
        except ImportError as e:
            click.echo(
                "FastAPI not available. Install with:\n"
                f"  pip install \"sccsos[api] @ file://{Path(__file__).resolve().parent.parent.parent / 'dist' / 'sccsos-0.11.4-py3-none-any.whl'}\"\n"
                "Or from source:\n"
                "  pip install \"sccsos[api]\"\n"
                "Or install all extras in one step:\n"
                "  pip install \"sccsos[all]\"\n",
                err=True,
            )

    # Legacy server fallback
    if legacy:
        click.echo(
            "WARNING: --legacy mode is deprecated and will be removed in v0.12.0. "
            "Use 'pip install sccsos[api]' for the FastAPI server.",
            err=True,
        )
    from sccsos.api.server import run_server as run_legacy
    click.echo(f"Starting sccsos API server (legacy) on {host}:{port}")
    run_legacy(host=host, port=port)


# ── main entry point ──────────────────────────────────────────────


@click.group()
def main():
    """sccsos — Smart Agent Runtime Platform for SCCS-T Product Ecosystem."""
    pass


main.add_command(version)
main.add_command(init)
main.add_command(config)
main.add_command(agent)
main.add_command(workflow)
main.add_command(trace)
main.add_command(audit)
main.add_command(memory)
main.add_command(session)
main.add_command(personality)
main.add_command(skill)
main.add_command(quota)
main.add_command(billing)
main.add_command(benchmark)
main.add_command(plugin)
main.add_command(maintenance)
main.add_command(health)
main.add_command(doctor)
main.add_command(serve)
main.add_command(hermes_cmd)
main.add_command(role_cmd)


# ── template constants ────────────────────────────────────────────


_DEFAULT_YAML = """# sccsos v0.16.5 project configuration
project:
  name: sccsos
  version: 0.16.5
hermes:
  profile: sccsos
  binary: hermes
  home: ""                 # HERMES_HOME 覆盖（空值 = 使用环境变量或默认 ~/.hermes）
  code_path: ""            # HERMES_CODE_PATH 覆盖（空值 = 使用环境变量）
  adapter: subprocess
  setup:
    provider: deepseek
    model: deepseek-v4-flash
    api_key: ""
    base_url: "https://api.deepseek.com/v1"
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
pricing:
  path: ./config/pricing.json
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


if __name__ == "__main__":
    main()
