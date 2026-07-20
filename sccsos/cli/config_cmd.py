"""config CLI commands — show, webhook management."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click
import yaml

from sccsos.core.config import WebhookEntry, WebhooksConfig, get_config, reload_config


# ── Helpers ─────────────────────────────────────────────────────────


def _get_config_path() -> Path:
    """Resolve the path to sccsos.yaml."""
    # Check common locations
    candidates = [
        Path.cwd() / "sccsos.yaml",
        Path.cwd() / ".." / "sccsos.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p.resolve()
    # Fall back to CWD
    return (Path.cwd() / "sccsos.yaml").resolve()


def _load_sccsos_yaml() -> dict:
    """Load sccsos.yaml as raw dict."""
    cfg_path = _get_config_path()
    if not cfg_path.exists():
        click.echo(f"Error: {cfg_path} not found. Run 'sccsos init' first.", err=True)
        sys.exit(1)
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_sccsos_yaml(data: dict) -> None:
    """Write sccsos.yaml from dict, preserving structure."""
    cfg_path = _get_config_path()
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    click.echo(f"  Updated: {cfg_path}")


def _format_webhook_endpoint(entry: WebhookEntry, index: int) -> str:
    """Format a single webhook endpoint for display."""
    events_str = ", ".join(entry.events)
    secret_str = f"secret=**** ({len(entry.secret)} chars)" if entry.secret else "no auth"
    return (
        f"  [{index}] {entry.url}\n"
        f"        Events: {events_str}\n"
        f"        Auth:   {secret_str}"
    )


# ── config show ────────────────────────────────────────────────────


@click.command("show")
@click.option("--webhooks", is_flag=True, help="Show webhook configuration only")
@click.option("--policies", is_flag=True, help="Show policy configuration only")
def config_show(webhooks: bool, policies: bool) -> None:
    """Display current sccsos configuration."""
    cfg = get_config()

    if webhooks:
        _show_webhooks(cfg.webhooks)
        return
    if policies:
        _show_policies(cfg)
        return

    # Full config tree
    click.echo(f"sccsos configuration ({_get_config_path()}):")
    click.echo("")
    click.echo(f"Project:")
    click.echo(f"  name:    {cfg.project.name}")
    click.echo(f"  version: {cfg.project.version}")
    click.echo("")
    click.echo(f"Database:")
    click.echo(f"  path: {cfg.database.path}")
    click.echo("")
    click.echo(f"Defaults:")
    click.echo(f"  hermes_profile: {cfg.defaults.hermes_profile}")
    click.echo(f"  max_turns:      {cfg.defaults.max_turns}")
    click.echo(f"  timeout:        {cfg.defaults.timeout}s")
    click.echo("")
    click.echo(f"Logging:")
    click.echo(f"  level:    {cfg.logging.level}")
    click.echo(f"  format:   {cfg.logging.format}")
    click.echo(f"  directory: {cfg.logging.directory}")
    click.echo(f"  retention: {cfg.logging.retention_days}d")
    click.echo("")
    click.echo(f"Tracing:")
    click.echo(f"  enabled:     {cfg.tracing.enabled}")
    click.echo(f"  export_path: {cfg.tracing.export_path}")
    click.echo("")
    click.echo(f"Pricing:")
    click.echo(f"  path: {cfg.pricing.path or '(built-in defaults)'}")
    click.echo("")
    click.echo(f"Agents:")
    click.echo(f"  path:        {cfg.agents.path}")
    click.echo(f"  wiki_path:   {cfg.agents.wiki_path or '(none)'}")
    click.echo(f"  personalities: {cfg.agents.personalities_path}")
    click.echo("")
    _show_webhooks(cfg.webhooks)
    click.echo("")
    _show_policies(cfg)


def _show_webhooks(wc: WebhooksConfig) -> None:
    """Print webhook configuration."""
    click.echo(f"Webhooks:")
    click.echo(f"  enabled: {wc.enabled}")
    if wc.endpoints:
        click.echo(f"  endpoints ({len(wc.endpoints)}):")
        for i, ep in enumerate(wc.endpoints):
            click.echo(f"    [{i}] {ep.url}")
            click.echo(f"          Events: {', '.join(ep.events)}")
            click.echo(f"          Secret: {'****' if ep.secret else '(none)'}")
    else:
        click.echo(f"  endpoints: (none)")


def _show_policies(cfg) -> None:
    """Print policy configuration."""
    p = cfg.policies.default
    click.echo(f"Policies:")
    click.echo(f"  default:")
    click.echo(f"    max_tokens_per_session: {p.max_tokens_per_session}")
    click.echo(f"    max_cost_usd:           ${p.max_cost_usd}")
    click.echo(f"    allowed_tools ({len(p.allowed_tools)}): {', '.join(p.allowed_tools[:5])}{'...' if len(p.allowed_tools) > 5 else ''}")
    click.echo(f"    blocked_tools:          {', '.join(p.blocked_tools) if p.blocked_tools else '(none)'}")
    if cfg.policies.named:
        click.echo(f"  named policies ({len(cfg.policies.named)}):")
        for name in cfg.policies.named:
            click.echo(f"    - {name}")


# ── config webhook group ───────────────────────────────────────────


@click.group()
def webhook() -> None:
    """Manage webhook endpoints."""
    pass


@webhook.command("list")
def webhook_list() -> None:
    """List all configured webhook endpoints."""
    cfg = get_config()
    if not cfg.webhooks.endpoints:
        click.echo("No webhook endpoints configured.")
        click.echo("Add one with: sccsos config webhook add <url>")
        return

    click.echo(f"Webhook endpoints ({len(cfg.webhooks.endpoints)}):")
    click.echo(f"  Enabled: {cfg.webhooks.enabled}")
    for i, ep in enumerate(cfg.webhooks.endpoints):
        click.echo("")
        click.echo(_format_webhook_endpoint(ep, i))


@webhook.command("add")
@click.argument("url")
@click.option("--events", "-e", default="completed,failed",
              help="Comma-separated events (default: completed,failed)")
@click.option("--secret", "-s", default="",
              help="HMAC secret for request signing")
@click.option("--enable", is_flag=True, default=False,
              help="Also enable webhooks globally (webhooks.enabled=true)")
def webhook_add(url: str, events: str, secret: str, enable: bool) -> None:
    """Add a webhook endpoint.

    URL is the HTTP/HTTPS endpoint that receives POST callbacks.
    """
    data = _load_sccsos_yaml()
    wh = data.setdefault("webhooks", {})
    endpoints = wh.setdefault("endpoints", [])

    # Check for duplicate URL
    for ep in endpoints:
        if isinstance(ep, dict) and ep.get("url") == url:
            click.echo(f"Error: endpoint '{url}' already exists.", err=True)
            sys.exit(1)

    event_list = [e.strip() for e in events.split(",") if e.strip()]
    entry = {"url": url, "events": event_list}
    if secret:
        entry["secret"] = secret
    endpoints.append(entry)

    if enable:
        wh["enabled"] = True

    _save_sccsos_yaml(data)
    reload_config()
    click.echo(f"Webhook endpoint added:")
    click.echo(f"  URL:    {url}")
    click.echo(f"  Events: {', '.join(event_list)}")
    click.echo(f"  Secret: {'****' if secret else '(none)'}")
    if enable:
        click.echo(f"  Webhooks globally enabled.")


@webhook.command("remove")
@click.argument("target")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def webhook_remove(target: str, yes: bool) -> None:
    """Remove a webhook endpoint by URL or index.

    TARGET can be a full URL or a numeric index (from 'config webhook list').
    """
    data = _load_sccsos_yaml()
    endpoints = data.get("webhooks", {}).get("endpoints", [])

    # Try index first, then URL match
    idx: Optional[int] = None
    try:
        idx = int(target)
    except ValueError:
        for i, ep in enumerate(endpoints):
            if isinstance(ep, dict) and ep.get("url") == target:
                idx = i
                break

    if idx is None or idx < 0 or idx >= len(endpoints):
        click.echo(f"Error: endpoint '{target}' not found.", err=True)
        click.echo("Use 'sccsos config webhook list' to see available endpoints.")
        sys.exit(1)

    removed = endpoints[idx]
    url = removed.get("url", target)

    if not yes:
        click.confirm(f"Remove webhook endpoint '{url}'?", abort=True)

    endpoints.pop(idx)
    data["webhooks"]["endpoints"] = endpoints
    _save_sccsos_yaml(data)
    reload_config()
    click.echo(f"Removed webhook endpoint: {url}")


@webhook.command("test")
@click.argument("target", required=False, default=None)
def webhook_test(target: Optional[str]) -> None:
    """Send a test event to a webhook endpoint.

    TARGET can be a URL or index (from 'config webhook list').
    If omitted, sends to all configured endpoints.
    """
    cfg = get_config()
    endpoints = cfg.webhooks.endpoints

    if target:
        try:
            idx = int(target)
            endpoints = [endpoints[idx]]
        except (ValueError, IndexError):
            endpoints = [ep for ep in endpoints if ep.url == target]
            if not endpoints:
                click.echo(f"Error: endpoint '{target}' not found.", err=True)
                sys.exit(1)

    if not endpoints:
        click.echo("No webhook endpoints configured.", err=True)
        sys.exit(1)

    from sccsos.observability.webhook import WebhookNotifier

    notifier = WebhookNotifier(cfg.webhooks)
    test_urls = [ep.url for ep in endpoints]

    click.echo(f"Sending test event to {len(endpoints)} endpoint(s)...")
    for url in test_urls:
        click.echo(f"  → {url}")

    notifier.fire(
        event="test",
        run_id="test_manual",
        workflow_name="CLI test",
        status="test",
    )
    click.echo("Test event sent (check endpoint for delivery).")
