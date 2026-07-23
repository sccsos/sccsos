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
    _get_hermes_install_prefix,
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


def _update_hermes_paths_in_yaml(home: str, install_prefix: str) -> None:
    """Update hermes.home and (optionally) hermes.install_prefix in sccsos.yaml."""
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
    if install_prefix:
        if hermes.get("install_prefix") != install_prefix:
            hermes["install_prefix"] = install_prefix
            changed = True
    else:
        if "install_prefix" in hermes:
            del hermes["install_prefix"]
            changed = True
    if changed:
        config_path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        click.echo("  ✅ sccsos.yaml 已更新: hermes.home + hermes.install_prefix")


def _install_git(
    version: Optional[str],
    git_url: str,
    target: Optional[str],
    yes: bool,
    force: bool,
    home_override: Optional[str],
    install_prefix_override: Optional[str],
) -> None:
    """Install Hermes Agent via git clone + pip install -e."""
    hermes_home = home_override or _get_hermes_home()
    install_dir = target or str(Path(hermes_home) / "hermes-agent")
    install_path = Path(install_dir)
    final_install_prefix = install_prefix_override or install_dir

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
    if hermes_home:
        pip_env["HERMES_HOME"] = hermes_home
    if final_install_prefix:
        pip_env["HERMES_INSTALL_PREFIX"] = final_install_prefix
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", install_dir],
        timeout=300,
        env=pip_env,
    )
    if r.returncode != 0:
        click.echo(f"  ❌ pip install -e 失败（退出码 {r.returncode}）")
        return
    click.echo("  ✅ pip install -e 完成")

    _update_hermes_paths_in_yaml(hermes_home, final_install_prefix)

    # 创建 HERMES_HOME 目录结构（如使用自定义路径且不存在）
    _ensure_hermes_home(hermes_home)


def _ensure_hermes_home(home_path: str) -> None:
    """Create HERMES_HOME directory structure if it doesn't exist.

    Also creates the companion directories for the ``$HOME/hermes``
    fully-enclosed pattern (install/, runtime/, uv-cache/).
    """
    hp = Path(home_path)
    if hp.exists():
        return
    click.echo(f"  → 创建 HERMES_HOME 目录结构: {home_path}")

    # Core HERMES_HOME subdirs
    for sub in ["config", "logs", "data", "sessions", "skills", "memory", "plugins", "pid", "bin"]:
        (hp / sub).mkdir(parents=True, exist_ok=True)

    # Companion directories for fully-enclosed pattern
    hermes_root = hp.parent  # $HOME/hermes when hp = $HOME/hermes/runtime
    if hermes_root.name == "hermes" and hermes_root.parent == Path.home():
        (hermes_root / "install" / "bin").mkdir(parents=True, exist_ok=True)
        (hermes_root / "install" / "venv").mkdir(parents=True, exist_ok=True)
        (hermes_root / "install" / "lib").mkdir(parents=True, exist_ok=True)
        (hermes_root / "uv-cache" / "archives").mkdir(parents=True, exist_ok=True)
        (hermes_root / "uv-cache" / "git").mkdir(parents=True, exist_ok=True)
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
    """Detect the user's shell rc file based on OS and $SHELL."""
    shell = os.environ.get("SHELL", "")
    if "zsh" in shell:
        candidates = [".zshrc", ".zprofile"]
    elif "bash" in shell:
        # Linux → .bashrc, macOS → .bash_profile
        if sys.platform == "darwin":
            candidates = [".bash_profile", ".bashrc", ".zshrc"]
        else:
            candidates = [".bashrc", ".bash_profile"]
    elif "fish" in shell:
        return str(Path.home() / ".config" / "fish" / "config.fish")
    else:
        candidates = [".bashrc", ".zshrc", ".profile"]

    for c in candidates:
        rc = Path.home() / c
        if rc.exists():
            return str(rc)
    # Fallback: use the first candidate
    return str(Path.home() / candidates[0])


