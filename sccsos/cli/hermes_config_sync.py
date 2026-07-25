"""Hermes configuration sync commands for SCCS OS CLI.

Extracts model config + .env sync logic from :mod:`sccsos.cli.hermes_cmd`
into a standalone module with its own CLI command ``sccsos hermes config-sync``.

The core function :func:`_auto_apply_config` reads model/provider/api_key
from ``sccsos.yaml`` and writes them to the Hermes profile and ``.env`` file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import click

from sccsos.observability.logger import get_logger

# ── Shared helpers from hermes_cmd ───────────────────────────────────
from sccsos.cli.hermes_cmd import (
    PROVIDER_DEFAULT_MODELS,
    PROVIDER_DEFAULT_URLS,
    _create_profile,
    _get_env_api_key,
    _get_hermes_config,
    _get_hermes_home,
    _get_hermes_install_dir,
    _get_uv_install_dir,
    _get_uv_cache_dir,
    _list_profiles,
    _profile_exists,
    _resolve_hermes_binary,
    _run_hermes,
    _set_profile_config,
)

logger = get_logger()


# ── .env management ──────────────────────────────────────────────────


def _ensure_env_file(profile_name: str, provider: str, api_key: str, base_url: str = "") -> None:
    """Write API key and base URL to the Hermes .env file for a profile.

    The .env path is derived from :func:`_get_profile_config_path`,
    which resolves ``HERMES_HOME`` (env var > sccsos.yaml hermes.home
    > ``$HOME/hermes/data``).

    For a Hermes root at ``$ROOT``::

        default profile:  $ROOT/.env
        named profile:    $ROOT/profiles/<name>/.env

    Adds or replaces ``PROVIDER_API_KEY`` and ``PROVIDER_BASE_URL`` lines.
    If ``api_key`` is empty only ``base_url`` is written (and vice versa).
    """
    if not api_key and not base_url:
        return

    # Resolve .env path: default or profile
    from sccsos.cli.hermes_install import _get_profile_config_path  # noqa: E402

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
            if api_key and stripped.startswith(f"{key_var}="):
                new_lines.append(f"{key_var}={api_key}\n")
                key_found = True
            elif base_url and stripped.startswith(f"{url_var}="):
                new_lines.append(f"{url_var}={base_url}\n")
                url_found = True
            else:
                new_lines.append(line)
    else:
        env_path.parent.mkdir(parents=True, exist_ok=True)

    # Append if not found (api_key only when non-empty)
    if api_key and not key_found:
        new_lines.append(f"\n# sccsos: {provider} API Key\n" if not env_path.exists() else "")
        new_lines.append(f"{key_var}={api_key}\n")
    if base_url and not url_found:
        new_lines.append(f"{url_var}={base_url}\n")

    env_path.write_text("".join(new_lines), encoding="utf-8")
    # Restrict permissions (same as Hermes defaults)
    env_path.chmod(0o600)


# ── Hermes config helpers ────────────────────────────────────────────


def _set_default_config(key: str, value: str,
                        extra_env: Optional[dict[str, str]] = None) -> bool:
    """Set a config value in the default Hermes config."""
    out, _, rc = _run_hermes(["config", "set", key, value], extra_env=extra_env)
    return rc == 0


def _write_model_config(target_fn, model: str, provider: str, base_url: str,
                        extra_env: Optional[dict[str, str]] = None) -> bool:
    """Write model.default/provider/base_url to a config target.

    ``target_fn`` is either ``_set_default_config`` or ``_set_profile_config``
    with the profile name already curried/bound.

    .. note::
       API key is intentionally **not** written here — it belongs in the
       ``.env`` file, not in ``config.yaml``, to keep secrets out of
       plain-text config and respect Hermes' secrets convention.
    """
    ok = target_fn("model.default", model, extra_env=extra_env)
    ok = target_fn("model.provider", provider, extra_env=extra_env) and ok
    if base_url:
        ok = target_fn("model.base_url", base_url, extra_env=extra_env) and ok
    return ok


def _resolve_hermes_root() -> str:
    """Resolve the true Hermes root directory from the effective HERMES_HOME.

    Hermes may point ``HERMES_HOME`` to a profile directory
    (``profiles/<name>/``) when running under a specific profile.  This
    function walks up to the real root in that case, matching the same
    logic as :func:`_get_profile_config_path` in ``hermes_install``.
    """
    hermes_home = Path(_get_hermes_home())
    # Walk up if inside a profiles/<name> dir
    if hermes_home.name != ".hermes" and hermes_home.parent.name == "profiles":
        hermes_home = hermes_home.parent.parent
    elif not (hermes_home / "config.yaml").exists() and not (hermes_home / "profiles").exists():
        hermes_home = hermes_home.parent
    return str(hermes_home)


def _build_hermes_env() -> dict[str, str]:
    """Build extra env vars for Hermes CLI subprocess calls.

    Ensures ``HERMES_HOME``, ``HERMES_CONFIG_PATH``, ``HERMES_INSTALL_DIR``,
    ``UV_INSTALL_DIR``, and ``UV_CACHE_DIR`` are set so ``hermes config set``
    targets the correct installation (resolved root, not a profile sub-directory)
    even when the binary was freshly installed to a custom prefix.
    """
    env: dict[str, str] = {}
    hermes_home = _resolve_hermes_root()
    if hermes_home:
        env["HERMES_HOME"] = hermes_home
        env["HERMES_CONFIG_PATH"] = hermes_home
    install_dir = _get_hermes_install_dir()
    if install_dir:
        env["HERMES_INSTALL_DIR"] = install_dir
    install_bin = Path(install_dir) / "bin"
    if install_bin.exists():
        env["PATH"] = f"{install_bin}:{os.environ.get('PATH', '')}"

    uv_bin = _get_uv_install_dir()
    if uv_bin:
        env["UV_INSTALL_DIR"] = uv_bin
    uv_cache = _get_uv_cache_dir()
    if uv_cache:
        env["UV_CACHE_DIR"] = uv_cache
    return env


# ── Config sync core ─────────────────────────────────────────────────


def _auto_apply_config() -> None:
    """Auto-sync sccsos.yaml model config to Hermes after install.

    Strategy:

    1. Read provider/model/api_key from ``sccsos.yaml``.
    2. Write ``model.default/provider/base_url`` to the **default** config
       (resolved from ``HERMES_HOME``) — always, as fallback.
    3. If ``sccsos.yaml hermes.profile`` differs from ``"default"``,
       clone the config to that profile (create if missing).
    4. Sync ``.env`` files with API key and base URL.
    5. Verify both configs and cross-check consistency.

    API key is written to ``.env`` (via :func:`_ensure_env_file`),
    not to ``config.yaml`` — respects Hermes secrets convention.
    """
    try:
        cfg = _get_hermes_config()
        provider = cfg.setup.provider or "deepseek"
        model = cfg.setup.model or PROVIDER_DEFAULT_MODELS.get(provider, "deepseek-v4-flash")
        if not provider or not model:
            click.echo("  ⚠️  sccsos.yaml 中 hermes.setup.provider/model 未配置，跳过自动同步")
            click.echo("     请编辑 sccsos.yaml 后运行: sccsos hermes setup")
            return

        profile_name = cfg.profile or "sccsos"
        base_url = cfg.setup.base_url or PROVIDER_DEFAULT_URLS.get(provider, "")
        api_key = cfg.setup.api_key or _get_env_api_key(provider) or ""
        extra_env = _build_hermes_env()
        click.echo("  → 自动同步配置文件...")

        # 确保 HERMES_HOME 目录结构存在（lazy import 避免循环引用）
        from sccsos.cli.hermes_install import _ensure_hermes_home as _do_ensure_home  # noqa: E402
        _do_ensure_home(_get_hermes_home())

        from sccsos.cli.hermes_install import _get_profile_config_path  # noqa: E402
        from sccsos.cli.hermes_install import _verify_model_config  # noqa: E402

        # Step 1: Write to default config
        default_path = _get_profile_config_path("default")
        ok = _write_model_config(_set_default_config, model, provider, base_url,
                                 extra_env=extra_env)
        if not ok:
            click.echo("  ⚠️  默认配置写入异常，请检查 Hermes CLI 状态")
            return
        click.echo(f"  ✅ 默认配置已更新: {provider} / {model}")

        # Step 2: Clone to target profile
        if profile_name != "default":
            if not _profile_exists(profile_name, extra_env=extra_env):
                if not _create_profile(profile_name, extra_env=extra_env):
                    click.echo(f"  ⚠️  Profile '{profile_name}' 创建失败，跳过")
                    return

                # Clone all default config keys to the new profile
                import yaml as _yaml  # noqa: E402
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
                lambda k, v, **kw: _set_profile_config(profile_name, k, v, extra_env=extra_env),
                model, provider, base_url, extra_env=extra_env,
            )
            if not ok:
                click.echo(f"  ⚠️  Profile '{profile_name}' 写入异常")
                return
            click.echo(f"  ✅ Profile '{profile_name}' 已同步")

        # Step 2b: Sync .env files with API key and base URL
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


# ── CLI command ──────────────────────────────────────────────────────


@click.command(name="config-sync")
def config_sync() -> None:
    """从 sccsos.yaml 同步 model/config 到 Hermes profile。

    读取 ``sccsos.yaml`` 的 ``hermes.setup`` 和 ``hermes.profile``，
    将 model/provider/base_url 写入 Hermes 配置，并将 API key
    写入 ``.env`` 文件。不重新安装。
    """
    click.echo("── SCCS OS — Hermes 配置同步 ──")
    click.echo("")
    _auto_apply_config()
