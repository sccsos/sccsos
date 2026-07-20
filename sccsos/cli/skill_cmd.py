"""Skill review CLI commands.

Usage:
    sccsos skill review list
    sccsos skill review submit <name>
    sccsos skill review approve <name>
    sccsos skill review reject <name> <reason>
    sccsos skill review validate <name>
"""

from __future__ import annotations

from pathlib import Path

import click

from sccsos.core.agent_runtime import get_runtime as _get_runtime


@click.group()
def skill():
    """Manage skills and the review pipeline."""
    pass


@skill.group()
def review():
    """Review workflow for skill submissions."""
    pass


@review.command("list")
@click.option("--status", "-s", default="pending_review",
              type=click.Choice(["draft", "pending_review", "approved", "rejected", "all"]),
              help="Filter by status (default: pending_review)")
def review_list(status):
    """List skills in the review pipeline."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)

    if status == "all":
        items = mgr.list_all()
    else:
        items = mgr.list_all(status=status)

    if not items:
        click.echo(f"No skills in status '{status}'.")
        return

    click.echo(f"Skills ({status}):")
    for item in items:
        status_icon = {
            "draft": "📝", "pending_review": "🔍",
            "approved": "✅", "rejected": "❌",
        }.get(item.status, "❓")
        click.echo(f"  {status_icon} {item.name} v{item.version}")
        click.echo(f"     Type: {item.type} | Author: {item.author}")
        click.echo(f"     Desc: {item.description or '(no description)'}")
        if item.review_notes:
            click.echo(f"     Notes: {item.review_notes}")
        click.echo("")


@review.command("submit")
@click.argument("name")
@click.option("--version", "-v", default="1.0", help="Skill version (default: 1.0)")
def review_submit(name, version):
    """Submit a skill for review (draft → pending_review)."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)

    if mgr.submit_for_review(name, version):
        click.echo(f"✅ Skill '{name}' v{version} submitted for review.")
    else:
        click.echo(f"⚠️  Could not submit '{name}' v{version}. Check name/version and current status.")


@review.command("approve")
@click.argument("name")
@click.option("--version", "-v", default="1.0", help="Skill version (default: 1.0)")
@click.option("--reviewer", "-r", default="", help="Reviewer name")
@click.option("--notes", "-n", default="", help="Approval notes")
def review_approve(name, version, reviewer, notes):
    """Approve a skill (pending_review → approved). Auto-validates first."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)

    # Show validation before approving
    validation = mgr.validate(name, version)
    if not validation.valid:
        click.echo(f"❌ Validation failed for '{name}':")
        for err in validation.errors:
            click.echo(f"   - {err}")
        click.echo("Fix the errors and try again.")
        return
    if validation.warnings:
        click.echo("⚠️  Warnings:")
        for w in validation.warnings:
            click.echo(f"   - {w}")

    if mgr.approve(name, version, reviewer=reviewer, notes=notes):
        click.echo(f"✅ Skill '{name}' v{version} approved.")
    else:
        click.echo(f"❌ Could not approve '{name}'. Check name/version.")


@review.command("reject")
@click.argument("name")
@click.argument("reason")
@click.option("--version", "-v", default="1.0", help="Skill version (default: 1.0)")
def review_reject(name, reason, version):
    """Reject a skill with a reason.

    Example:
        sccsos skill review reject my-agent "Missing system_prompt field"
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)

    if mgr.reject(name, version, reason=reason):
        click.echo(f"✅ Skill '{name}' v{version} rejected: {reason}")
    else:
        click.echo(f"❌ Could not reject '{name}'. A reason is required.")


