"""Hermes Agent install commands.

Extracted from :mod:`sccsos.cli.hermes_cmd` for modularity.
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

# ── Shared helpers from hermes_cmd ─────────────────────────────────
from sccsos.cli.hermes_cmd import (
    PROVIDER_DEFAULT_URLS,
    _create_profile,
    _get_config_path,
    _get_hermes_config,
    _get_hermes_home,
    _get_hermes_install_dir,
    _get_uv_install_dir,
    _get_uv_cache_dir,
    _profile_exists,
    _run_hermes,
    _set_profile_config,
)

logger = get_logger()


# ── Install helpers ─────────────────────────────────────────────────


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


def _update_hermes_paths_in_yaml(home: str, install_dir: str) -> None:
    """Update hermes.home and (optionally) hermes.install_dir in sccsos.yaml."""
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
    if install_dir:
        if hermes.get("install_dir") != install_dir:
            hermes["install_dir"] = install_dir
            changed = True
    else:
        if "install_dir" in hermes:
            del hermes["install_dir"]
            changed = True
    if changed:
        config_path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        click.echo("  ✅ sccsos.yaml 已更新: hermes.home + hermes.install_dir")


def _install_git(
    version: Optional[str],
    git_url: str,
    target: Optional[str],
    yes: bool,
    force: bool,
    home_override: Optional[str],
    install_dir_override: Optional[str],
    uv_install_dir: str = "",
    uv_cache_dir: str = "",
) -> None:
    """Install Hermes Agent via git clone + pip install -e."""
    hermes_home = home_override or _get_hermes_home()
    install_dir = target or str(Path(hermes_home) / "hermes-agent")
    install_path = Path(install_dir)
    final_install_dir = install_dir_override or install_dir
    final_uv_install = uv_install_dir or _get_uv_install_dir()
    final_uv_cache = uv_cache_dir or _get_uv_cache_dir()

    click.echo(f"  Mode:     git")
    click.echo(f"  Repo:     {git_url}")
    click.echo(f"  Target:   {install_dir}")
    if hermes_home:
        click.echo(f"  Home:     {hermes_home}")
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
    pip_env = os.environ.copy()
    pip_env["HERMES_HOME"] = hermes_home
    pip_env["HERMES_CONFIG_PATH"] = hermes_home
    pip_env["HERMES_INSTALL_DIR"] = final_install_dir
    pip_env["UV_INSTALL_DIR"] = final_uv_install
    pip_env["UV_CACHE_DIR"] = final_uv_cache
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", install_dir],
        timeout=300,
        env=pip_env,
    )
    if r.returncode != 0:
        click.echo(f"  ❌ pip install -e 失败（退出码 {r.returncode}）")
        return
    click.echo("  ✅ pip install -e 完成")

    _update_hermes_paths_in_yaml(hermes_home, final_install_dir)

    # 创建 HERMES_HOME 目录结构（如使用自定义路径且不存在）
    _ensure_hermes_home(hermes_home)

    # 初始化默认 profile 配置
    _run_hermes(["profile", "list"], timeout=30)


def _ensure_hermes_home(home_path: str) -> None:
    """Create HERMES_HOME directory structure if it doesn't exist.

    Also creates the companion directories for the ``$HOME/hermes``
    fully-enclosed pattern (agent/, data/, data/uv-cache/).
    """
    hp = Path(home_path)
    if hp.exists():
        return
    click.echo(f"  → 创建 HERMES_HOME 目录结构: {home_path}")

    # Core HERMES_HOME subdirs
    for sub in ["config", "logs", "data", "sessions", "skills", "memory", "plugins", "pid"]:
        (hp / sub).mkdir(parents=True, exist_ok=True)

    # Companion directories for fully-enclosed pattern
    hermes_root = hp.parent  # $HOME/hermes when hp = $HOME/hermes/data
    if hermes_root.name == "hermes" and hermes_root.parent == Path.home():
        (hermes_root / "agent" / "venv" / "bin").mkdir(parents=True, exist_ok=True)
        (hermes_root / "agent" / "lib").mkdir(parents=True, exist_ok=True)
        (hp / "bin").mkdir(parents=True, exist_ok=True)       # UV_INSTALL_DIR
        (hp / "uv-cache" / "archives").mkdir(parents=True, exist_ok=True)
        (hp / "uv-cache" / "git").mkdir(parents=True, exist_ok=True)
        click.echo(f"  ✅ $HOME/hermes 全封闭目录结构已创建")

    # 写入最小 config.yaml
    cfg = hp / "config.yaml"
    if not cfg.exists():
        cfg.write_text(
            "active_profile: sccsos\nmodel:\n  default: deepseek-v4-flash\n  provider: deepseek\n",
            encoding="utf-8",
        )
    click.echo(f"  ✅ HERMES_HOME 已创建")


def _detect_shell_rc() -> str:
    """Detect the user's shell rc file based on OS and $SHELL.

    Returns the first existing rc file, or falls back to the most
    appropriate location for the detected OS/shell, creating it if
    the file does not already exist.
    """
    shell = os.environ.get("SHELL", "")

    # Build candidate list by OS/shell
    candidates: list[str] = []
    if "zsh" in shell:
        candidates = [".zshrc", ".zprofile"]
    elif "bash" in shell:
        if sys.platform == "darwin":
            candidates = [".bash_profile", ".bashrc", ".zshrc"]
        else:
            candidates = [".bashrc", ".bash_profile"]
    elif "fish" in shell:
        return str(Path.home() / ".config" / "fish" / "config.fish")
    else:
        # SHELL not set or unknown — use platform defaults
        if sys.platform == "darwin":
            candidates = [".zshrc", ".bash_profile", ".bashrc"]
        else:
            candidates = [".bashrc", ".zshrc", ".profile"]

    # Return the first existing rc file
    for c in candidates:
        rc = Path.home() / c
        if rc.exists():
            return str(rc)

    # No rc file exists yet — create the best candidate
    best = candidates[0]
    rc_path = Path.home() / best
    rc_path.parent.mkdir(parents=True, exist_ok=True)
    rc_path.touch()
    return str(rc_path)


def _export_current_session(
    home: str, install_dir: str,
    hermes_bin: str, hermes_bin_dir: str,
    uv_bin: str, uv_cache: str,
) -> None:
    """Export Hermes env vars to the current shell session (os.environ)."""
    export_home = os.path.expandvars(home)
    export_install = os.path.expandvars(install_dir)
    os.environ["HERMES_HOME"] = export_home
    os.environ["HERMES_CONFIG_PATH"] = export_home
    os.environ["HERMES_INSTALL_DIR"] = export_install
    os.environ["HERMES_BIN"] = os.path.expandvars(hermes_bin)
    os.environ["HERMES_BIN_DIR"] = os.path.expandvars(hermes_bin_dir)
    os.environ["UV_INSTALL_DIR"] = os.path.expandvars(uv_bin)
    os.environ["UV_CACHE_DIR"] = os.path.expandvars(uv_cache)
    click.echo("  ✅ 当前会话已生效")


def _setup_shell_rc(rc_file: str = "", yes: bool = False,
                    home: str = "", install_dir: str = "") -> bool:
    """Write Hermes core environment variables to the user's shell rc file.

    When ``home`` or ``install_dir`` are provided, those values are used
    in the env block instead of the default ``$HOME/hermes/data`` /
    ``$HOME/hermes/agent`` paths.

    Returns True if changes were made.
    """
    rc_path = Path(rc_file) if rc_file else Path(_detect_shell_rc())

    # Resolve paths: parameter > default shell-var pattern
    # NOTE: for shell rc files we deliberately use shell variable references
    # ($HOME, $HERMES_HOME, $PATH) rather than resolving from the current
    # environment — the rc file defines defaults; actual values are resolved
    # by the shell at login time.
    resolved_home = home or "$HOME/hermes/data"
    resolved_install = install_dir or "$HOME/hermes/agent"
    resolved_uv_bin = "$HERMES_HOME/bin"
    resolved_uv_cache = "$HERMES_HOME/uv-cache"
    resolved_path = "$HERMES_INSTALL_DIR/venv/bin:$HERMES_HOME/bin:$PATH"
    resolved_bin = "$HERMES_INSTALL_DIR/venv/bin/hermes"
    resolved_bin_dir = "$HERMES_INSTALL_DIR/venv/bin"

    env_block = f"""
