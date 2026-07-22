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
    """List available Hermes profiles via ``hermes profile list``."""
    out, _, rc = _run_hermes(["profile", "list"])
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


def _profile_exists(name: str) -> bool:
    """Check if a Hermes profile exists."""
    return name in _list_profiles()


def _create_profile(name: str) -> bool:
    """Create a Hermes profile via ``hermes profile create``."""
    out, _, rc = _run_hermes(["profile", "create", name], timeout=60)
    return rc == 0


def _set_profile_config(name: str, key: str, value: str) -> bool:
    """Set a config value in a Hermes profile via ``hermes -p <name> config set``."""
    out, _, rc = _run_hermes(["-p", name, "config", "set", key, value])
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
    binary = shutil.which("hermes")
    if binary:
        out, _, _ = _run_hermes(["--version"])
        click.echo(f"  ✅ Hermes CLI 已安装")
        click.echo(f"  Binary:   {binary}")
        click.echo(f"  Version:  {out or 'unknown'}")
        try:
            from sccsos.core.hermes_manager import get_manager
            inst = get_manager().discover()
            click.echo(f"  Mode:     {inst.mode.value}")
            if inst.home:
                click.echo(f"  Home:     {inst.home}")
        except Exception:
            pass
    else:
        click.echo("  ❌ Hermes CLI 未安装")
        click.echo("")
        click.echo("  安装: sccsos hermes install")


def _update_hermes_paths_in_yaml(home: str, code_path: str) -> None:
    """Update hermes.home and hermes.code_path in sccsos.yaml."""
    config_path = _get_config_path()
    if not config_path.exists():
        return
    import yaml
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    hermes = data.setdefault("hermes", {})
    changed = False
    if home and hermes.get("home") != home:
        hermes["home"] = home
        changed = True
    if code_path and hermes.get("code_path") != code_path:
        hermes["code_path"] = code_path
        changed = True
    if changed:
        config_path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        click.echo(f"  ✅ sccsos.yaml 已更新: hermes.home + hermes.code_path")


def _install_git(
    version: Optional[str],
    git_url: str,
    target: Optional[str],
    yes: bool,
    force: bool,
    home_override: Optional[str],
    code_path_override: Optional[str],
) -> None:
    """Install Hermes Agent via git clone + pip install -e."""
    hermes_home = home_override or _get_hermes_home()
    install_dir = target or str(Path(hermes_home) / "hermes-agent")
    install_path = Path(install_dir)
    final_code_path = code_path_override or install_dir

    click.echo(f"  Mode:     git")
    click.echo(f"  Repo:     {git_url}")
    click.echo(f"  Target:   {install_dir}")
    if version:
        click.echo(f"  Version:  {version}")

    if not shutil.which("git"):
        click.echo("  ❌ git 未安装，请先安装 git")
        return

    if install_path.exists() and (install_path / ".git").exists():
        click.echo("  → 更新已有仓库...")
        subprocess.run(
            ["git", "fetch", "--tags", "--force"],
            cwd=install_dir, capture_output=True, text=True, timeout=120,
        )
        if version:
            r = subprocess.run(
                ["git", "checkout", version],
                cwd=install_dir, capture_output=True, text=True, timeout=30,
            )
            if r.returncode != 0:
                click.echo(f"  ⚠️  checkout {version} 失败: {r.stderr.strip()[:100]}")
        else:
            r = subprocess.run(
                ["git", "pull"],
                cwd=install_dir, capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0:
                click.echo(f"  ⚠️  git pull 失败: {r.stderr.strip()[:100]}")
    elif install_path.exists() and not (install_path / ".git").exists():
        click.echo(f"  ❌ {install_dir} 已存在但不是 git 仓库")
        click.echo("     请删除后重试，或使用 --force")
        return
    else:
        click.echo("  → 克隆仓库（实时输出）...")
        install_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "clone", git_url, install_dir]
        if version:
            cmd += ["--branch", version]
        r = subprocess.run(cmd, timeout=180)
        if r.returncode != 0:
            click.echo(f"  ❌ git clone 失败（退出码 {r.returncode}）")
            return
        click.echo("  ✅ git clone 完成")

    click.echo("  → pip install -e .（实时输出，请耐心等待）...")
    click.echo("")
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", install_dir],
        timeout=300,
    )
    if r.returncode != 0:
        click.echo(f"  ❌ pip install -e 失败（退出码 {r.returncode}）")
        return
    click.echo("  ✅ pip install -e 完成")

    # ── 确保默认配置文件存在（install.sh 会自动生成，git 模式不会）──
    click.echo("  → 初始化默认配置...")
    _run_hermes(["profile", "list"], timeout=30)
    click.echo("  ✅ 默认配置已初始化")

    _update_hermes_paths_in_yaml(hermes_home, final_code_path)