def _setup_shell_rc(rc_file: str = "", yes: bool = False) -> bool:
    """Write Hermes core environment variables to the user's shell rc file.

    Returns True if changes were made.
    """
    rc_path = Path(rc_file) if rc_file else Path(_detect_shell_rc())

    env_block = f"""# ── Hermes Agent 全封闭安装环境变量 ──
export HOME_HERMES="$HOME/hermes"
export HERMES_INSTALL_PREFIX="$HOME_HERMES/install"
export HERMES_HOME="$HOME_HERMES/runtime"
export UV_INSTALL_DIR="$HOME_HERMES/runtime/bin"
export UV_CACHE_DIR="$HOME_HERMES/uv-cache"
export PATH="$HOME_HERMES/install/bin:$HOME_HERMES/runtime/bin:$PATH"
# ── ──
"""
    if rc_path.exists():
        existing = rc_path.read_text(encoding="utf-8")
        if "HERMES_INSTALL_PREFIX" in existing:
            click.echo(f"  ⏭ Hermes 环境变量已在 {rc_path.name} 中存在，跳过")
            return False

    if not yes:
        if not click.confirm(f"  将 Hermes 环境变量写入 {rc_path.name}?\\n"
                             f"    路径: {rc_path}"):
            click.echo("  已跳过 Shell RC 配置")
            return False

    rc_path.parent.mkdir(parents=True, exist_ok=True)
    with open(rc_path, "a", encoding="utf-8") as f:
        f.write(f"\\n{env_block}")
    click.echo(f"  ✅ 环境变量已写入 {rc_path.name}")
    click.echo(f"     执行 source {rc_path.name} 立即生效")
    return True


def _install_script(china_mirror: bool, yes: bool, timeout: int = 600,
                    home: str = "", install_prefix: str = "") -> bool:
    """Install Hermes Agent via official one-click install script.

    Uses the upstream install.sh which auto-configures venv, deps, and CLI.
    After success, writes detected home/install_prefix back to sccsos.yaml.
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
        # 如有自定义 home/install_prefix，传给 install.sh
        env = os.environ.copy()
        if home:
            env["HERMES_HOME"] = home
            click.echo(f"  ↪ 使用自定义路径: HERMES_HOME={home}")
        if install_prefix:
            env["HERMES_INSTALL_PREFIX"] = install_prefix
        r = subprocess.run(
            ["bash", "-c", f"curl -fL --progress-bar {url} | bash"],
            timeout=timeout,
            env=env,
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
    detected_install = install_prefix or _get_hermes_install_prefix()
    if not detected_home:
        detected_home = str(Path.home() / ".hermes")
    _update_hermes_paths_in_yaml(detected_home, detected_install)
    # 如使用了自定义路径且 install.sh 未自动创建，补建目录结构
    if home:
        _ensure_hermes_home(home)
    return True


def _install_docker(version: Optional[str], yes: bool, force: bool,
                    home: str = "", install_prefix: str = "",
                    china_mirror: bool = False) -> bool:
    """Install Hermes Agent via Docker image pull.

    After success, writes detected home/install_prefix back to sccsos.yaml.
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
    detected_install = install_prefix or _get_hermes_install_prefix()
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


# ── Post-install config sync ────────────────────────────────────────