@review.command("validate")
@click.argument("name")
@click.option("--version", "-v", default="1.0", help="Skill version (default: 1.0)")
def review_validate(name, version):
    """Validate a skill's content for safety and completeness.

    Checks YAML syntax, required fields, and prompt injection patterns.
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)

    result = mgr.validate(name, version)
    click.echo(f"Validation result for '{name}' v{version}:")
    if result.valid:
        click.echo(f"  ✅ Valid")
    else:
        click.echo(f"  ❌ Invalid")
    for err in result.errors:
        click.echo(f"     Error: {err}")
    for w in result.warnings:
        click.echo(f"     ⚠️  {w}")

    if result.valid and not result.warnings:
        click.echo("  No issues found.")


# ── skill clean ────────────────────────────────────────────────────


@skill.command("clean")
@click.option("--keep", "-k", default=5,
              help="Keep N most recent versions per skill (default: 5)")
@click.option("--days", "-d", default=30,
              help="Remove rejected/draft entries older than N days (default: 30)")
@click.option("--dry-run", is_flag=True,
              help="Show what would be cleaned without deleting")
def skill_clean(keep, days, dry_run):
    """Clean stale skill market entries and old versions.

    Removes:
    - Rejected skills older than N days
    - Draft skills older than N days (abandoned submissions)
    - Old personality versions beyond the keep limit

    Use ``--dry-run`` to preview before deleting.
    """
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    total_removed = 0

    # ── 1. Rejected skills older than N days ──────────────────
    rows = runtime.db.fetchall(
        "SELECT name, version, created_at FROM skill_market "
        "WHERE status = 'rejected' AND updated_at < ?",
        (cutoff.isoformat(),),
    )
    for row in rows:
        if dry_run:
            click.echo(f"  [dry-run] Would delete rejected: {row['name']} v{row['version']} ({row['created_at']})")
        else:
            runtime.db.execute(
                "DELETE FROM skill_market WHERE name = ? AND version = ?",
                (row['name'], row['version']),
            )
            click.echo(f"  Deleted rejected: {row['name']} v{row['version']}")
        total_removed += 1

    # ── 2. Draft skills older than N days ─────────────────────
    rows = runtime.db.fetchall(
        "SELECT name, version, created_at FROM skill_market "
        "WHERE status = 'draft' AND updated_at < ?",
        (cutoff.isoformat(),),
    )
    for row in rows:
        if dry_run:
            click.echo(f"  [dry-run] Would delete stale draft: {row['name']} v{row['version']} ({row['created_at']})")
        else:
            runtime.db.execute(
                "DELETE FROM skill_market WHERE name = ? AND version = ?",
                (row['name'], row['version']),
            )
            click.echo(f"  Deleted stale draft: {row['name']} v{row['version']}")
        total_removed += 1

    # ── 3. Old personality versions (delegate to existing) ─────
    from sccsos.core.personality_version import PersonalityVersionManager
    p_mgr = PersonalityVersionManager(runtime.db)
    p_names = p_mgr.list_all_personalities()
    for p_name in p_names:
        versions = p_mgr.list_versions(p_name)
        if len(versions) <= keep:
            continue
        surplus = versions[keep:]
        for pv in surplus:
            if dry_run:
                click.echo(f"  [dry-run] Would delete personality version: {p_name} v{pv.version} ({pv.created_at})")
            else:
                p_mgr.delete_version(p_name, pv.version)
                click.echo(f"  Deleted {p_name} v{pv.version}")
            total_removed += 1

    # ── 4. Orphaned installed_skills ───────────────────────────
    orphaned = runtime.db.fetchall(
        "SELECT i.name, i.version FROM installed_skills i "
        "LEFT JOIN skill_market s ON i.name = s.name "
        "WHERE s.name IS NULL"
    )
    for row in orphaned:
        if dry_run:
            click.echo(f"  [dry-run] Would remove orphaned installed: {row['name']} v{row['version']}")
        else:
            runtime.db.execute(
                "DELETE FROM installed_skills WHERE name = ? AND version = ?",
                (row['name'], row['version']),
            )
            click.echo(f"  Removed orphaned installed: {row['name']} v{row['version']}")
        total_removed += 1

    runtime.db.commit()

    if total_removed == 0:
        click.echo("Nothing to clean.")
    else:
        click.echo(f"Cleaned {total_removed} item(s).")
        if dry_run:
            click.echo("Run without --dry-run to apply.")


@skill.command("verify")
def skill_verify():
    """Verify all published/approved skills for YAML validity."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.skill_market import SkillMarket
    market = SkillMarket(runtime.db)
    result = market.verify_all()

    click.echo(f"Skill 验证结果:")
    click.echo(f"  总数: {result['total']}")
    click.echo(f"  有效: {result['valid']}")
    click.echo(f"  无效: {result['invalid']}")
    if result["issues"]:
        click.echo("\n问题列表:")
        for issue in result["issues"]:
            click.echo(f"  ❌ {issue['name']} v{issue['version']}: {issue['issue']}")