def _install_script(china_mirror: bool, yes: bool, timeout: int = 600,
                    home: str = "", code_path: str = "") -> bool:
    """Install Hermes Agent via official one-click install script.

    Uses the upstream install.sh which auto-configures venv, deps, and CLI.
    After success, writes detected home/code_path back to sccsos.yaml.
    """
    url = (
        "https://res1.hermesagent.org.cn/install.sh"
        if china_mirror else
        "https://hermes-agent.nousresearch.com/install.sh"
    )
    click.echo(f"  Mode:     script")
    click.echo(f"  URL:      {url}")
    if not yes:
        click.echo("")
        if not click.confirm("  确认安装?"):
            click.echo("  已取消。")
            return False
    click.echo("  → 下载并执行安装脚本（实时输出，请耐心等待）...")
    click.echo("")
    try:
        r = subprocess.run(
            ["bash", "-c", f"curl -fL --progress-bar {url} | bash"],
            timeout=timeout,
        )
        if r.returncode != 0:
            click.echo(f"  ❌ 安装失败（退出码 {r.returncode}），请检查网络后重试")
            return False
        click.echo("")
        click.echo("  ✅ 一键脚本安装完成")
    except subprocess.TimeoutExpired:
        click.echo(f"  ❌ 安装超时（{timeout}s），请检查网络后重试")
        return False
    except Exception as e:
        click.echo(f"  ❌ 安装异常: {str(e)[:100]}")
        return False

    # ── 安装成功后写回 sccsos.yaml ──
    detected_home = home or _get_hermes_home()
    detected_code = code_path or _get_hermes_code_path()
    if not detected_home:
        detected_home = str(Path.home() / ".hermes")
    if not detected_code:
        detected_code = str(Path(detected_home) / "hermes-agent")
    _update_hermes_paths_in_yaml(detected_home, detected_code)
    return True


def _install_docker(version: Optional[str], yes: bool, force: bool,
                    home: str = "", code_path: str = "",
                    china_mirror: bool = False) -> bool:
    """Install Hermes Agent via Docker image pull.

    After success, writes detected home/code_path back to sccsos.yaml.
    """
    tag = version or "latest"
    image = (
        f"docker.xuanyuan.run/nousresearch/hermes-agent:{tag}"
        if china_mirror else
        f"nousresearch/hermes-agent:{tag}"
    )
    click.echo(f"  Mode:     docker")
    click.echo(f"  Image:    {image}")
    if not shutil.which("docker"):
        click.echo("  ❌ docker 未安装，请先安装 Docker")
        return False
    if not yes:
        click.echo("")
        if not click.confirm("  确认拉取?"):
            click.echo("  已取消。")
            return False
    click.echo("  → 拉取 Docker 镜像（实时输出，请耐心等待）...")
    click.echo("")
    r = subprocess.run(
        ["docker", "pull", image],
        timeout=600,
    )
    if r.returncode != 0:
        click.echo(f"  ❌ 拉取失败（退出码 {r.returncode}）")
        return False
    click.echo(f"  ✅ Docker 镜像拉取完成: {image}")
    # Show image size
    r2 = subprocess.run(
        ["docker", "images", image, "--format", "{{.Size}}"],
        capture_output=True, text=True, timeout=10,
    )
    if r2.returncode == 0 and r2.stdout.strip():
        click.echo(f"     大小: {r2.stdout.strip()}")

    # ── 写回 sccsos.yaml ──
    detected_home = home or _get_hermes_home() or str(Path.home() / ".hermes")
    detected_code = code_path or _get_hermes_code_path() or str(Path(detected_home) / "hermes-agent")
    _update_hermes_paths_in_yaml(detected_home, detected_code)
    return True


