"""CLI commands for role package management.

Provides ``sccsos role`` subcommands for listing available role
packages, viewing role details, and installing roles.

Also extends ``sccsos init`` with ``--role`` option via the
:func:`install_role_on_init` helper.
"""

from __future__ import annotations

import click

from sccsos.roles import get_registry
from sccsos.roles.installer import RolePackageInstaller


@click.group(name="role")
def role_cmd() -> None:
    """Manage SCCS OS role packages.

    Roles bundle Hermes skills, SCCS OS personalities, agents,
    and workflows for one-step setup.
    """


@role_cmd.command(name="list")
def list_roles() -> None:
    """List all available role packages."""
    roles = RolePackageInstaller.discover_roles()

    if not roles:
        click.echo("没有可用角色包。")
        return

    click.echo(f"可用角色包 ({len(roles)}):")
    click.echo("")
    for r in roles:
        click.echo(f"  {r['name']}")
        click.echo(f"    描述: {r['description']}")
        click.echo(f"    模型: {r['model']}")
        click.echo(f"    技能: {r['skills']} 个")
        click.echo(f"    配置文件: {r['files']} 个")
        click.echo("")


@role_cmd.command(name="info")
@click.argument("name", required=True)
def role_info(name: str) -> None:
    """Show detailed information about a role package."""
    info = RolePackageInstaller.get_role_info(name)

    if not info:
        click.echo(f"❌ 角色包 '{name}' 不存在。")
        click.echo("运行 'sccsos role list' 查看可用角色。")
        return

    click.echo(f"── 角色包: {info['name']} ──")
    click.echo(f"  描述:           {info['description']}")
    click.echo(f"  推荐模型:       {info['hermes_profile']['model']}")
    click.echo(f"  推荐温度:       {info['hermes_profile']['temperature']}")
    click.echo("")

    if info['skills']:
        click.echo("  Hermes 技能:")
        for s in info['skills']:
            click.echo(f"    - {s}")
    else:
        click.echo("  Hermes 技能: (无)")

    click.echo("")
    if info['personalities']:
        click.echo(f"  SCCS OS 人格: {', '.join(info['personalities'])}")
    if info['agents']:
        click.echo(f"  SCCS OS Agent: {', '.join(info['agents'])}")
    if info['workflows']:
        click.echo(f"  SCCS OS 工作流: {', '.join(info['workflows'])}")

    click.echo("")
    click.echo(f"  安装: sccsos role install {info['name']}")


@role_cmd.command(name="install")
@click.argument("name", required=True)
@click.option("--project", "-p", default=".",
              help="Project root directory (default: current dir)")
def role_install(name: str, project: str) -> None:
    """Install a role package into the current project."""
    from sccsos.roles import get_registry

    role = get_registry().get_role(name)
    if not role:
        click.echo(f"❌ 角色包 '{name}' 不存在。")
        click.echo("运行 'sccsos role list' 查看可用角色。")
        return

    click.echo(f"正在安装角色包: {role.name}")
    click.echo(f"  描述: {role.description}")
    click.echo("")

    installer = RolePackageInstaller(project_root=project)
    report = installer.install(role)

    click.echo(f"  Hermes 技能验证:   {report.skills_verified} / {len(role.skills.hermes)}")
    click.echo(f"  人格文件安装:      {report.personalities_installed}")
    click.echo(f"  Agent 文件安装:    {report.agents_installed}")
    click.echo(f"  工作流文件安装:    {report.workflows_installed}")
    click.echo("")

    if not report.errors:
        click.echo(f"🎉 角色包 '{role.name}' 安装完成！")
        click.echo("")
        click.echo("后续步骤:")
        click.echo(f"  sccsos agent create {role.name}    # 创建 Agent")
        click.echo(f"  sccsos agent start {role.name}     # 启动 Agent")
    else:
        for e in report.errors:
            click.echo(f"  ⚠️  {e}")
        if report.success:
            click.echo(f"🎉 角色包 '{role.name}' 安装完成（有警告）")
        else:
            click.echo(f"❌ 角色包安装出现错误，请检查以上信息。")


# ── Helper for sccsos init --role ────────────────────────────────────


def install_role_on_init(role_name: str, project_root: str) -> None:
    """Install a role package during ``sccsos init``.

    Called by the init command when ``--role <name>`` is passed.
    Prints progress to stdout.
    """
    from sccsos.roles import get_registry

    role = get_registry().get_role(role_name)
    if not role:
        click.echo(f"⚠️  角色包 '{role_name}' 不存在，跳过角色安装。", err=True)
        click.echo("运行 'sccsos role list' 查看可用角色。", err=True)
        return

    click.echo(f"\\n正在安装角色包: {role.description}...")

    installer = RolePackageInstaller(project_root=project_root)
    report = installer.install(role)

    click.echo(f"  Hermes 技能验证: {report.skills_verified}")
    click.echo(f"  SCCS OS 文件: {report.personalities_installed + report.agents_installed + report.workflows_installed} 个")

    if report.success:
        click.echo(f"✅ 角色 '{role_name}' 安装完成")
    else:
        for e in report.errors:
            click.echo(f"  ⚠️  {e}")
