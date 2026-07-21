"""CLI commands for Hermes Agent management.

Provides ``sccsos hermes`` subcommands for one-click Hermes Agent
setup, configuration display, environment variable injection,
skill directory management, and auto-fix diagnostics.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import click

from sccsos.observability.logger import get_logger

logger = get_logger()


# ── Provider environment variable mapping ────────────────────────────

PROVIDER_ENV_KEYS: dict[str, str] = {
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY",
    "together": "TOGETHER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}

PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "deepseek": "deepseek-v4-flash",
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4",
    "groq": "llama-3.3-70b",
    "together": "mixtral-8x22b",
    "mistral": "mistral-large",
}

PROVIDER_DEFAULT_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
}


# ── Helpers ─────────────────────────────────────────────────────────


def _resolve_hermes_binary() -> str:
    """Resolve Hermes binary path: env var > config > default."""
    from_env = os.environ.get("HERMES_BINARY", "")
    if from_env:
        return from_env
    try:
        cfg = _get_hermes_config()
        if cfg.binary:
            return cfg.binary
    except Exception:
        pass
    return "hermes"


def _get_hermes_home() -> str:
    """Get HERMES_HOME: env var > config > default (~/.hermes)."""
    from_env = os.environ.get("HERMES_HOME", "")
    if from_env:
        return from_env
    try:
        cfg = _get_hermes_config()
        if cfg.home:
            return cfg.home
    except Exception:
        pass
    return str(Path.home() / ".hermes")


def _get_hermes_code_path() -> str:
    """Get HERMES_CODE_PATH: env var > config > default.

    Default checks common git-installer location
    (~/.hermes/hermes-agent/).
    """
    from_env = os.environ.get("HERMES_CODE_PATH", "")
    if from_env:
        return from_env
    try:
        cfg = _get_hermes_config()
        if cfg.code_path:
            return cfg.code_path
    except Exception:
        pass
    # Default: check common git-installer location
    default_path = Path.home() / ".hermes" / "hermes-agent"
    if default_path.exists():
        return str(default_path)
    return ""


def _run_hermes(args: list[str], timeout: int = 30) -> tuple[str, str, int]:
    """Run a hermes CLI command and return (stdout, stderr, returncode).

    Resolves the Hermes binary via :func:`_resolve_hermes_binary`,
    which respects ``HERMES_BINARY`` env var, ``sccsos.yaml``'s
    ``hermes.binary`` setting, or falls back to ``hermes``.
    """
    binary = _resolve_hermes_binary()
    try:
        r = subprocess.run(
            [binary, *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        return "", (
            f"Hermes CLI '{binary}' not found. "
            f"Install with: pip install hermes-agent"
        ), -1
    except subprocess.TimeoutExpired:
        return "", f"hermes command timed out after {timeout}s", -1


def _get_env_api_key(provider: str) -> str:
    """Read the standard API key environment variable for a provider."""
    env_key = PROVIDER_ENV_KEYS.get(provider, "")
    if not env_key:
        return ""
    return os.environ.get(env_key, "")


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


def _test_profile(name: str, timeout: int = 60) -> tuple[bool, str]:
    """Test a Hermes profile with a simple chat."""
    out, err, rc = _run_hermes(["-p", name, "-z", "ping"], timeout=timeout)
    if rc == 0:
        return True, out
    return False, err or "unknown error"


def _get_config_path() -> Path:
    """Resolve the sccsos.yaml config file path."""
    from sccsos.core.config import DEFAULT_CONFIG_PATH
    env_path = os.environ.get("AGENTOS_CONFIG", "")
    return Path(env_path) if env_path else Path(DEFAULT_CONFIG_PATH)


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


def _get_hermes_config():
    """Get the hermes config section from sccsos.yaml."""
    from sccsos.core.config import get_config
    return get_config().hermes


# ── CLI Group ────────────────────────────────────────────────────────


@click.group(name="hermes")
def hermes_cmd() -> None:
    """Manage Hermes Agent connection and configuration.

    One-click setup, profile management, environment variable injection,
    skill directory configuration, and connectivity diagnostics.
    """


@hermes_cmd.command(name="doctor")
@click.option("--fix", "-f", is_flag=True, help="Auto-fix detected issues")
def doctor(fix: bool) -> None:
    """Check Hermes Agent installation and connectivity.

    Use ``--fix`` to automatically resolve common issues.
    """
    click.echo("── Hermes Agent 诊断 ──")

    issues: list[tuple[str, str, str]] = []  # (section, description, fix_hint)

    # 1. CLI availability
    binary_path = _resolve_hermes_binary()
    installed = _check_hermes_installed()
    click.echo(f"  Hermes CLI:     {'✅' if installed else '❌'} {'可用' if installed else '未安装'}")
    click.echo(f"  Binary path:    {binary_path}")

    # 1b. Installation mode (via HermesManager)
    try:
        from sccsos.core.hermes_manager import get_manager
        inst = get_manager().discover()
        click.echo(f"  安装模式:       {inst.mode.value}")
    except Exception:
        pass
    if not installed:
        issues.append(("CLI", "Hermes CLI 未安装", "pip install hermes-agent"))

    if not installed:
        if fix:
            click.echo("  → 正在安装 hermes-agent...")
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "hermes-agent"],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0:
                click.echo("  ✅ Hermes Agent 安装完成")
                installed = True
            else:
                click.echo(f"  ❌ 安装失败: {r.stderr.strip()[:200]}")
                return
        else:
            click.echo("  建议: pip install hermes-agent")
            return

    # 2. Version
    out, _, _ = _run_hermes(["--version"])
    click.echo(f"  Version:        {out or 'unknown'}")

    # 2b. Environment paths
    hermes_home = _get_hermes_home()
    hermes_code_path = _get_hermes_code_path()
    click.echo(f"  HERMES_HOME:    {hermes_home}")
    click.echo(f"  HERMES_CODE_PATH: {hermes_code_path or 'not detected'}")
    home_ok = Path(hermes_home).exists()
    if not home_ok:
        issues.append(("home", f"HERMES_HOME 目录不存在: {hermes_home}", "sccsos hermes setup"))

    # 3. Hermes config directory
    hermes_dir = Path.home() / ".hermes"
    config_ok = hermes_dir.exists()
    click.echo(f"  Config dir:     {'✅' if config_ok else '❌'} {hermes_dir}")
    if not config_ok:
        issues.append(("config", "Hermes 配置目录不存在", "hermes setup"))

    # 4. Profiles
    profiles = _list_profiles()
    if profiles:
        click.echo(f"  Profiles:       ✅ {len(profiles)} 个: {', '.join(profiles)}")
    else:
        click.echo(f"  Profiles:       ❌ 无可用 profile")
        issues.append(("profile", "无可用 Hermes profile", "sccsos hermes setup"))

    # 5. Environment variables
    click.echo(f"  ── 环境变量 ──")
    env_found = 0
    for provider, env_key in sorted(PROVIDER_ENV_KEYS.items()):
        val = os.environ.get(env_key, "")
        if val:
            env_found += 1
            click.echo(f"    ✅ {env_key}=***{val[-4:]}")
        else:
            click.echo(f"    ❌ {env_key} 未设置")
    click.echo(f"    --- {env_found}/{len(PROVIDER_ENV_KEYS)} 个有效")

    # If env vars are missing but a profile is configured, check for API key in profile
    if env_found == 0 and profiles:
        # Try the active profile
        cfg = _get_hermes_config()
        active = cfg.profile if cfg.profile in profiles else profiles[0]
        click.echo(f"  → 可通过 'sccsos hermes setup' 为 profile '{active}' 注入 API Key")

    # 6. Profile connectivity test
    test_profile = profiles[0] if profiles else ""
    if test_profile:
        ok, msg = _test_profile(test_profile)
        click.echo(f"  Chat test ({test_profile}): {'✅' if ok else '❌'} {'通过' if ok else msg[:80]}")
        if not ok:
            issues.append(("connectivity", f"Profile '{test_profile}' 连通性测试失败", "sccsos hermes setup --yes"))
    else:
        test_profile = "default"
        ok, msg = _test_profile("default")
        click.echo(f"  Chat test ({test_profile}): {'✅' if ok else '❌'} {'通过' if ok else msg[:80]}")

    # 7. Skills directory
    from sccsos.core.config import DEFAULT_CONFIG_PATH
    skills_ok = True
    skills_dir = Path("skills")
    if skills_dir.exists():
        skill_count = len(list(skills_dir.glob("*.yaml"))) + len(list(skills_dir.glob("*.py")))
        click.echo(f"  Skills dir:     ✅ {skills_dir}/ ({skill_count} 个技能)")
    else:
        click.echo(f"  Skills dir:     ⚠️  skills/ 目录不存在（可选）")

    # 8. Summary
    click.echo("")
    if not issues:
        click.echo("🎉 所有检查通过！SCCS OS 已就绪。")
    else:
        click.echo(f"⚠️  发现 {len(issues)} 个问题:")
        for section, desc, hint in issues:
            click.echo(f"  [{section}] {desc}")
            click.echo(f"    → {hint}")
        if fix:
            click.echo("\n--fix 模式：已自动修复可修复项，剩余问题请按提示处理。")
        else:
            click.echo("\n使用 '--fix' 参数自动修复，或按提示手动处理。")


@hermes_cmd.command(name="show")
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


@hermes_cmd.command(name="setup")
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
        click.echo(f"  ✅ 使用 CLI 参数提供的 API Key")
    elif env_api_key:
        resolved_api_key = env_api_key
        click.echo(f"  ✅ 使用环境变量 {env_key_name}")
    elif cfg.setup.api_key:
        resolved_api_key = cfg.setup.api_key
        click.echo(f"  ✅ 使用配置文件中的 API Key")
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
        click.echo(f"\n🎉 环境变量配置完成！")
        click.echo(f"  运行 'sccsos hermes setup' 可继续配置 Hermes Profile。")
        return

    # ── Step 5 (or 4 for non-skip): Create/Update profile ───────
    step_label = "[4/5]" if skip_env else "[5/5]"
    click.echo(f"\n{step_label} 配置 Hermes Profile '{profile_name}'...")

    if _profile_exists(profile_name):
        if not yes and not click.confirm(f"  覆盖 '{profile_name}' 的现有配置?"):
            click.echo("  跳过 Profile 配置")
        else:
            _set_profile_config(profile_name, "provider", resolved_provider)
            _set_profile_config(profile_name, "model", resolved_model)
            _set_profile_config(profile_name, "api_key", resolved_api_key)
            resolved_base_url = base_url or cfg.setup.base_url or PROVIDER_DEFAULT_URLS.get(resolved_provider, "")
            if resolved_base_url:
                _set_profile_config(profile_name, "base_url", resolved_base_url)
            click.echo(f"  ✅ Provider: {resolved_provider}")
            click.echo(f"  ✅ Model:    {resolved_model}")
            click.echo(f"  ✅ API Key:  {'***' + resolved_api_key[-4:] if len(resolved_api_key) > 4 else '***'}")
            if resolved_base_url:
                click.echo(f"  ✅ Base URL: {resolved_base_url}")
    else:
        click.echo(f"  → 创建 Profile '{profile_name}'...")
        if not _create_profile(profile_name):
            click.echo(f"  ❌ 创建 Profile 失败")
            return
        _set_profile_config(profile_name, "provider", resolved_provider)
        _set_profile_config(profile_name, "model", resolved_model)
        _set_profile_config(profile_name, "api_key", resolved_api_key)
        resolved_base_url = base_url or cfg.setup.base_url or PROVIDER_DEFAULT_URLS.get(resolved_provider, "")
        if resolved_base_url:
            _set_profile_config(profile_name, "base_url", resolved_base_url)
        click.echo(f"  ✅ Profile '{profile_name}' 已创建并配置")

    # Update sccsos.yaml with the profile name
    _update_yaml(["hermes", "profile"], profile_name)
    click.echo(f"  ✅ sccsos.yaml 已更新")

    # ── Validate end-to-end ─────────────────────────────────────
    click.echo(f"\n  验证 Profile '{profile_name}'...")
    ok, msg = _test_profile(profile_name, timeout=90)
    if ok:
        click.echo("  ✅ Profile 验证通过 — LLM 响应正常")
        click.echo(f"\n🎉 Hermes Agent 配置完成！Profile '{profile_name}' 已就绪。")
        click.echo(f"\n后续步骤:")
        click.echo(f"  sccsos health                    # 检查 SCCS OS 健康状态")
        click.echo(f"  sccsos agent create architect     # 创建一个 Agent")
        click.echo(f"  sccsos agent start architect      # 启动 Agent")
        click.echo(f"  sccsos workflow run demo.yaml     # 运行工作流")
    else:
        click.echo(f"  ❌ 验证失败: {msg[:200]}")
        click.echo("  请检查 API Key 和网络连接后重试。")
        click.echo(f"  → 环境变量 {env_key_name} 已设置，可直接重试命令。")


@hermes_cmd.command(name="use")
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