def _set_default_config(key: str, value: str) -> bool:
    """Set a config value in the default Hermes config (~/.hermes/config.yaml)."""
    out, _, rc = _run_hermes(["config", "set", key, value])
    return rc == 0


def _ensure_env_file(profile_name: str, provider: str, api_key: str, base_url: str = "") -> None:
    """Write API key and base URL to the Hermes ``.env`` file for a profile.

    Hermes v0.18 stores secrets in ``.env`` (default: ``~/.hermes/.env``,
    profile: ``~/.hermes/profiles/<name>/.env``).  This function
    adds or replaces the ``PROVIDER_API_KEY`` and ``PROVIDER_BASE_URL``
    lines so the key is available to Hermes at runtime.
    """
    if not api_key:
        return

    # Resolve .env path: default or profile
    cfg_path = _get_profile_config_path(profile_name)
    env_path = cfg_path.parent / ".env"

    key_var = f"{provider.upper()}_API_KEY"
    url_var = f"{provider.upper()}_BASE_URL"
    new_lines: list[str] = []
    key_found = url_found = False

    # Read existing .env if present
    if env_path.exists():
        existing = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
        for line in existing:
            stripped = line.strip()
            if stripped.startswith(f"{key_var}="):
                new_lines.append(f"{key_var}={api_key}\n")
                key_found = True
            elif base_url and stripped.startswith(f"{url_var}="):
                new_lines.append(f"{url_var}={base_url}\n")
                url_found = True
            else:
                new_lines.append(line)
    else:
        env_path.parent.mkdir(parents=True, exist_ok=True)

    # Append if not found
    if not key_found:
        new_lines.append(f"\n# sccsos: {provider} API Key\n" if not env_path.exists() else "")
        new_lines.append(f"{key_var}={api_key}\n")
    if base_url and not url_found:
        new_lines.append(f"{url_var}={base_url}\n")

    env_path.write_text("".join(new_lines), encoding="utf-8")
    # Restrict permissions (same as Hermes defaults)
    env_path.chmod(0o600)


def _write_model_config(target_fn, model: str, provider: str, base_url: str,
                        api_key: str = "") -> bool:
    """Write model.default/provider/base_url to a config target.

    ``target_fn`` is either ``_set_default_config`` or ``_set_profile_config``
    with the profile name already curried/bound.
    """
    ok = target_fn("model.default", model)
    ok = target_fn("model.provider", provider) and ok
    if base_url:
        ok = target_fn("model.base_url", base_url) and ok
    if api_key:
        ok = target_fn("model.api_key", api_key) and ok
    return ok


def _verify_model_config(config_path: Path) -> dict:
    """Inspect a Hermes config file and return a dict with model status.

    Returns::
        {"exists": bool, "is_dict": bool, "model": dict, "errors": [str]}
    """
    result: dict = {"exists": False, "is_dict": False, "model": {}, "errors": []}
    if not config_path.exists():
        result["errors"].append(f"文件不存在: {config_path}")
        return result
    result["exists"] = True
    try:
        import yaml
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        m = data.get("model", {})
        if isinstance(m, dict):
            result["is_dict"] = True
            result["model"] = m
            for k in ["default", "provider"]:
                if not m.get(k):
                    result["errors"].append(f"model.{k} 未设置")
        else:
            result["errors"].append(f"model 是 {type(m).__name__}（应为 dict），值: {m!r}")
    except Exception as e:
        result["errors"].append(f"解析失败: {e}")
    return result


def _get_profile_config_path(profile_name: str) -> Path:
    """Get the filesystem path to a Hermes profile's config.yaml.

    Resolves the Hermes home root by checking the effective HERMES_HOME,
    then walking up if it points inside a ``profiles/`` subdirectory
    (e.g. when ``HERMES_HOME`` resolves to a profile directory).
    """
    hermes_home = Path(_get_hermes_home())
    # If hermes_home looks like it's inside a profiles/<name> dir, walk up
    if hermes_home.name != ".hermes" and hermes_home.parent.name == "profiles":
        hermes_home = hermes_home.parent.parent
    elif not (hermes_home / "config.yaml").exists() and not (hermes_home / "profiles").exists():
        # Fall back to the parent if the resolved home doesn't look like the root
        hermes_home = hermes_home.parent
    if profile_name == "default":
        return hermes_home / "config.yaml"
    return hermes_home / "profiles" / profile_name / "config.yaml"