# ── Hermes Agent 全封闭安装环境变量 ──
export HERMES_HOME="{resolved_home}"
export HERMES_CONFIG_PATH="{resolved_home}"
export HERMES_INSTALL_DIR="{resolved_install}"
export HERMES_BIN="{resolved_bin}"
export HERMES_BIN_DIR="{resolved_bin_dir}"
export UV_INSTALL_DIR="{resolved_uv_bin}"
export UV_CACHE_DIR="{resolved_uv_cache}"
export PATH="{resolved_path}"
# ── ──
"""
    if rc_path.exists():
        existing = rc_path.read_text(encoding="utf-8")
        if "HERMES_INSTALL_DIR" in existing and "HERMES_CONFIG_PATH" in existing:
            click.echo(f"  ⏭ Hermes 环境变量已在 {rc_path.name} 中存在，跳过 rc 写入")
            # 跳过 rc 写入，但仍导出到当前会话（确保 HERMES_BIN/BIN_DIR 生效）
            _export_current_session(resolved_home, resolved_install,
                                     resolved_bin, resolved_bin_dir,
                                     resolved_uv_bin, resolved_uv_cache)
            return True

    if not yes:
        if not click.confirm(f"  将 Hermes 环境变量写入 {rc_path.name}?\\n"
                             f"    路径: {rc_path}"):
            click.echo("  已跳过 Shell RC 配置")
            return False

    rc_path.parent.mkdir(parents=True, exist_ok=True)
    with open(rc_path, "a", encoding="utf-8") as f:
        f.write(env_block)
    click.echo(f"  ✅ 环境变量已写入 {rc_path.name}")
    click.echo(f"     路径: {rc_path}")

    # Export to current shell session immediately
    _export_current_session(resolved_home, resolved_install,
                            resolved_bin, resolved_bin_dir,
                            resolved_uv_bin, resolved_uv_cache)
    return True


def _install_script(china_mirror: bool, yes: bool, timeout: int = 600,
                    home: str = "", install_dir: str = "",
                    uv_install_dir: str = "", uv_cache_dir: str = "") -> bool:
    """Install Hermes Agent via official one-click install script.

    Uses the upstream install.sh which auto-configures venv, deps, and CLI.
    After success, writes detected home/install_dir back to sccsos.yaml.
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
        # Always resolve and forward ALL environment variables to install.sh
        env = os.environ.copy()
        resolved_home = home or _get_hermes_home()
        resolved_install = install_dir or _get_hermes_install_dir()
        resolved_uv_bin = uv_install_dir or _get_uv_install_dir()
        resolved_uv_cache = uv_cache_dir or _get_uv_cache_dir()

        env["HERMES_HOME"] = resolved_home
        env["HERMES_CONFIG_PATH"] = resolved_home
        env["HERMES_INSTALL_DIR"] = resolved_install
        env["UV_INSTALL_DIR"] = resolved_uv_bin
        env["UV_CACHE_DIR"] = resolved_uv_cache
        click.echo(f"  ↪ HERMES_HOME={resolved_home}")
        click.echo(f"  ↪ HERMES_CONFIG_PATH={resolved_home}")
        click.echo(f"  ↪ HERMES_INSTALL_DIR={resolved_install}")
        click.echo(f"  ↪ UV_INSTALL_DIR={resolved_uv_bin}")
        click.echo(f"  ↪ UV_CACHE_DIR={resolved_uv_cache}")
        # Retry loop for transient network failures
        max_attempts = 3
        last_rc = -1
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                wait = min(2 ** (attempt - 1), 10)
                click.echo(f"  → 重试 {attempt}/{max_attempts}（等待 {wait}s）...")
                import time as _time
                _time.sleep(wait)
            r = subprocess.run(
                ["bash", "-c", f"curl -fL --progress-bar {url} | bash -s -- --skip-setup"],
                timeout=timeout, env=env,
            )
            if r.returncode == 0:
                last_rc = 0
                break
            last_rc = r.returncode
            click.echo(f"  ⚠️  第 {attempt} 次失败（退出码 {r.returncode}）")
        if last_rc != 0:
            click.echo(f"  ❌ 安装失败（退出码 {last_rc}），请检查网络后重试")
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
    detected_install = install_dir or _get_hermes_install_dir()
    if not detected_home:
        detected_home = str(Path.home() / ".hermes")
    _update_hermes_paths_in_yaml(detected_home, detected_install)
    # 如使用了自定义路径且 install.sh 未自动创建，补建目录结构
    if home:
        _ensure_hermes_home(home)
    return True


