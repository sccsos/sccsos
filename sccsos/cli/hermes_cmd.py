"""CLI commands for Hermes Agent management.

Provides ``sccsos hermes`` subcommands for one-click Hermes Agent
setup, configuration display, environment variable injection,
skill directory management, and auto-fix diagnostics.
"""

from __future__ import annotations

import os
import shutil
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
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
}


# ── Helpers ─────────────────────────────────────────────────────────


def _resolve_hermes_binary() -> str:
    """Resolve Hermes binary path: env var > explicit config > discovered > default.

    Returns the full path to ``hermes`` when found via
    :func:`_find_hermes_bin_dir`, so subprocess invocations succeed
    even when the binary is not yet in ``PATH`` (e.g. right after
    installation before shell rc is re-sourced).
    """
    # 1. Explicit env var overrides (HERMES_BIN > HERMES_BINARY)
    for var in ("HERMES_BIN", "HERMES_BINARY"):
        val = os.environ.get(var, "")
        if val and Path(val).exists():
            return val
    # 2. Explicit binary path in sccsos.yaml (skip default "hermes")
    try:
        cfg = _get_hermes_config()
        if cfg.binary and cfg.binary != "hermes":
            return cfg.binary
    except Exception:
        pass
    # 3. Discover the actual binary on disk
    from sccsos.cli.hermes_config_sync import _find_hermes_bin_dir  # noqa: E402
    bin_dir = _find_hermes_bin_dir()
    if bin_dir:
        full_path = str(Path(bin_dir) / "hermes")
        if Path(full_path).exists():
            return full_path
    # 4. Fallback — hope it's in PATH
    return "hermes"


def _get_hermes_home() -> str:
    """Get HERMES_HOME: env var > config > $HOME/hermes/data > ~/.hermes."""
    from_env = os.environ.get("HERMES_HOME", "")
    if from_env:
        return from_env
    try:
        cfg = _get_hermes_config()
        if cfg.home:
            return cfg.home
    except Exception:
        pass
    # Always prefer $HOME/hermes/data (fully-enclosed pattern) over ~/.hermes
    hermes_data = Path.home() / "hermes" / "data"
    if hermes_data.exists():
        return str(hermes_data)
    # On first install, return the preferred default even if it doesn't exist yet
    # (it will be created by _ensure_hermes_home after install completes).
    return str(hermes_data)


def _get_hermes_install_dir() -> str:
    """Get HERMES_INSTALL_DIR: env var > config > $HOME/hermes/agent."""
    from_env = os.environ.get("HERMES_INSTALL_DIR", "")
    if from_env:
        return from_env
    try:
        cfg = _get_hermes_config()
        if cfg.install_dir:
            return cfg.install_dir
    except Exception:
        pass
    return str(Path.home() / "hermes" / "agent")


def _get_uv_install_dir() -> str:
    """Get UV_INSTALL_DIR: env var > config > $HOME/hermes/data/bin."""
    from_env = os.environ.get("UV_INSTALL_DIR", "")
    if from_env:
        return from_env
    try:
        cfg = _get_hermes_config()
        if cfg.uv.install_dir:
            return cfg.uv.install_dir
    except Exception:
        pass
    return str(Path.home() / "hermes" / "data" / "bin")


def _get_uv_cache_dir() -> str:
    """Get UV_CACHE_DIR: env var > config > $HOME/hermes/data/uv-cache."""
    from_env = os.environ.get("UV_CACHE_DIR", "")
    if from_env:
        return from_env
    try:
        cfg = _get_hermes_config()
        if cfg.uv.cache_dir:
            return cfg.uv.cache_dir
    except Exception:
        pass
    return str(Path.home() / "hermes" / "data" / "uv-cache")


