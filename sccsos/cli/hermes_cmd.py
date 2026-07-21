"""CLI commands for Hermes Agent management.

Provides ``sccsos hermes`` subcommands for one-click Hermes Agent
setup, configuration display, and connectivity checks.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Optional

import click

from sccsos.observability.logger import get_logger

logger = get_logger()


# ── Helpers ─────────────────────────────────────────────────────────


def _run_hermes(args: list[str], timeout: int = 30) -> tuple[str, str, int]:
    """Run a hermes CLI command and return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(
            ["hermes", *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        return "", "hermes CLI not found. Install with: pip install hermes-agent", -1
    except subprocess.TimeoutExpired:
        return "", f"hermes command timed out after {timeout}s", -1


def _check_hermes_installed() -> bool:
    """Check if Hermes CLI is available."""
    out, err, rc = _run_hermes(["--version"])
    return rc == 0


def _list_profiles() -> list[str]:
    """List available Hermes profiles."""
    out, _, rc = _run_hermes(["config", "list-profiles"])
    if rc != 0 or not out:
        return []
    return [p.strip() for p in out.splitlines() if p.strip()]


def _profile_exists(name: str) -> bool:
    """Check if a Hermes profile exists."""
    return name in _list_profiles()


def _create_profile(name: str) -> bool:
    """Create a Hermes profile."""
    out, _, rc = _run_hermes(["config", "create-profile", name])
    return rc == 0


def _set_profile_config(name: str, key: str, value: str) -> bool:
    """Set a config value in a Hermes profile."""
    out, _, rc = _run_hermes(["config", "set", "--profile", name, key, value])
    return rc == 0


def _test_profile(name: str) -> tuple[bool, str]:
    """Test a Hermes profile with a simple chat."""
    out, err, rc = _run_hermes(["-p", name, "-z", "ping"], timeout=60)
    if rc == 0:
        return True, out
    return False, err or "unknown error"


# ── CLI Group ────────────────────────────────────────────────────────


@click.group(name="hermes")
def hermes_cmd() -> None:
    """Manage Hermes Agent connection and configuration.

    One-click setup, profile management, and connectivity checks
    for the underlying Hermes Agent runtime.
    """


@hermes_cmd.command(name="doctor")
def doctor() -> None:
    """Check Hermes Agent installation and connectivity."""
    click.echo("── Hermes Agent Doctor ──")

    # 1. CLI availability
    installed = _check_hermes_installed()
    click.echo(f"  Hermes CLI:     {'✅' if installed else '❌'} {'found' if installed else 'not found'}")
    if not installed:
        click.echo("  → Install: pip install hermes-agent")
        return

    # 2. Version
    out, _, _ = _run_hermes(["--version"])
    click.echo(f"  Version:        {out or 'unknown'}")

    # 3. Profiles
    profiles = _list_profiles()
    click.echo(f"  Profiles:       {len(profiles)} found: {', '.join(profiles) if profiles else '(none)'}")

    # 4. Default profile connectivity test
    test_profile = profiles[0] if profiles else "default"
    ok, msg = _test_profile(test_profile)
    click.echo(f"  Chat test ({test_profile}): {'✅' if ok else '❌'} {msg[:80] if not ok else 'ok'}")

    # 5. Summary
    if installed and profiles and ok:
        click.echo("\n✅ All checks passed. SCCS OS is ready to use.")
    else:
        click.echo("\n⚠️  Some checks failed. Run 'sccsos hermes setup' to configure.")


@hermes_cmd.command(name="show")
def show() -> None:
    """Show current Hermes configuration."""
    from sccsos.core.config import get_config
    cfg = get_config().hermes

    click.echo("── Hermes Configuration (sccsos.yaml) ──")
    click.echo(f"  Profile:    {cfg.profile}")
    click.echo(f"  Binary:     {cfg.binary}")
    click.echo(f"  Adapter:    {cfg.adapter}")
    if cfg.setup.provider:
        click.echo(f"  Setup:      {cfg.setup.provider} / {cfg.setup.model}")

    click.echo("")
    if not _check_hermes_installed():
        click.echo("⚠️  Hermes CLI is not installed.")
        return

    profiles = _list_profiles()
    click.echo(f"Hermes profiles on system: {len(profiles)}")
    for p in profiles:
        marker = " ← active" if p == cfg.profile else ""
        ok, _ = _test_profile(p)
        click.echo(f"  {'✅' if ok else '❌'} {p}{marker}")


@hermes_cmd.command(name="setup")
@click.option("--provider", default=None, help="LLM provider (deepseek/openai/anthropic)")
@click.option("--model", default=None, help="Model name")
@click.option("--api-key", default=None, help="API key (omit for interactive prompt)")
@click.option("--base-url", default=None, help="Custom API base URL")
@click.option("--profile", default=None, help="Hermes profile name (default from sccsos.yaml)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
def setup(provider, model, api_key, base_url, profile, yes):
    """One-click Hermes Agent configuration.

    Installs Hermes (if missing), creates/updates a profile,
    and validates end-to-end connectivity.

    Configuration values are read from sccsos.yaml ``hermes.setup``
    section when not provided via CLI flags.
    """
    from sccsos.core.config import get_config
    cfg = get_config().hermes

    # Determine profile name
    profile_name = profile or cfg.profile or "sccsos"

    click.echo(f"SCCS OS — Hermes Agent 一键配置\n")
    click.echo(f"  目标 Profile: {profile_name}")

    # Step 1: Check Hermes installation
    click.echo("\n[1/5] 检查 Hermes Agent 安装...")
    if not _check_hermes_installed():
        click.echo("  ❌ Hermes CLI 未安装")
        if yes or click.confirm("  是否安装 hermes-agent?"):
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "hermes-agent"],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0:
                click.echo(f"  ❌ 安装失败: {r.stderr.strip()[:200]}")
                return
            click.echo("  ✅ Hermes Agent 安装完成")
        else:
            return
    else:
        out, _, _ = _run_hermes(["--version"])
        click.echo(f"  ✅ Hermes CLI 可用 ({out})")

    # Step 2: Create profile if needed
    click.echo(f"\n[2/5] 检查 Profile '{profile_name}'...")
    if _profile_exists(profile_name):
        click.echo(f"  ✅ Profile '{profile_name}' 已存在")
        if not yes:
            if not click.confirm(f"  是否覆盖 '{profile_name}' 的配置?"):
                click.echo("  跳过配置，保留现有设置")
                profile_ok = True
                # Jump to test
                click.echo(f"\n[5/5] 验证 Profile '{profile_name}'...")
                ok, msg = _test_profile(profile_name)
                if ok:
                    click.echo("  ✅ Profile 验证通过")
                    click.echo(f"\n🎉 Hermes Agent 配置完成！Profile '{profile_name}' 可用。")
                else:
                    click.echo(f"  ❌ 验证失败: {msg[:100]}")
                return
    else:
        click.echo(f"  → Profile '{profile_name}' 不存在，正在创建...")
        if not _create_profile(profile_name):
            click.echo(f"  ❌ 创建 Profile 失败")
            return
        click.echo(f"  ✅ Profile '{profile_name}' 已创建")

    # Step 3: Collect configuration values
    click.echo(f"\n[3/5] 配置 LLM 连接...")

    # Resolve values: CLI flag > sccsos.yaml > interactive prompt
    resolved_provider = provider or cfg.setup.provider or ""
    if not resolved_provider:
        resolved_provider = click.prompt(
            "  LLM 服务商", type=click.Choice(["deepseek", "openai", "anthropic"]),
            default="deepseek",
        )

    resolved_model = model or cfg.setup.model or ""
    if not resolved_model:
        model_defaults = {
            "deepseek": "deepseek-v4-flash",
            "openai": "gpt-4o",
            "anthropic": "claude-sonnet-4",
        }
        resolved_model = click.prompt(
            "  模型名称", default=model_defaults.get(resolved_provider, ""),
        )

    resolved_api_key = api_key or cfg.setup.api_key or ""
    if not resolved_api_key:
        resolved_api_key = click.prompt("  API Key", hide_input=True)

    resolved_base_url = base_url or cfg.setup.base_url or ""
    if not resolved_base_url:
        resolved_base_url = click.prompt(
            "  API 地址 (回车使用默认)", default="",
        ) or ""

    # Step 4: Apply configuration
    click.echo(f"\n[4/5] 写入 Profile 配置...")
    _set_profile_config(profile_name, "provider", resolved_provider)
    _set_profile_config(profile_name, "model", resolved_model)
    _set_profile_config(profile_name, "api_key", resolved_api_key)
    if resolved_base_url:
        _set_profile_config(profile_name, "base_url", resolved_base_url)
    click.echo(f"  ✅ Provider: {resolved_provider}")
    click.echo(f"  ✅ Model:    {resolved_model}")
    click.echo(f"  ✅ API Key:  {'***' + resolved_api_key[-4:] if len(resolved_api_key) > 4 else '***'}")

    # Step 5: Validate
    click.echo(f"\n[5/5] 验证 Profile '{profile_name}'...")
    ok, msg = _test_profile(profile_name)
    if ok:
        click.echo("  ✅ Profile 验证通过 — LLM 响应正常")
        click.echo(f"\n🎉 Hermes Agent 配置完成！Profile '{profile_name}' 已就绪。")
        click.echo(f"\n后续步骤:")
        click.echo(f"  sccsos health                  # 检查 SCCS OS 健康状态")
        click.echo(f"  sccsos agent create architect   # 创建一个 Agent")
        click.echo(f"  sccsos agent start architect    # 启动 Agent")
    else:
        click.echo(f"  ❌ 验证失败: {msg[:200]}")
        click.echo("  请检查 API Key 和网络连接后重试。")


@hermes_cmd.command(name="use")
@click.argument("profile_name", required=True)
def use(profile_name: str) -> None:
    """Switch the active Hermes profile used by SCCS OS.

    Updates sccsos.yaml to use PROFILE_NAME as the default profile.
    """
    import yaml
    from pathlib import Path
    from sccsos.core.config import DEFAULT_CONFIG_PATH

    # Check profile exists
    if not _profile_exists(profile_name):
        click.echo(f"❌ Profile '{profile_name}' 不存在.")
        click.echo(f"可用 profiles: {', '.join(_list_profiles())}")
        return

    # Update sccsos.yaml
    config_path = Path(DEFAULT_CONFIG_PATH)
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    else:
        data = {}

    if "hermes" not in data:
        data["hermes"] = {}
    data["hermes"]["profile"] = profile_name

    config_path.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False), encoding="utf-8")
    click.echo(f"✅ 默认 profile 已切换为 '{profile_name}'")

    # Test
    ok, msg = _test_profile(profile_name)
    if ok:
        click.echo(f"✅ Profile '{profile_name}' 验证通过")
    else:
        click.echo(f"⚠️  Profile '{profile_name}' 验证失败: {msg[:100]}")