# ── Post-install config sync ────────────────────────────────────────


def _auto_apply_config() -> None:
    """Auto-sync sccsos.yaml model config to Hermes after install.

    Strategy:
    1. Write model.default/provider/base_url/api_key to the **default** config
       (~/.hermes/config.yaml) — always, as fallback.
    2. If sccsos.yaml hermes.profile differs from "default",
       clone the config to that profile (create if missing).
    3. Verify both configs are valid dict structures and consistent.

    API key resolution: sccsos.yaml > provider env var (DEEPSEEK_API_KEY etc.)
    """
    try:
        cfg = _get_hermes_config()
        provider = cfg.setup.provider
        model = cfg.setup.model
        if not provider or not model:
            return

        profile_name = cfg.profile or "sccsos"
        base_url = cfg.setup.base_url or PROVIDER_DEFAULT_URLS.get(provider, "")
        api_key = cfg.setup.api_key or _get_env_api_key(provider) or ""
        click.echo("  → 自动同步配置文件...")

        # Step 1: Write to default config
        default_path = _get_profile_config_path("default")
        ok = _write_model_config(_set_default_config, model, provider, base_url, api_key)
        if not ok:
            click.echo("  ⚠️  默认配置写入异常，请检查 Hermes CLI 状态")
            return
        click.echo(f"  ✅ 默认配置已更新: {provider} / {model}")

        # Step 2: Clone to target profile
        if profile_name != "default":
            if not _profile_exists(profile_name):
                if not _create_profile(profile_name):
                    click.echo(f"  ⚠️  Profile '{profile_name}' 创建失败，跳过")
                    return

                # Clone all default config keys to the new profile
                import yaml as _yaml
                _default_path = _get_profile_config_path("default")
                if _default_path.exists():
                    try:
                        _default_data = _yaml.safe_load(
                            _default_path.read_text(encoding="utf-8")
                        ) or {}
                        # Remove model section — will be overwritten below
                        _default_data.pop("model", None)
                        _prof_path = _get_profile_config_path(profile_name)
                        _prof_path.parent.mkdir(parents=True, exist_ok=True)
                        _prof_path.write_text(
                            _yaml.dump(_default_data, allow_unicode=True, default_flow_style=False),
                            encoding="utf-8",
                        )
                        click.echo(f"  ✅ Profile '{profile_name}' 已创建（完整克隆自默认配置）")
                    except Exception as _e:
                        click.echo(f"  ⚠️  默认配置克隆失败: {_e}")

                # Clone .env from default profile
                _default_env = _get_profile_config_path("default").parent / ".env"
                if _default_env.exists():
                    try:
                        _prof_env_parent = _get_profile_config_path(profile_name).parent
                        _prof_env_parent.mkdir(parents=True, exist_ok=True)
                        _prof_env = _prof_env_parent / ".env"
                        _prof_env.write_text(_default_env.read_text(encoding="utf-8"), encoding="utf-8")
                        _prof_env.chmod(0o600)
                        click.echo(f"  ✅ Profile '.env' 已克隆")
                    except Exception as _e:
                        click.echo(f"  ⚠️  .env 克隆失败: {_e}")

            prof_path = _get_profile_config_path(profile_name)
            ok = _write_model_config(
                lambda k, v: _set_profile_config(profile_name, k, v),
                model, provider, base_url, api_key,
            )
            if not ok:
                click.echo(f"  ⚠️  Profile '{profile_name}' 写入异常")
                return
            click.echo(f"  ✅ Profile '{profile_name}' 已同步")

        # Step 2b: Sync .env files with API key and base URL
        if api_key:
            _ensure_env_file("default", provider, api_key,
                             cfg.setup.base_url or PROVIDER_DEFAULT_URLS.get(provider, ""))
            if profile_name != "default":
                _ensure_env_file(profile_name, provider, api_key,
                                 cfg.setup.base_url or PROVIDER_DEFAULT_URLS.get(provider, ""))
            click.echo("  ✅ .env 密钥文件已同步")

        # Step 3: Verify both configs
        errors = []
        for label, path in [("默认配置", default_path),
                            (f"Profile '{profile_name}'", _get_profile_config_path(profile_name))]:
            v = _verify_model_config(path)
            if v["errors"]:
                errors.extend([f"{label}: {e}" for e in v["errors"]])
            elif v["is_dict"]:
                url = v["model"].get("base_url", "")
                has_key = bool(v["model"].get("api_key"))
                detail = f"{v['model'].get('provider')} / {v['model'].get('default')}"
                if url:
                    detail += f" / {url}"
                if has_key:
                    detail += " 🔑"
                click.echo(f"  ✅ {label} 结构正确: {detail}")

        # Cross-check consistency
        if profile_name != "default":
            dv = _verify_model_config(default_path)
            pv = _verify_model_config(_get_profile_config_path(profile_name))
            if dv["is_dict"] and pv["is_dict"]:
                for k in ["default", "provider", "base_url", "api_key"]:
                    # api_key is allowed to differ: default config uses Hermes secrets
                    # store (.env), while profile stores it in config.yaml
                    if k == "api_key" and not dv["model"].get(k) and pv["model"].get(k):
                        continue
                    if dv["model"].get(k) != pv["model"].get(k):
                        errors.append(
                            f"model.{k} 不一致: 默认={dv['model'].get(k)!r} ≠ "
                            f"profile={pv['model'].get(k)!r}")

        if errors:
            click.echo(f"  ⚠️  配置不一致 ({len(errors)} 项):")
            for e in errors:
                click.echo(f"    {e}")
        else:
            click.echo("  ✅ 默认配置 ↔ Profile 一致")
        click.echo("")

    except Exception as e:
        click.echo(f"  ⚠️  自动配置跳过: {e}")


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

