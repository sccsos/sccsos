"""sccsos CLI — main entry point, top-level commands, group wiring."""

from __future__ import annotations

from pathlib import Path

import click

from sccsos.core.agent_runtime import get_runtime as _get_runtime
from sccsos.core.config import get_config
from sccsos.cli.agent_cmd import agent
from sccsos.cli.workflow_cmd import workflow
from sccsos.cli.system_cmd import trace, audit, memory, session, personality


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

    dirs = [
        target / "data",
        target / "logs",
        target / "traces",
        target / "agents",
        target / "workflows",
        target / "personalities",
        target / "wiki",
        target / "config",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    cfg_path = target / "sccsos.yaml"
    if not cfg_path.exists() or force:
        cfg_path.write_text(_DEFAULT_YAML, encoding="utf-8")
        click.echo(f"  Created: sccsos.yaml")

    sample = target / "agents" / "architect.yaml"
    if not sample.exists() or force:
        sample.write_text(_SAMPLE_AGENT, encoding="utf-8")
        click.echo(f"  Created: agents/architect.yaml")

    # Optional pricing configuration (only created if missing)
    pricing_path = target / "config" / "pricing.json"
    if not pricing_path.exists():
        pricing_path.write_text(_SAMPLE_PRICING, encoding="utf-8")
        click.echo(f"  Created: config/pricing.json")

    click.echo("\nsccsos project initialized.")
    click.echo("Run: sccsos agent list")


# ── config ─────────────────────────────────────────────────────────


@click.group()
def config():
    """Manage sccsos configuration."""
    pass


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
@click.option("--legacy", is_flag=True, help="Use legacy http.server instead of FastAPI")
def serve(port, host, legacy):
    """Start the sccsos HTTP API server.

    By default uses the FastAPI server (requires ``pip install sccsos[api]``).
    Falls back to the legacy ``http.server`` implementation if FastAPI is
    not available, or if ``--legacy`` is specified.

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
        except ImportError:
            click.echo(
                "FastAPI not available. Install with: pip install sccsos[api]\n"
                "Falling back to legacy server..."
            )

    # Legacy server fallback
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
main.add_command(health)
main.add_command(serve)


# ── template constants ────────────────────────────────────────────


_DEFAULT_YAML = """# sccsos v0.9.0 project configuration
project:
  name: sccsos
  version: 0.9.0
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

_SAMPLE_PRICING = """{
  "version": 1,
  "updated": "2026-07-18",
  "description": "LLM model pricing per 1M tokens (USD). [input_price, output_price].",
  "default_input_price": 0.50,
  "default_output_price": 2.00,
  "models": {
    "deepseek-v4-flash":       [0.14, 0.28],
    "deepseek-v4-pro":         [0.44, 0.87],
    "deepseek-chat":           [0.14, 0.28],
    "deepseek-reasoner":       [0.55, 2.19],
    "gpt-4o":                 [2.50, 10.00],
    "gpt-4o-mini":            [0.15, 0.60],
    "claude-sonnet-4":        [3.00, 15.00],
    "claude-haiku-3.5":       [0.80, 4.00],
    "gemini-2.5-flash":        [0.30, 2.50],
    "gemini-2.5-pro":         [1.25, 10.00]
  }
}
"""


if __name__ == "__main__":
    main()
