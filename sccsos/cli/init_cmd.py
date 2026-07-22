"""init command — initialize a new sccsos project."""

from __future__ import annotations

from pathlib import Path

import click

from sccsos.cli.sample_templates import (
    SAMPLE_FILES, SAMPLE_PRICING, SAMPLE_YAML_FULL,
)
from sccsos.cli.role_cmd import install_role_on_init


@click.command()
@click.option("--dir", "-d", default=".", help="Project directory (default: current)")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing files")
@click.option("--samples", "-s", is_flag=True, help="Generate sample agents, personalities, workflows")
@click.option("--interactive", "-i", is_flag=True, help="Interactive setup wizard")
@click.option("--role", "-r", default=None, help="Role package to install (architect, doc-writer, code-reviewer, ...)")
def init(dir, force, samples, interactive, role):
    """Initialize a new sccsos project in DIR.

    By default creates a minimal project with directory structure and
    a basic ``sccsos.yaml``.  Use ``--samples`` to also populate
    sample agents, personalities, and workflows.  Use ``--interactive``
    for guided database / admin / pricing setup.  Use ``--role``
    to install a role package (personalities, agents, workflows, and
    Hermes skills) in one step.
    """
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

    # Interactive setup wizard
    db_type = "sqlite"
    pg_dsn = ""
    admin_tenant = ""
    admin_name = ""
    pricing_tier = "free"

    if interactive:
        click.echo("")
        click.echo("─" * 48)
        click.echo("  SCCS OS 安装向导")
        click.echo("─" * 48)

        click.echo("")
        click.echo("[Step 1/3] 数据库配置")
        db_type = click.prompt(
            "  数据库类型",
            type=click.Choice(["sqlite", "postgresql"], case_sensitive=False),
            default="sqlite",
            show_choices=True,
        )
        if db_type == "postgresql":
            pg_dsn = click.prompt(
                "  PostgreSQL 连接字符串",
                default="postgresql://user:***@localhost:5432/sccsos",
            )
            click.echo(f"  ✓ PostgreSQL: {pg_dsn}")

        click.echo("")
        click.echo("[Step 2/3] 管理员账户（RBAC）")
        if click.confirm("  创建管理员账户?", default=True):
            admin_tenant = click.prompt("  租户 ID", default="default")
            admin_name = click.prompt("  管理员用户名", default="admin")
            admin_tenant = admin_tenant or "default"
            admin_name = admin_name or "admin"
            click.echo(f"  ✓ 管理员: {admin_name} @ {admin_tenant}")

        click.echo("")
        click.echo("[Step 3/3] 定价配置")
        pricing_tier = click.prompt(
            "  定价方案",
            type=click.Choice(["free", "pro", "enterprise", "custom"], case_sensitive=False),
            default="free",
            show_choices=True,
        )
        if pricing_tier == "custom":
            click.echo("  （请编辑 config/pricing.json 自定义定价）")
        click.echo("")
        click.echo("─" * 48)

    # ── sccsos.yaml ──
    cfg_path = target / "sccsos.yaml"
    if samples:
        yaml_content = SAMPLE_YAML_FULL
    else:
        from sccsos.cli import _DEFAULT_YAML as _dy
        yaml_content = _dy
    if not cfg_path.exists() or force:
        cfg_path.write_text(yaml_content, encoding="utf-8")
        click.echo(f"  Created: sccsos.yaml{' (full)' if samples else ''}")

    # Apply interactive settings
    if interactive and cfg_path.exists():
        import yaml as pyyaml
        try:
            with open(cfg_path) as f:
                cfg_data = pyyaml.safe_load(f) or {}
            changed = False
            if db_type == "postgresql" and pg_dsn:
                cfg_data.setdefault("database", {})
                cfg_data["database"]["type"] = "postgresql"
                cfg_data["database"]["dsn"] = pg_dsn
                cfg_data["database"]["path"] = ""
                changed = True
            if pricing_tier != "free":
                cfg_data.setdefault("pricing", {})
                cfg_data["pricing"]["tier"] = pricing_tier
                changed = True
            if changed:
                with open(cfg_path, "w") as f:
                    pyyaml.dump(cfg_data, f, default_flow_style=False, allow_unicode=True)
                click.echo("  Updated: sccsos.yaml (interactive settings)")
        except Exception as e:
            click.echo(f"  ⚠ Failed to apply interactive settings: {e}")

    # ── Sample agents ──
    sample_agent_dir = target / "agents"
    if samples:
        click.echo("  Generating sample files...")
        for rel_path, content in SAMPLE_FILES.items():
            fp = target / rel_path
            if not fp.exists() or force:
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(content.lstrip("\n"), encoding="utf-8")
                click.echo(f"    {rel_path}")
    else:
        # Create hermes-installer as the default agent
        installer = sample_agent_dir / "hermes-installer.yaml"
        if not installer.exists() or force:
            from sccsos.cli.sample_templates import SAMPLE_AGENT_HERMES_INSTALL
            installer.write_text(SAMPLE_AGENT_HERMES_INSTALL.lstrip("\n"), encoding="utf-8")
            click.echo(f"  Created: agents/hermes-installer.yaml")

    # ── Pricing ──
    pricing_path = target / "config" / "pricing.json"
    if not pricing_path.exists():
        pricing_path.write_text(SAMPLE_PRICING, encoding="utf-8")
        click.echo(f"  Created: config/pricing.json")

    # ── Admin user ──
    if interactive and admin_name and admin_tenant:
        admin_agent = sample_agent_dir / "admin.yaml"
        if not admin_agent.exists() or force:
            admin_yaml = f"""name: {admin_name}
version: 1.0
description: Admin user for RBAC management
tenant_id: {admin_tenant}
personality: default-admin
profile: sccsos
lifecycle:
  max_turns: 90
  timeout: 1800
auto_approve: true
"""
            admin_agent.write_text(admin_yaml.lstrip("\n"), encoding="utf-8")
            click.echo(f"  Created: agents/{admin_name}.yaml")

    # ── Role package ──
    if role:
        install_role_on_init(role, str(target))

    click.echo("")
    click.echo("sccsos project initialized.")
    if interactive:
        click.echo(f"  Mode:    interactive setup")
        click.echo(f"  DB:      {db_type}")
        click.echo(f"  Admin:   {admin_name or '(none)'} @ {admin_tenant or 'default'}")
        click.echo(f"  Pricing: {pricing_tier}")
    elif samples:
        click.echo(f"  {len(SAMPLE_FILES)} sample files created.")
        click.echo("  Try: sccsos agent list")
        click.echo("  Try: sccsos workflow run workflows/冒烟测试.yaml")
    else:
        click.echo("  Run with --samples to generate agent/workflow samples.")
        click.echo("  Run with --interactive for guided setup.")
        click.echo("  Try: sccsos agent list")
