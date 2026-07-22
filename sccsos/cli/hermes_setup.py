"""Hermes setup/show/use commands for SCCS OS CLI.

Extracted from :mod:`sccsos.cli.hermes_cmd` to reduce module size.
Functions here are registered on the ``hermes_cmd`` group via
:func:`register_setup_commands`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import click

from sccsos.observability.logger import get_logger
from sccsos.cli.hermes_cmd import (
    PROVIDER_DEFAULT_MODELS,
    PROVIDER_DEFAULT_URLS,
    PROVIDER_ENV_KEYS,
    _check_hermes_installed,
    _create_profile,
    _get_config_path,
    _get_env_api_key,
    _get_hermes_code_path,
    _get_hermes_config,
    _get_hermes_home,
    _list_profiles,
    _profile_exists,
    _resolve_hermes_binary,
    _run_hermes,
    _set_profile_config,
    _test_profile,
)

logger = get_logger()


# ── Helpers ─────────────────────────────────────────────────────────


def _update_yaml(key_path: list[str], value: str) -> None:
    """Update a nested key in sccsos.yaml."""
    import yaml
    config_path = _get_config_path()
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    else:
        data = {}
    # Navigate to the nested key
    target = data
    for k in key_path[:-1]:
        if k not in target or not isinstance(target[k], dict):
            target[k] = {}
        target = target[k]
    target[key_path[-1]] = value
    config_path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


# ── Commands ────────────────────────────────────────────────────────


@click.command(name="show")
def show() -> None:
    """Show current Hermes configuration and environment."""
    cfg = _get_hermes_config()

    click.echo("── Hermes 配置 (sccsos.yaml) ──")
    click.echo(f"  Profile:    {cfg.profile}")
    click.echo(f"  Binary:     {cfg.binary} ({_resolve_hermes_binary()})")
    click.echo(f"  Adapter:    {cfg.adapter}")
    click.echo(f"  HERMES_HOME: {cfg.home or _get_hermes_home()}")
    click.echo(f"  HERMES_CODE_PATH: {cfg.code_path or _get_hermes_code_path() or '(not set)'}")
    if cfg.setup.provider:
        click.echo(f"  Provider:   {cfg.setup.provider}")
        click.echo(f"  Model:      {cfg.setup.model}")

    click.echo("")
    click.echo("── 环境变量 ──")
    for provider, env_key in sorted(PROVIDER_ENV_KEYS.items()):
        val = os.environ.get(env_key, "")
        if val:
            click.echo(f"  ✅ {env_key}=***{val[-4:]}")
        else:
            click.echo(f"  ❌ {env_key} 未设置")

    click.echo("")
    if not _check_hermes_installed():
        click.echo("⚠️  Hermes CLI 未安装。")
        return

    profiles = _list_profiles()
    click.echo(f"Hermes 系统 profiles: {len(profiles)}")
    for p in profiles:
        marker = " ← 当前使用" if p == cfg.profile else ""
        ok, _ = _test_profile(p)
        click.echo(f"  {'✅' if ok else '❌'} {p}{marker}")

    # Check skills directory
    skills_dir = Path("skills")
    if skills_dir.exists():
        skill_count = len(list(skills_dir.glob("*.yaml"))) + len(list(skills_dir.glob("*.py")))
        click.echo(f"\nSkills: {skills_dir}/ ({skill_count} 个技能)")
    else:
        click.echo(f"\nSkills: skills/ 目录不存在（可选）")


@click.command(name="setup")
@click.option("--provider", default=None, help="LLM provider (deepseek/openai/anthropic/...)")
@click.option("--model", default=None, help="Model name")
@click.option("--api-key", default=None, help="API key (omit to use env var or interactive)")
@click.option("--base-url", default=None, help="Custom API base URL")
@click.option("--profile", default=None, help="Hermes profile name (default from sccsos.yaml)")
@click.option("--env-only", is_flag=True, help="Only set environment variables, skip profile config")
@click.option("--skip-env", is_flag=True, help="Skip environment variable injection")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
def setup(provider, model, api_key, base_url, profile, env_only, skip_env, yes):
    """One-click Hermes Agent configuration.

    Automatically:

    \b
    - Installs Hermes CLI (if missing)
    - Creates/updates the Hermes profile
    - Injects API key into the environment
    - Sets up skills directory
    - Validates end-to-end connectivity
    """
    cfg = _get_hermes_config()
    profile_name = profile or cfg.profile or "sccsos"

    click.echo("SCCS OS — Hermes Agent 一键配置\n")

    if env_only:
        click.echo("  模式: 仅环境变量（跳过 Profile 配置）")
    else:
        click.echo(f"  目标 Profile: {profile_name}")

    # ── Step 1: Check / Install Hermes ──────────────────────────
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

    # ── Step 2: Resolve provider + model ────────────────────────
    click.echo("\n[2/5] 解析 LLM 配置...")
    resolved_provider = provider or cfg.setup.provider or ""
    if not resolved_provider:
        resolved_provider = click.prompt(
            "  LLM 服务商",
            type=click.Choice(list(PROVIDER_ENV_KEYS.keys())),
            default="deepseek",
        )

    resolved_model = model or cfg.setup.model or ""
    if not resolved_model:
        resolved_model = click.prompt(
            "  模型名称", default=PROVIDER_DEFAULT_MODELS.get(resolved_provider, ""),
        )

    # ── Step 3: Resolve API key ─────────────────────────────────
    click.echo("\n[3/5] 配置 API Key...")

    # Priority: CLI arg > env var > sccsos.yaml > interactive
    env_key_name = PROVIDER_ENV_KEYS.get(resolved_provider, "")
    env_api_key = _get_env_api_key(resolved_provider)

    if api_key:
        resolved_api_key = api_key
        click.echo("  ✅ 使用 CLI 参数提供的 API Key")
    elif env_api_key:
        resolved_api_key = env_api_key
        click.echo(f"  ✅ 使用环境变量 {env_key_name}")
    elif cfg.setup.api_key:
        resolved_api_key = cfg.setup.api_key
        click.echo("  ✅ 使用配置文件中的 API Key")
    else:
        resolved_api_key = click.prompt(
            f"  请输入 {resolved_provider} API Key"
            f" (设置 {env_key_name} 环境变量可跳过此步)",
            hide_input=True,
        )

    # ── Step 4: Set environment variables ───────────────────────
    if not skip_env and env_key_name:
        click.echo(f"\n[4/5] 设置环境变量...")

        # Write to shell profile for persistence
        shell_rc = None
        for rc_file in [".zshrc", ".bashrc", ".bash_profile", ".zprofile"]:
            rc_path = Path.home() / rc_file
            if rc_path.exists():
                shell_rc = rc_path
                break

        if shell_rc and not yes:
            if click.confirm(f"  将 {env_key_name} 写入 {shell_rc.name}?"):
                escaped_key = resolved_api_key.replace("'", "'\\''")
                line = f"export {env_key_name}='{escaped_key}'"
                if line not in shell_rc.read_text(encoding="utf-8"):
                    with open(shell_rc, "a", encoding="utf-8") as f:
                        f.write(f"\n# sccsos: {resolved_provider} API Key\n{line}\n")
                    click.echo(f"  ✅ {env_key_name} 已追加到 {shell_rc.name}")
                else:
                    click.echo(f"  ⚠️  {env_key_name} 已在 {shell_rc.name} 中存在，跳过")

        # Export to current session
        os.environ[env_key_name] = resolved_api_key
        click.echo(f"  ✅ 当前会话已设置 {env_key_name}")

    # ── If env-only mode, skip profile config ───────────────────
    if env_only:
        click.echo("\n🎉 环境变量配置完成！")
        click.echo("  运行 'sccsos hermes setup' 可继续配置 Hermes Profile。")
        return

    # ── Step 5 (or 4 for non-skip): Create/Update profile ───────
    step_label = "[4/5]" if skip_env else "[5/5]"
    click.echo(f"\n{step_label} 配置 Hermes Profile '{profile_name}'...")

    if _profile_exists(profile_name):
        if not yes and not click.confirm(f"  覆盖 '{profile_name}' 的现有配置?"):
            click.echo("  跳过 Profile 配置")
        else:
            _set_profile_config(profile_name, "model.default", resolved_model)
            _set_profile_config(profile_name, "model.provider", resolved_provider)
            _set_profile_config(profile_name, "model.api_key", resolved_api_key)
            resolved_base_url = base_url or cfg.setup.base_url or PROVIDER_DEFAULT_URLS.get(resolved_provider, "")
            if resolved_base_url:
                _set_profile_config(profile_name, "model.base_url", resolved_base_url)
            click.echo(f"  ✅ Provider: {resolved_provider}")
            click.echo(f"  ✅ Model:    {resolved_model}")
            click.echo(f"  ✅ API Key:  {'***' + resolved_api_key[-4:] if len(resolved_api_key) > 4 else '***'}")
            if resolved_base_url:
                click.echo(f"  ✅ Base URL: {resolved_base_url}")
    else:
        click.echo(f"  → 创建 Profile '{profile_name}'...")
        if not _create_profile(profile_name):
            click.echo("  ❌ 创建 Profile 失败")
            return
        _set_profile_config(profile_name, "model.default", resolved_model)
        _set_profile_config(profile_name, "model.provider", resolved_provider)
        _set_profile_config(profile_name, "model.api_key", resolved_api_key)
        resolved_base_url = base_url or cfg.setup.base_url or PROVIDER_DEFAULT_URLS.get(resolved_provider, "")
        if resolved_base_url:
            _set_profile_config(profile_name, "model.base_url", resolved_base_url)
        click.echo(f"  ✅ Profile '{profile_name}' 已创建并配置")

    # Update sccsos.yaml with the profile name
    _update_yaml(["hermes", "profile"], profile_name)
    click.echo("  ✅ sccsos.yaml 已更新")

    # ── Validate end-to-end ─────────────────────────────────────
    click.echo(f"\n  验证 Profile '{profile_name}'...")
    ok, msg = _test_profile(profile_name, timeout=90)
    if ok:
        click.echo("  ✅ Profile 验证通过 — LLM 响应正常")
        click.echo(f"\n🎉 Hermes Agent 配置完成！Profile '{profile_name}' 已就绪。")
        click.echo("\n后续步骤:")
        click.echo("  sccsos health                    # 检查 SCCS OS 健康状态")
        click.echo("  sccsos agent create architect     # 创建一个 Agent")
        click.echo("  sccsos agent start architect      # 启动 Agent")
        click.echo("  sccsos workflow run demo.yaml     # 运行工作流")
    else:
        click.echo(f"  ❌ 验证失败: {msg[:200]}")
        click.echo("  请检查 API Key 和网络连接后重试。")
        click.echo(f"  → 环境变量 {env_key_name} 已设置，可直接重试命令。")


@click.command(name="use")
@click.argument("profile_name", required=True)
def use(profile_name: str) -> None:
    """Switch the active Hermes profile used by SCCS OS.

    Updates sccsos.yaml to use PROFILE_NAME as the default profile.
    """
    if not _profile_exists(profile_name):
        click.echo(f"❌ Profile '{profile_name}' 不存在.")
        click.echo(f"可用 profiles: {', '.join(_list_profiles())}")
        return

    _update_yaml(["hermes", "profile"], profile_name)
    click.echo(f"✅ 默认 profile 已切换为 '{profile_name}'")

    ok, msg = _test_profile(profile_name)
    if ok:
        click.echo(f"✅ Profile '{profile_name}' 验证通过")
    else:
        click.echo(f"⚠️  Profile '{profile_name}' 验证失败: {msg[:100]}")