# ── skill market ───────────────────────────────────────────────────


@skill.group()
def market():
    """Skill marketplace — list, install, publish skills."""
    pass


@market.command("list")
@click.option("--status", "-s", default="approved",
              type=click.Choice(["approved", "draft", "pending_review", "rejected", "all"]),
              help="Filter by status (default: approved)")
def market_list(status):
    """List available skills in the marketplace."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)

    if status == "all":
        items = mgr.list_all()
    else:
        items = mgr.list_all(status=status)

    if not items:
        click.echo(f"No skills found (status: {status}).")
        return

    click.echo(f"Skill Marketplace ({status}):")
    click.echo(f"{'Name':<20} {'Version':<8} {'Type':<14} {'Author':<16} {'Status':<14}")
    click.echo("-" * 72)
    for item in items:
        status_icon = {
            "draft": "📝", "pending_review": "🔍",
            "approved": "✅", "rejected": "❌",
        }.get(item.status, " ")
        click.echo(
            f"{status_icon} {item.name:<18} {item.version:<8} "
            f"{item.type:<14} {item.author:<16} {item.status:<14}"
        )


@market.command("show")
@click.argument("name")
@click.option("--version", "-v", default="latest", help="Version (default: latest)")
def market_show(name, version):
    """Show skill details from the marketplace."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)

    if version == "latest":
        # Get all versions, show latest approved
        items = mgr.list_all(status="approved")
        items = [i for i in items if i.name == name]
        if not items:
            click.echo(f"Skill '{name}' not found in approved skills.")
            return
        item = items[0]
    else:
        item = mgr.get_review(name, version)
        if not item:
            click.echo(f"Skill '{name}' v{version} not found.")
            return

    click.echo(f"Skill: {item.name} v{item.version}")
    click.echo(f"  Type:        {item.type}")
    click.echo(f"  Author:      {item.author}")
    click.echo(f"  Status:      {item.status}")
    click.echo(f"  Description: {item.description or '(none)'}")
    click.echo(f"  Tags:        {', '.join(item.tags) if item.tags else '(none)'}")
    click.echo(f"  Filename:    {item.filename or '(none)'}")
    if item.review_notes:
        click.echo(f"  Notes:       {item.review_notes}")
    click.echo(f"  Created:     {item.created_at}")
    click.echo(f"  Updated:     {item.updated_at}")


