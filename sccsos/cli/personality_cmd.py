""""Personality CLI commands.

Extracted from system_cmd.py.
"""

from __future__ import annotations
from pathlib import Path
import click
from sccsos.core.agent_runtime import get_runtime as _get_runtime



@click.group()
def personality():
    """Manage personality version history."""
    pass


@personality.command("list")
def personality_list():
    """List all personalities with version history."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return
    from sccsos.core.personality_version import PersonalityVersionManager
    mgr = PersonalityVersionManager(runtime.db)
    names = mgr.list_all_personalities()
    if not names:
        click.echo("No personality versions found.")
        return
    click.echo("Personalities with version history:")
    for name in names:
        versions = mgr.list_versions(name)
        click.echo(f"  {name}: {len(versions)} version(s) (latest: {versions[0].version})")


@personality.command()
@click.argument("name")
@click.argument("change_log", default="")
def save(name, change_log):
    """Snapshot the current personality file as a new version.
    
    Usage:
        sccsos personality save agent-architect "Updated system prompt"
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return
    from sccsos.core.personality_version import PersonalityVersionManager
    personalities_dir = runtime.config.agents.personalities_path
    mgr = PersonalityVersionManager(runtime.db, personalities_dir)
    try:
        version = mgr.save_version(name, change_log=change_log)
        click.echo(f"Saved version {version} for personality '{name}'")
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)


@personality.command("show")
@click.argument("name")
@click.option("--version", "-v", "ver", default="", help="Specific version (default: latest)")
def personality_show(name, ver):
    """Show a personality version's content.
    
    Usage:
        sccsos personality show agent-architect
        sccsos personality show agent-architect --version 1.0
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return
    from sccsos.core.personality_version import PersonalityVersionManager
    mgr = PersonalityVersionManager(runtime.db)

    if ver:
        pv = mgr.get_version(name, ver)
    else:
        versions = mgr.list_versions(name)
        if not versions:
            click.echo(f"No versions found for '{name}'")
            return
        pv = versions[0]

    if pv is None:
        click.echo(f"Version '{ver or 'latest'}' not found for '{name}'")
        return

    click.echo(f"Personality: {pv.personality_name} v{pv.version}")
    click.echo(f"  Created: {pv.created_at}")
    click.echo(f"  Change:  {pv.change_log}")
    click.echo("---")
    click.echo(pv.content)


@personality.command()
@click.argument("name")
@click.argument("version")
def rollback(name, version):
    """Rollback a personality to a previous version.
    
    Restores the YAML file content from the specified version.
    The current content is auto-saved as a new version before rollback.
    
    Usage:
        sccsos personality rollback agent-architect 1.0
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return
    from sccsos.core.personality_version import PersonalityVersionManager
    personalities_dir = runtime.config.agents.personalities_path
    mgr = PersonalityVersionManager(runtime.db, personalities_dir)

    pv = mgr.get_version(name, version)
    if pv is None:
        click.echo(f"Version '{version}' not found for '{name}'")
        return

    # Auto-save current before rollback
    try:
        mgr.save_version(name, change_log=f"Auto-save before rollback to v{version}")
    except FileNotFoundError:
        click.echo(f"Warning: could not save current version (file not found)", err=True)

    # Write the version content to disk
    target = Path(personalities_dir) / f"{name}.yaml"
    if not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(pv.content, encoding="utf-8")
    click.echo(f"Rolled back '{name}' to version {version}")
    click.echo(f"  File: {target}")
    click.echo(f"  Change: {pv.change_log}")


# ── personality validate ───────────────────────────────────────────


@personality.command("validate")
@click.option("--name", "-n", default=None, help="Validate a specific personality (default: all)")
def personality_validate(name):
    """Validate personality files — check YAML syntax and loadability.

    Scans the personalities directory, parses each YAML file, and
    reports any errors found.
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    personalities_dir = Path(runtime.config.agents.personalities_path)
    if not personalities_dir.exists():
        click.echo(f"Personalities directory not found: {personalities_dir}")
        return

    if name:
        files = [personalities_dir / f"{name}.yaml"]
    else:
        files = sorted(personalities_dir.glob("*.yaml"))

    if not files:
        click.echo("No personality files found.")
        return

    import yaml

    ok_count = 0
    fail_count = 0
    click.echo(f"Validating {len(files)} personality file(s)...")
    for fp in files:
        try:
            content = fp.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if not isinstance(data, dict):
                click.echo(f"  ⚠️  {fp.name}: not a valid YAML mapping")
                fail_count += 1
                continue
            if "name" not in data:
                click.echo(f"  ⚠️  {fp.name}: missing 'name' field")
                fail_count += 1
                continue
            if "system_prompt" not in data:
                click.echo(f"  ⚠️  {fp.name}: missing 'system_prompt' field")
                fail_count += 1
                continue
            click.echo(f"  ✅  {fp.name}: {data.get('name')} (v{data.get('model', '?')})")
            ok_count += 1
        except yaml.YAMLError as e:
            click.echo(f"  ❌  {fp.name}: YAML parse error — {e}")
            fail_count += 1
        except Exception as e:
            click.echo(f"  ❌  {fp.name}: {e}")
            fail_count += 1

    click.echo("")
    click.echo(f"Result: {ok_count} valid, {fail_count} failed")
    if fail_count > 0:
        raise click.ClickException(f"{fail_count} personality file(s) failed validation")


# ── personality clean ──────────────────────────────────────────────


@personality.command("clean")
@click.option("--keep", "-k", default=5, help="Keep N most recent versions (default: 5)")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted without deleting")
def personality_clean(keep, dry_run):
    """Clean old personality versions beyond the keep limit.

    Removes surplus version snapshots from the database, keeping only
    the N most recent versions for each personality.
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.core.personality_version import PersonalityVersionManager
    mgr = PersonalityVersionManager(runtime.db)

    names = mgr.list_all_personalities()
    total_removed = 0
    click.echo(f"Cleaning personality versions (keeping {keep} per personality)...")

    for name in names:
        versions = mgr.list_versions(name)
        if len(versions) <= keep:
            continue

        surplus = versions[keep:]  # Oldest beyond keep
        for pv in surplus:
            if dry_run:
                click.echo(f"  [dry-run] Would delete {name} v{pv.version} ({pv.created_at})")
            else:
                mgr.delete_version(name, pv.version)
                click.echo(f"  Deleted {name} v{pv.version} ({pv.created_at})")
            total_removed += 1

    if total_removed == 0:
        click.echo("No surplus versions to clean.")
    else:
        click.echo(f"Cleaned {total_removed} version(s).")
        if not dry_run:
            click.echo("Run 'sccsos personality list' to verify.")
