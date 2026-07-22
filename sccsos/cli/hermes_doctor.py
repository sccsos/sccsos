"""Doctor and postinstall commands for Hermes Agent diagnostics and system dependencies."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import click

from sccsos.cli.hermes_cmd import (
    _auto_apply_config,
    _check_hermes_installed,
    _get_hermes_code_path,
    _get_hermes_config,
    _get_hermes_home,
    _get_profile_config_path,
    _list_profiles,
    _resolve_hermes_binary,
    _run_hermes,
    _test_profile,
    _verify_model_config,
    PROVIDER_ENV_KEYS,
)


# ── Postinstall helpers ──────────────────────────────────────────────


def _check_browser_engine() -> tuple[bool, str]:
    """Check if browser engine (agent-browser + Chromium) is installed."""
    if not shutil.which("agent-browser"):
        return False, "agent-browser CLI 未安装"
    try:
        r = subprocess.run(
            ["agent-browser", "--version"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            return True, r.stdout.strip()
        return False, r.stderr.strip()[:80]
    except FileNotFoundError:
        return False, "agent-browser CLI 未安装"
    except subprocess.TimeoutExpired:
        return False, "agent-browser 无响应"
    except Exception as e:
        return False, str(e)[:80]


def _check_cua_driver() -> tuple[bool, str]:
    """Check if Computer Use driver (cua-driver) is installed."""
    out, _, rc = _run_hermes(["computer-use", "status"], timeout=15)
    if rc != 0:
        return False, out or "cua-driver 检查失败"
    if "not installed" in out.lower():
        return False, out.strip()
    return True, out.strip()


def _install_browser_engine(yes: bool, timeout: int = 300) -> bool:
    """Install browser engine (agent-browser + Chromium)."""
    click.echo("  → 安装 Browser 引擎 (agent-browser + Chromium)...")
    click.echo("    这将下载约 300MB，请耐心等待")
    if not yes:
        if not click.confirm("    确认安装?"):
            click.echo("  已跳过")
            return False
    r = subprocess.run(
        [sys.executable, "-m", "hermes_tools", "post-setup", "agent_browser"],
        capture_output=True, text=True, timeout=timeout,
    )
    # Fallback: try through hermes CLI
    if r.returncode != 0:
        click.echo("  → 通过 hermes CLI 安装...")
        out, err, rc = _run_hermes(
            ["tools", "post-setup", "agent_browser"], timeout=timeout,
        )
        if rc != 0:
            click.echo(f"  ❌ 安装失败: {err[:200] or out[:200]}")
            return False
        click.echo(f"  ✅ {out.strip()[:100] or '安装完成'}")
    else:
        click.echo(f"  ✅ {r.stdout.strip()[:100] or '安装完成'}")
    return True


def _install_cua_driver(yes: bool, timeout: int = 120) -> bool:
    """Install Computer Use driver (cua-driver)."""
    click.echo("  → 安装 Computer Use 驱动 (cua-driver)...")
    if not yes:
        if not click.confirm("    确认安装?"):
            click.echo("  已跳过")
            return False
    out, err, rc = _run_hermes(["computer-use", "install"], timeout=timeout)
    if rc != 0:
        click.echo(f"  ❌ 安装失败: {err[:200] or out[:200]}")
        return False
    click.echo(f"  ✅ {out.strip()[:100] or '安装完成'}")
    return True


# ── Doctor command ──────────────────────────────────────────────────


@click.command(name="doctor")
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

    # 7. Config sync check (sccsos.yaml ↔ Hermes configs)
    import yaml
    try:
        sccsos_cfg = _get_hermes_config()
        target_profile = sccsos_cfg.profile or "sccsos"
        default_path = _get_profile_config_path("default")
        prof_path = _get_profile_config_path(target_profile)

        # Default config structure
        dv = _verify_model_config(default_path)
        if dv["errors"]:
            for e in dv["errors"]:
                click.echo(f"  Default config:  ⚠️  {e}")
                issues.append(("config_sync", f"默认配置: {e}", "sccsos hermes install --force"))
        elif dv["is_dict"]:
            click.echo(f"  Default config:  ✅ 默认配置: {dv['model'].get('provider')} / {dv['model'].get('default')}" +
                      (f" / {dv['model'].get('base_url')}" if dv['model'].get('base_url') else ""))

        # Profile config structure
        pv = _verify_model_config(prof_path)
        if not pv["exists"]:
            click.echo(f"  Profile config:  ⚠️  {prof_path} 不存在")
            issues.append(("config_sync", f"Profile '{target_profile}' 配置文件不存在", "sccsos hermes install --force 或 setup"))
        elif pv["errors"]:
            for e in pv["errors"]:
                click.echo(f"  Profile config:  ⚠️  {e}")
                issues.append(("config_sync", f"Profile '{target_profile}': {e}", "sccsos hermes install --force 或 --fix"))
        elif pv["is_dict"]:
            click.echo(f"  Profile config:  ✅ Profile '{target_profile}': {pv['model'].get('provider')} / {pv['model'].get('default')}" +
                      (f" / {pv['model'].get('base_url')}" if pv['model'].get('base_url') else ""))

        # Cross-check: sccsos.yaml vs profile
        sccsos_has = bool(sccsos_cfg.setup.model) and bool(sccsos_cfg.setup.provider)
        if sccsos_has and pv["is_dict"]:
            match = (pv["model"].get("default") == sccsos_cfg.setup.model and
                     pv["model"].get("provider") == sccsos_cfg.setup.provider)
            if match:
                click.echo(f"  Config sync:    ✅ sccsos.yaml ↔ Profile '{target_profile}' 一致")
            else:
                click.echo(f"  Config sync:    ⚠️ sccsos.yaml 与 Profile '{target_profile}' 值不一致")
                issues.append(("config_sync", f"sccsos.yaml 与 Profile '{target_profile}' 值不一致", "--fix"))
        elif sccsos_has and not pv["is_dict"] and pv["exists"]:
            click.echo(f"  Config sync:    ⚠️ sccsos.yaml 有配置但 Profile 结构异常")

        # Cross-check: default vs profile consistency
        if dv["is_dict"] and pv["is_dict"]:
            diff_keys = [k for k in ["default", "provider", "base_url"]
                         if dv["model"].get(k) != pv["model"].get(k)]
            if diff_keys:
                click.echo(f"  Default↔Profile: ⚠️  不一致: {', '.join(diff_keys)}")
                issues.append(("config_sync", f"默认配置与 Profile '{target_profile}' 不一致", "--fix"))
            else:
                click.echo(f"  Default↔Profile: ✅ 一致")
    except Exception as e:
        click.echo(f"  Config sync:    ⚠️  检查失败: {e}")

    # 8. Skills directory
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
            # Auto-fix config sync if needed
            if any(s == "config_sync" for s, _, _ in issues):
                click.echo("")
                click.echo("  → 自动同步配置文件...")
                _auto_apply_config()
            click.echo("\n--fix 模式：已自动修复可修复项，剩余问题请按提示处理。")
        else:
            click.echo("\n使用 '--fix' 参数自动修复，或按提示手动处理。")


# ── Postinstall command ────────────────────────────────────────────


@click.command(name="postinstall")
@click.option("--browser/--no-browser", "do_browser", default=True,
              help="安装/跳过 Browser 引擎 (agent-browser + Chromium)")
@click.option("--cua/--no-cua", "do_cua", default=True,
              help="安装/跳过 Computer Use 驱动 (cua-driver)")
@click.option("--check", "-c", is_flag=True, help="仅检测后端安装状态")
@click.option("--yes", "-y", is_flag=True, help="跳过确认提示")
def postinstall(do_browser, do_cua, check, yes):
    """Install Hermes Agent system dependencies.

    Automatically detects enabled Hermes backends (browser engine,
    Computer Use driver, etc.) and installs any missing dependencies.

    Run after ``sccsos hermes install`` to set up the Browser engine
    and other system-level components that pip cannot provide.
    """
    click.echo("── SCCS OS — Hermes Agent 系统依赖安装 ──")
    click.echo("")

    # ── 检测状态 ──
    browser_ok, browser_msg = _check_browser_engine()
    cua_ok, cua_msg = _check_cua_driver()

    click.echo("  检测结果:")
    click.echo(f"    Browser 引擎:   {'✅' if browser_ok else '❌'} {browser_msg}")
    click.echo(f"    Computer Use:   {'✅' if cua_ok else '❌'} {cua_msg}")
    click.echo("")

    if check:
        if browser_ok and cua_ok:
            click.echo("🎉 所有系统依赖已就绪。")
        else:
            missing = []
            if not browser_ok:
                missing.append("Browser 引擎")
            if not cua_ok:
                missing.append("Computer Use")
            click.echo(f"缺少 {len(missing)} 个依赖: {', '.join(missing)}")
            click.echo("运行 'sccsos hermes postinstall' 安装")
        return

    # ── 安装 ──
    installed_any = False

    if do_browser and not browser_ok:
        click.echo(f"[1/2] Browser 引擎")
        if _install_browser_engine(yes):
            installed_any = True
        click.echo("")
    elif do_browser and browser_ok:
        click.echo("  ⏭ Browser 引擎已安装，跳过")

    if do_cua and not cua_ok:
        step = "[2/2]" if do_browser else "[1/1]"
        click.echo(f"{step} Computer Use 驱动")
        if _install_cua_driver(yes):
            installed_any = True
        click.echo("")
    elif do_cua and cua_ok:
        click.echo("  ⏭ Computer Use 已安装，跳过")

    # ── 安装后验证 ──
    if installed_any:
        click.echo("  安装后验证...")
        b2_ok, b2_msg = _check_browser_engine()
        c2_ok, c2_msg = _check_cua_driver()
        click.echo(f"    Browser 引擎:   {'✅' if b2_ok else '❌'} {b2_msg}")
        click.echo(f"    Computer Use:   {'✅' if c2_ok else '❌'} {c2_msg}")
        click.echo("")

    all_ok = (browser_ok or (do_browser and _check_browser_engine()[0])) and \
             (cua_ok or (do_cua and _check_cua_driver()[0]))
    if all_ok:
        click.echo("🎉 所有系统依赖已就绪。")
    else:
        click.echo("部分依赖未安装完成。运行 'sccsos hermes doctor' 查看详情。")