@market.command("install")
@click.argument("name")
@click.option("--version", "-v", default="latest", help="Version (default: latest)")
def market_install(name, version):
    """Install an approved skill from the marketplace."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)

    # Find the skill
    if version == "latest":
        items = mgr.list_all(status="approved")
        items = [i for i in items if i.name == name]
        if not items:
            click.echo(f"No approved skill '{name}' found.")
            return
        item = items[0]
        ver = item.version
    else:
        item = mgr.get_review(name, version)
        if not item:
            click.echo(f"Skill '{name}' v{version} not found.")
            return
        if item.status != "approved":
            click.echo(f"Skill '{name}' is '{item.status}', not approved. Approve it first.")
            return
        ver = version

    # Install: write to personalities dir
    personalities_dir = runtime.config.agents.personalities_path
    target_path = Path(personalities_dir) / item.filename if item.filename \
        else Path(personalities_dir) / f"{name}.yaml"

    if not target_path.parent.exists():
        target_path.parent.mkdir(parents=True, exist_ok=True)

    target_path.write_text(item.content or "", encoding="utf-8")
    click.echo(f"✅ Installed '{name}' v{ver} → {target_path}")

    # Record as installed
    runtime.db.execute(
        "INSERT OR IGNORE INTO installed_skills (name, version, type) "
        "VALUES (?, ?, ?)",
        (name, ver, item.type),
    )
    runtime.db.commit()


@market.command("uninstall")
@click.argument("name")
def market_uninstall(name):
    """Uninstall a skill (removes file + record)."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    from sccsos.core.skill_review import SkillReviewManager
    mgr = SkillReviewManager(runtime.db)

    # Check if installed
    row = runtime.db.fetchone(
        "SELECT * FROM installed_skills WHERE name = ?", (name,)
    )
    if not row:
        click.echo(f"Skill '{name}' is not installed.")
        return

    # Remove file
    personalities_dir = runtime.config.agents.personalities_path
    for ext in (".yaml", ".yml", ""):
        fpath = Path(personalities_dir) / f"{name}{ext}"
        if fpath.exists():
            fpath.unlink()
            click.echo(f"  Removed file: {fpath}")
            break

    # Remove from installed
    runtime.db.execute(
        "DELETE FROM installed_skills WHERE name = ?", (name,)
    )
    runtime.db.commit()
    click.echo(f"✅ Uninstalled '{name}'.")


@market.command("publish")
@click.argument("name")
@click.option("--type", "-t", "skill_type", default="personality",
              help="Skill type (default: personality)")
@click.option("--description", "-d", default="", help="Short description")
@click.option("--author", "-a", default="", help="Author name")
@click.option("--tags", default="", help="Comma-separated tags")
def market_publish(name, skill_type, description, author, tags):
    """Publish a local personality file as a marketplace listing."""
    runtime = _get_runtime()
    if not runtime.initialize():
        click.echo("Not initialized.")
        return

    import json
    from datetime import datetime, timezone

    # Read from personalities dir
    personalities_dir = Path(runtime.config.agents.personalities_path)
    content = None
    filename = None
    for ext in (f"{name}.yaml", f"{name}.yml", name):
        fpath = personalities_dir / ext
        if fpath.exists() and fpath.is_file():
            content = fpath.read_text(encoding="utf-8")
            filename = fpath.name
            break

    if not content:
        click.echo(f"Personality file '{name}' not found in {personalities_dir}")
        return

    # Validate YAML
    import yaml
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as e:
        click.echo(f"❌ YAML validation failed: {e}")
        return

    # Check if already exists
    existing = runtime.db.fetchone(
        "SELECT version FROM skill_market WHERE name = ? ORDER BY created_at DESC LIMIT 1",
        (name,),
    )
    if existing:
        # Bump version
        try:
            ver_num = float(existing["version"]) + 0.1
            version = f"{ver_num:.1f}"
        except (ValueError, TypeError):
            version = "1.1"
        click.echo(f"Updating existing listing: v{existing['version']} → v{version}")
    else:
        version = "1.0"

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    now = datetime.now(timezone.utc).isoformat()
    runtime.db.execute(
        """INSERT INTO skill_market
           (name, version, type, description, author, tags, filename, content, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending_review', ?, ?)""",
        (name, version, skill_type, description, author,
         json.dumps(tag_list), filename or f"{name}.yaml", content, now, now),
    )
    runtime.db.commit()
    click.echo(f"✅ Published '{name}' v{version} as '{skill_type}' (pending review).")
    click.echo(f"   Run: sccsos skill review list")
    click.echo(f"   Run: sccsos skill review approve {name}")