hermes_cmd.add_command(show)
hermes_cmd.add_command(setup)
hermes_cmd.add_command(use)




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
@click.option("--code-path", default=None,
              help="写入 sccsos.yaml 的 HERMES_CODE_PATH 路径")
def install(method, version, git_url, target, check, yes, force, home, code_path, china_mirror):
    """Install Hermes Agent on this machine.

    三种安装方式：

    \\b
    - script（默认）：一键在线脚本，自动配置环境，新手首选
    - git：源码编译安装，适合二次开发
    - docker：Docker 容器部署，适合生产环境

    安装完成后运行 ``sccsos hermes setup`` 配置 LLM Provider 和 API Key。
    """
    click.echo("── SCCS OS — Hermes Agent 安装 ──")
    click.echo("")

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

    # ── 解析 home / code_path：CLI 参数 > sccsos.yaml > 默认 ──
    resolved_home = home or _get_hermes_home()
    resolved_code_path = code_path or _get_hermes_code_path()
    if resolved_home:
        click.echo(f"  HERMES_HOME:  {resolved_home}")
    if resolved_code_path:
        click.echo(f"  Code Path:    {resolved_code_path}")
    click.echo("")

    # ── 执行安装 ──
    if method == "script":
        _install_script(china_mirror, yes, home=resolved_home, code_path=resolved_code_path)
    elif method == "git":
        # china-mirror 时自动切换 git 源
        resolved_git_url = git_url
        if china_mirror and git_url == "https://github.com/NousResearch/hermes-agent.git":
            resolved_git_url = "https://cnb.cool/hermesagent-cn/hermes-agent-cn-mirror.git"
            click.echo(f"  ↪ 使用国内镜像: {resolved_git_url}")
        _install_git(version, resolved_git_url, target, yes, force, resolved_home, resolved_code_path)
    elif method == "docker":
        _install_docker(version, yes, force, home=resolved_home, code_path=resolved_code_path, china_mirror=china_mirror)

    # ── 安装后验证 ──
    click.echo("")
    click.echo("  验证安装...")
    out, _, rc = _run_hermes(["--version"])
    if rc == 0:
        click.echo(f"  ✅ Hermes Agent {out} 安装完成")
        click.echo("")

        # auto-sync sccsos.yaml model config → Hermes profile
        _auto_apply_config()

        click.echo("后续步骤:")
        click.echo("  sccsos hermes setup              # 配置 API Key（如未设置环境变量）")
        click.echo("  sccsos hermes postinstall          # 安装 Browser 引擎等系统依赖")
        click.echo("  sccsos hermes doctor              # 验证安装完整性")
        click.echo("  sccsos health                     # 检查 SCCS OS 健康状态")
    else:
        click.echo("  ❌ 安装后验证失败，请检查日志")
