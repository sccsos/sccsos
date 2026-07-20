"""sccsos CLI — plugin management commands."""

from __future__ import annotations

import click

from sccsos.plugin import get_registry


@click.group()
def plugin():
    """Manage plugins."""
    pass


@plugin.command("list")
def plugin_list():
    """List registered plugins."""
    registry = get_registry()
    plugins = registry.list()
    if not plugins:
        click.echo("No plugins registered.")
        return

    click.echo(f"{'Name':<24} {'Version':<10} {'Hooks':<30} {'Description'}")
    click.echo("-" * 90)
    for p in plugins:
        hooks_str = ", ".join(p["hooks"]) if p["hooks"] else "-"
        click.echo(f"{p['name']:<24} {p['version']:<10} {hooks_str:<30} {p['description'][:40]}")
    click.echo(f"\nTotal: {len(plugins)} plugin(s)")


@plugin.command("info")
@click.argument("name")
def plugin_info(name: str):
    """Show details for a specific plugin."""
    registry = get_registry()
    plugin_obj = registry.get(name)
    if plugin_obj is None:
        click.echo(f"Plugin '{name}' not found.")
        return

    click.echo(f"Name:        {plugin_obj.name}")
    click.echo(f"Version:     {plugin_obj.version}")
    click.echo(f"Description: {plugin_obj.description}")
    click.echo(f"Hooks:       {', '.join(plugin_obj.get_hooks().keys()) or '-'}")