def _auto_apply_config() -> None:
    """Auto-sync sccsos.yaml model config to Hermes after install.

    Strategy:
    1. Write model.default/provider/base_url to the **default** config
       (~/.hermes/config.yaml) — always, as fallback.
    2. If sccsos.yaml hermes.profile differs from "default",
       clone the config to that profile (create if missing).
    3. Verify both configs are valid dict structures and consistent.

    Does NOT set API key (security) — user must run ``sccsos hermes setup``.
    """
    try:
        cfg = _get_hermes_config()
        provider = cfg.setup.provider
        model = cfg.setup.model
        if not provider or not model:
            return

        profile_name = cfg.profile or "sccsos"
        base_url = cfg.setup.base_url or PROVIDER_DEFAULT_URLS.get(provider, "")
        click.echo("  → 自动同步配置文件...")

        # Step 1: Write to default config
        default_path = _get_profile_config_path("default")
        ok = _write_model_config(_set_default_config, model, provider, base_url)
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
                click.echo(f"  ✅ Profile '{profile_name}' 已创建（从默认配置克隆）")

            prof_path = _get_profile_config_path(profile_name)
            ok = _write_model_config(
                lambda k, v: _set_profile_config(profile_name, k, v),
                model, provider, base_url,
            )
            if not ok:
                click.echo(f"  ⚠️  Profile '{profile_name}' 写入异常")
                return
            click.echo(f"  ✅ Profile '{profile_name}' 已同步")

        # Step 3: Verify both configs
        errors = []
        for label, path in [("默认配置", default_path),
                            (f"Profile '{profile_name}'", _get_profile_config_path(profile_name))]:
            v = _verify_model_config(path)
            if v["errors"]:
                errors.extend([f"{label}: {e}" for e in v["errors"]])
            elif v["is_dict"]:
                url = v["model"].get("base_url", "")
                click.echo(f"  ✅ {label} 结构正确: {v['model'].get('provider')} / {v['model'].get('default')}" +
                          (f" / {url}" if url else ""))

        # Cross-check consistency
        if profile_name != "default":
            dv = _verify_model_config(default_path)
            pv = _verify_model_config(_get_profile_config_path(profile_name))
            if dv["is_dict"] and pv["is_dict"]:
                for k in ["default", "provider", "base_url"]:
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


# ── CLI command ─────────────────────────────────────────────────────


@click.option("--install-prefix", default=None,
              help="写入 sccsos.yaml 的 HERMES_INSTALL_PREFIX 路径")
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
def install(method, version, git_url, target, check, yes, force, home, install_prefix, shell_rc, china_mirror):
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

    # ── 解析 home / install_prefix：CLI 参数 > sccsos.yaml > 默认 ──
    resolved_home = home or _get_hermes_home()
    resolved_install_prefix = install_prefix or _get_hermes_install_prefix()
    resolved_uv_bin = _get_uv_install_dir()
    resolved_uv_cache = _get_uv_cache_dir()
    if resolved_home:
        click.echo(f"  HERMES_HOME:            {resolved_home}")
    if resolved_install_prefix:
        click.echo(f"  HERMES_INSTALL_PREFIX:  {resolved_install_prefix}")
    click.echo(f"  UV_INSTALL_DIR:         {resolved_uv_bin}")
    click.echo(f"  UV_CACHE_DIR:           {resolved_uv_cache}")
    click.echo("")

    # ── 执行安装 ──
    if method == "script":
        _install_script(china_mirror, yes, home=resolved_home, install_prefix=resolved_install_prefix)
    elif method == "git":
        # china-mirror 时自动切换 git 源
        resolved_git_url = git_url
        if china_mirror and git_url == "https://github.com/NousResearch/hermes-agent.git":
            resolved_git_url = "https://cnb.cool/hermesagent-cn/hermes-agent-cn-mirror.git"
            click.echo(f"  ↪ 使用国内镜像: {resolved_git_url}")
        _install_git(version, resolved_git_url, target, yes, force, resolved_home, resolved_install_prefix)
    elif method == "docker":
        _install_docker(version, yes, force, home=resolved_home, install_prefix=resolved_install_prefix, china_mirror=china_mirror)

    # ── 安装后验证 ──
    click.echo("")
    click.echo("  验证安装...")
    out, _, rc = _run_hermes(["--version"])
    if rc == 0:
        click.echo(f"  ✅ Hermes Agent {out} 安装完成")
        click.echo("")

        # auto-sync sccsos.yaml model config → Hermes profile
        _auto_apply_config()

        # ── Shell RC 配置 ──
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
            _setup_shell_rc(yes=yes)

        click.echo("")
        click.echo("后续步骤:")
        click.echo("  sccsos hermes setup              # 配置 API Key（如未设置环境变量）")
        click.echo("  sccsos hermes postinstall          # 安装 Browser 引擎等系统依赖")
        click.echo("  sccsos hermes doctor              # 验证安装完整性")
        click.echo("  sccsos health                     # 检查 SCCS OS 健康状态")
    else:
        click.echo("  ❌ 安装后验证失败，请检查日志")