def _run_hermes(args: list[str], timeout: int = 30,
                extra_env: Optional[dict[str, str]] = None) -> tuple[str, str, int]:
    """Run a hermes CLI command and return (stdout, stderr, returncode).

    Resolves the Hermes binary via :func:`_resolve_hermes_binary`,
    which respects ``HERMES_BINARY`` env var, ``sccsos.yaml``'s
    ``hermes.binary`` setting, or falls back to ``hermes``.

    When ``extra_env`` is provided, these additional environment variables
    are injected into the subprocess (e.g. ``HERMES_HOME`` for custom
    installation paths).
    """
    binary = _resolve_hermes_binary()
    try:
        proc_env = os.environ.copy()
        if extra_env:
            proc_env.update(extra_env)
        r = subprocess.run(
            [binary, *args],
            capture_output=True, text=True, timeout=timeout,
            env=proc_env,
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


def _list_profiles(extra_env: Optional[dict[str, str]] = None) -> list[str]:
    """List available Hermes profiles via ``hermes profile list``.

    Args:
        extra_env: Optional env vars override (e.g. resolved HERMES_HOME).
    """
    out, _, rc = _run_hermes(["profile", "list"], extra_env=extra_env)
    if rc != 0 or not out:
        return []
    # Parse table: skip header line and separator line (contain "Profile" or dashes)
    lines = out.splitlines()
    profiles = []
    for line in lines:
        line = line.strip()
        if not line or "Profile" in line or "─" in line:
            continue
        # Strip ◆ active marker and take first word
        name = line.lstrip("◆ ").split()[0] if line.split() else ""
        if name:
            profiles.append(name)
    return profiles


def _profile_exists(name: str, extra_env: Optional[dict[str, str]] = None) -> bool:
    """Check if a Hermes profile exists.

    Args:
        extra_env: Optional env vars override (e.g. resolved HERMES_HOME).
    """
    return name in _list_profiles(extra_env=extra_env)


def _create_profile(name: str, extra_env: Optional[dict[str, str]] = None) -> bool:
    """Create a Hermes profile via ``hermes profile create``."""
    out, _, rc = _run_hermes(["profile", "create", name], timeout=60, extra_env=extra_env)
    return rc == 0


def _set_profile_config(name: str, key: str, value: str,
                        extra_env: Optional[dict[str, str]] = None) -> bool:
    """Set a config value in a Hermes profile via ``hermes -p <name> config set``."""
    out, _, rc = _run_hermes(["-p", name, "config", "set", key, value], extra_env=extra_env)
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


def _get_hermes_config():
    """Get the hermes config section from sccsos.yaml."""
    from sccsos.core.config import get_config
    return get_config().hermes


# ── Install helpers ──────────────────────────────────────────────────


def _report_install_status() -> None:
    """Check and report Hermes installation status."""
    from sccsos.cli.hermes_install import _report_install_status as _do
    _do()



def _install_script(china_mirror: bool, yes: bool, timeout: int = 600,
                    home: str = "", install_dir: str = "",
                    uv_install_dir: str = "", uv_cache_dir: str = "") -> bool:
    """Install Hermes Agent via official one-click install script.

    Uses the upstream install.sh which auto-configures venv, deps, and CLI.
    After success, writes detected home/install_dir back to sccsos.yaml.
    """
    from sccsos.cli.hermes_install import _install_script as _do
    return _do(china_mirror, yes, timeout=timeout, home=home, install_dir=install_dir,
               uv_install_dir=uv_install_dir, uv_cache_dir=uv_cache_dir)


def _install_docker(version: Optional[str], yes: bool, force: bool,
                    home: str = "", install_dir: str = "",
                    uv_install_dir: str = "", uv_cache_dir: str = "",
                    china_mirror: bool = False) -> bool:
    """Install Hermes Agent via Docker image pull.

    After success, writes detected home/install_dir back to sccsos.yaml.
    """
    from sccsos.cli.hermes_install import _install_docker as _do
    return _do(version, yes, force, home=home, install_dir=install_dir,
               uv_install_dir=uv_install_dir, uv_cache_dir=uv_cache_dir,
               china_mirror=china_mirror)











def _verify_model_config(config_path: Path) -> dict:
    """Inspect a Hermes config file and return a dict with model status.

    Returns::
        {"exists": bool, "is_dict": bool, "model": dict, "errors": [str]}
    """
    from sccsos.cli.hermes_install import _verify_model_config as _do
    return _do(config_path)


def _get_profile_config_path(profile_name: str) -> Path:
    """Get the filesystem path to a Hermes profile's config.yaml.

    Resolves the Hermes home root by checking the effective HERMES_HOME,
    then walking up if it points inside a ``profiles/`` subdirectory
    (e.g. when ``HERMES_HOME`` resolves to a profile directory).
    """
    from sccsos.cli.hermes_install import _get_profile_config_path as _do
    return _do(profile_name)








# ── CLI Group ────────────────────────────────────────────────────────


@click.group(name="hermes")
def hermes_cmd() -> None:
    """Manage Hermes Agent connection and configuration.

    One-click setup, profile management, environment variable injection,
    skill directory configuration, and connectivity diagnostics.
    """


# (doctor command moved to cli/hermes_doctor.py)
# (show/setup/use commands moved to cli/hermes_setup.py)

from sccsos.cli.hermes_setup import show, setup, use
from sccsos.cli.hermes_doctor import env_setup, doctor, postinstall
from sccsos.cli.hermes_config_sync import config_sync

hermes_cmd.add_command(show)
hermes_cmd.add_command(setup)
hermes_cmd.add_command(use)
hermes_cmd.add_command(env_setup)
hermes_cmd.add_command(doctor)
hermes_cmd.add_command(postinstall)
hermes_cmd.add_command(config_sync)




@hermes_cmd.command(name="install")
@click.option("--method", "-m", default="script", type=click.Choice(["script", "git", "docker"]),
              help="安装方式（默认 script：一键安装脚本）")
@click.option("--version", "-v", default=None,
              help="版本标签（git: checkout, docker: image tag）")
@click.option("--china-mirror", is_flag=True,
              help="使用国内镜像加速（script 模式 + git 模式 + docker 模式）")
@click.option("--git-url", default="https://github.com/NousResearch/hermes-agent.git",
              help="Git 仓库地址（git 模式，--china-mirror 时自动切换）", show_default=True)
@click.option("--target", "-t", default=None,
              help="安装目标目录（git 模式，默认 {HERMES_HOME}/hermes-agent）")
@click.option("--check", "-c", is_flag=True, help="仅检查安装状态，不安装")
@click.option("--yes", "-y", is_flag=True, help="跳过确认提示")
@click.option("--force", "-f", is_flag=True, help="强制重新安装")
@click.option("--home", default=None,
              help="写入 sccsos.yaml 的 HERMES_HOME 路径")
@click.option("--install-dir", default=None,
              help="写入 sccsos.yaml 的 HERMES_INSTALL_DIR 路径")
def install(method, version, git_url, target, check, yes, force, home, install_dir, china_mirror):
    """Install Hermes Agent on this machine.

    三种安装方式：

    \\\b
    - script（默认）：一键在线脚本，自动配置环境，新手首选
    - git：源码编译安装，适合二次开发
    - docker：Docker 容器部署，适合生产环境

    安装完成后运行 ``sccsos hermes setup`` 配置 LLM Provider 和 API Key。

    .. note::
       仅支持 Linux / macOS。Windows 用户请使用 WSL2。
    """
    click.echo("── SCCS OS — Hermes Agent 安装 ──")
    click.echo("")

    # ── 平台检查 ──
    import sys as _sys
    if _sys.platform == "win32":
        click.echo("  ❌ Windows 暂不支持。Hermes Agent 仅支持 Linux / macOS。")
        click.echo("     请使用 WSL2（Windows Subsystem for Linux）或虚拟机。")
        return

    if check:
        _report_install_status()
        return

    # ── 检测已有安装 ──
    existing = shutil.which("hermes")
    if existing and not force:
        click.echo(f"  ✅ Hermes CLI 已存在: {existing}")
        out, _, _ = _run_hermes(["--version"])
        click.echo(f"  Version: {out or 'unknown'}")
        if not yes:
            click.echo("")
            if not click.confirm("  重新安装?"):
                click.echo("  已取消。")
                return
    elif existing and force:
        click.echo("  检测到已有安装，--force 模式将重新安装...")

    # ── 解析 home / install_dir：CLI 参数 > sccsos.yaml > 默认 ──
    resolved_home = home or _get_hermes_home()
    resolved_config_path = resolved_home   # 与 HERMES_HOME 同值
    resolved_install_dir = install_dir or _get_hermes_install_dir()
    resolved_uv_bin = _get_uv_install_dir()
    resolved_uv_cache = _get_uv_cache_dir()
    if resolved_home:
        click.echo(f"  HERMES_HOME:            {resolved_home}")
        click.echo(f"  HERMES_CONFIG_PATH:     {resolved_config_path}")
    if resolved_install_dir:
        click.echo(f"  INSTALL_DIR:            {resolved_install_dir}")
    resolved_bin = f"{resolved_install_dir}/venv/bin/hermes" if resolved_install_dir else ""
    resolved_bin_dir = f"{resolved_install_dir}/venv/bin" if resolved_install_dir else ""
    click.echo(f"  HERMES_BIN:             {resolved_bin}")
    click.echo(f"  HERMES_BIN_DIR:         {resolved_bin_dir}")
    click.echo(f"  UV_INSTALL_DIR:         {resolved_uv_bin}")
    click.echo(f"  UV_CACHE_DIR:           {resolved_uv_cache}")
    click.echo("")

    # ── 导出到当前 shell 环境 ──
    # 确保安装子进程继承正确路径，同时后续命令直接可用
    os.environ["HERMES_HOME"] = resolved_home
    os.environ["HERMES_CONFIG_PATH"] = resolved_config_path
    os.environ["HERMES_INSTALL_DIR"] = resolved_install_dir
    os.environ["UV_INSTALL_DIR"] = resolved_uv_bin
    os.environ["UV_CACHE_DIR"] = resolved_uv_cache
    click.echo("  ✅ 当前会话已设置环境变量")

    # ── 写入 shell rc 文件（持久化） ──
    from sccsos.cli.hermes_install import _setup_shell_rc  # noqa: E402
    _setup_shell_rc(yes=True, home=resolved_home,
                    install_dir=resolved_install_dir)

    # ── 执行安装 ──
    if method == "script":
        _install_script(china_mirror, yes, home=resolved_home, install_dir=resolved_install_dir,
                        uv_install_dir=resolved_uv_bin, uv_cache_dir=resolved_uv_cache)
    elif method == "git":
        # china-mirror 时自动切换 git 源
        resolved_git_url = git_url
        if china_mirror and git_url == "https://github.com/NousResearch/hermes-agent.git":
            resolved_git_url = "https://cnb.cool/hermesagent-cn/hermes-agent-cn-mirror.git"
            click.echo(f"  ↪ 使用国内镜像: {resolved_git_url}")
        from sccsos.cli.hermes_install import _install_git as _do_git_install
        _do_git_install(version, resolved_git_url, target, yes, force, resolved_home, resolved_install_dir,
                     uv_install_dir=resolved_uv_bin, uv_cache_dir=resolved_uv_cache)
    elif method == "docker":
        _install_docker(version, yes, force, home=resolved_home, install_dir=resolved_install_dir,
                        uv_install_dir=resolved_uv_bin, uv_cache_dir=resolved_uv_cache,
                        china_mirror=china_mirror)

    # ── 安装后验证 ──
    # 安装脚本已将 hermes 安装到 venv/bin 或 ~/.local/bin，
    # 但当前 shell 会话的 PATH 尚未更新。补充查找 binary 路径。
    from sccsos.cli.hermes_config_sync import _find_hermes_bin_dir  # noqa: E402
    bin_dir = _find_hermes_bin_dir()
    if bin_dir:
        os.environ["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"
        click.echo(f"  ✅ PATH 已补充: {bin_dir}")

    click.echo("")
    click.echo("  验证安装...")
    out, _, rc = _run_hermes(["--version"])
    if rc == 0:
        click.echo(f"  ✅ Hermes Agent {out} 安装完成")
        click.echo("")

        # auto-sync sccsos.yaml model config → Hermes profile
        from sccsos.cli.hermes_config_sync import _auto_apply_config as _do_sync  # noqa: E402
        _do_sync()

        # ── 确保 rc 文件配置正确 ──
        # 若安装前因旧版区块（缺少 HERMES_CONFIG_PATH）被跳过，此时重写
        from sccsos.cli.hermes_install import _setup_shell_rc as _post_rc  # noqa: E402
        _post_rc(yes=True)

        # ── 连通性验证 ──
        click.echo("")
        click.echo("  验证配置...")
        from sccsos.cli.hermes_config_sync import _build_hermes_env as _do_build_env  # noqa: E402
        extra_env = _do_build_env()
        out, err, rc = _run_hermes(["-p", _get_hermes_config().profile or "sccsos",
                                     "-z", "ping"], timeout=30, extra_env=extra_env)
        if rc == 0:
            click.echo("  ✅ Hermes 配置验证通过")
        else:
            click.echo(f"  ⚠️  Hermes 配置验证失败: {err[:100]}")
            click.echo("     请运行: sccsos hermes setup")
            click.echo("")

        click.echo("后续步骤:")
        click.echo("  sccsos hermes setup              # 配置 API Key（如未设置环境变量）")
        click.echo("  sccsos hermes postinstall          # 安装 Browser 引擎等系统依赖")
        click.echo("  sccsos hermes doctor              # 验证安装完整性")
        click.echo("  sccsos health                     # 检查 SCCS OS 健康状态")
    else:
        click.echo("  ❌ 安装后验证失败，请检查日志")