def _install_docker(version: Optional[str], yes: bool, force: bool,
                    home: str = "", install_dir: str = "",
                    uv_install_dir: str = "", uv_cache_dir: str = "",
                    china_mirror: bool = False) -> bool:
    """Install Hermes Agent via Docker image pull.

    After success, writes detected home/install_dir back to sccsos.yaml.
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
    detected_install = install_dir or _get_hermes_install_dir()
    _update_hermes_paths_in_yaml(detected_home, detected_install)
    return True


def _set_default_config(key: str, value: str) -> bool:
    """Set a config value in the default Hermes config (~/.hermes/config.yaml)."""
    out, _, rc = _run_hermes(["config", "set", key, value])
    return rc == 0


def _write_model_config(target_fn, model: str, provider: str, base_url: str) -> bool:
    """Write model.default/provider/base_url to a config target.

    ``target_fn`` is either ``_set_default_config`` or ``_set_profile_config``
    with the profile name already curried/bound.
    """
    ok = target_fn("model.default", model)
    ok = target_fn("model.provider", provider) and ok
    if base_url:
        ok = target_fn("model.base_url", base_url) and ok
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


# ── CLI command ─────────────────────────────────────────────────────


@click.option("--install-dir", default=None,
              help="写入 sccsos.yaml 的 HERMES_INSTALL_DIR 路径")
@click.option("--home", default=None,
              help="写入 sccsos.yaml 的 HERMES_HOME 路径")
@click.option("--force", "-f", is_flag=True, help="强制重新安装")
@click.option("--yes", "-y", is_flag=True, help="跳过确认提示")
@click.option("--check", "-c", is_flag=True, help="仅检查安装状态，不安装")
@click.option("--target", "-t", default=None,
              help="安装目标目录（git 模式，默认 {HERMES_HOME}/hermes-agent）")
@click.option("--git-url", default="https://github.com/NousResearch/hermes-agent.git",
              help="Git 仓库地址（git 模式，--china-mirror 时自动切换）", show_default=True)
@click.option("--china-mirror", is_flag=True,
              help="使用国内镜像加速（script 模式 + git 模式 + docker 模式）")
@click.option("--version", "-v", default=None,
              help="版本标签（git: checkout, docker: image tag）")
@click.option("--method", "-m", default="script", type=click.Choice(["script", "git", "docker"]),
              help="安装方式（默认 script：一键安装脚本）")
@click.option("--shell-rc/--no-shell-rc", default=None,
              help="安装后自动配置 Shell 环境变量（默认从 sccsos.yaml 读取 auto_setup）")
def install(method, version, git_url, target, check, yes, force, home, install_dir, shell_rc, china_mirror):
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
    if sys.platform == "win32":
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
    resolved_install_dir = install_dir or _get_hermes_install_dir()
    resolved_uv_bin = _get_uv_install_dir()
    resolved_uv_cache = _get_uv_cache_dir()
    if resolved_home:
        click.echo(f"  HERMES_HOME:            {resolved_home}")
    if resolved_install_dir:
        click.echo(f"  HERMES_INSTALL_DIR:  {resolved_install_dir}")
        resolved_bin = f"{resolved_install_dir}/venv/bin/hermes"
        resolved_bin_dir = f"{resolved_install_dir}/venv/bin"
        click.echo(f"  HERMES_BIN:             {resolved_bin}")
        click.echo(f"  HERMES_BIN_DIR:         {resolved_bin_dir}")
    click.echo(f"  UV_INSTALL_DIR:         {resolved_uv_bin}")
    click.echo(f"  UV_CACHE_DIR:           {resolved_uv_cache}")
    click.echo("")

    # ── Shell RC 配置（安装前设置，确保后续终端会话可用） ──
    # 安装流程中用户已确认安装，不重复弹窗确认
    do_shell_rc = shell_rc if shell_rc is not None else None
    if do_shell_rc is None:
        try:
            from sccsos.core.config import get_config
            do_shell_rc = get_config().hermes.shell_rc.auto_setup
        except Exception:
            do_shell_rc = True
    if do_shell_rc:
        click.echo("")
        click.echo("  ── Shell 环境变量配置 ──")
        _setup_shell_rc(yes=True, home=resolved_home,
                        install_dir=resolved_install_dir)

    # ── 执行安装 ──
    if method == "script":
        _install_script(china_mirror, yes, home=resolved_home,
                        install_dir=resolved_install_dir,
                        uv_install_dir=resolved_uv_bin, uv_cache_dir=resolved_uv_cache)
    elif method == "git":
        # china-mirror 时自动切换 git 源
        resolved_git_url = git_url
        if china_mirror and git_url == "https://github.com/NousResearch/hermes-agent.git":
            resolved_git_url = "https://cnb.cool/hermesagent-cn/hermes-agent-cn-mirror.git"
            click.echo(f"  ↪ 使用国内镜像: {resolved_git_url}")
        _install_git(version, resolved_git_url, target, yes, force,
                     resolved_home, resolved_install_dir,
                     uv_install_dir=resolved_uv_bin, uv_cache_dir=resolved_uv_cache)
    elif method == "docker":
        _install_docker(version, yes, force,
                        home=resolved_home, install_dir=resolved_install_dir,
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
    # ── 🪵 trace ──
    from sccsos.cli.hermes_cmd import _trace_env
    _trace_env("D-安装后")

    click.echo("")
    click.echo("  验证安装...")
    out, _, rc = _run_hermes(["--version"])
    if rc == 0:
        click.echo(f"  ✅ Hermes Agent {out} 安装完成")
        click.echo("")

        # auto-sync sccsos.yaml model config → Hermes profile
        # ── 🪵 trace ──
        from sccsos.cli.hermes_cmd import _trace_env as _te
        _te("E-config-sync前")
        from sccsos.cli.hermes_config_sync import _auto_apply_config as _do_sync  # noqa: E402
        _do_sync()

        click.echo("")
        click.echo("后续步骤:")
        click.echo("  source {}              # 立即激活环境变量".format(
            _detect_shell_rc() if not shell_rc else shell_rc,
        ))
        click.echo("  sccsos hermes setup              # 配置 API Key（如未设置环境变量）")
        click.echo("  sccsos hermes postinstall          # 安装 Browser 引擎等系统依赖")
        click.echo("  sccsos hermes doctor              # 验证安装完整性")
        click.echo("  sccsos health                     # 检查 SCCS OS 健康状态")
    else:
        click.echo("  ❌ 安装后验证失败，请检查日志")
