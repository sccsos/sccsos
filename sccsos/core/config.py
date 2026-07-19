"""sccsos configuration loader.

Loads sccsos.yaml from project root with sensible defaults.
Config hierarchy: CLI args > env vars > config file > defaults.
"""

from __future__ import annotations

import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


DEFAULT_CONFIG_PATH = "sccsos.yaml"


@dataclass
class DatabaseConfig:
    path: str = "./data/sccsos.db"


@dataclass
class DefaultsConfig:
    hermes_profile: str = "sccsos"
    max_turns: int = 90
    timeout: int = 1800


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "json"
    directory: str = "./logs"
    retention_days: int = 30


@dataclass
class TracingConfig:
    enabled: bool = True
    export_path: str = "./traces/"
    pricing_path: str = ""  # Deprecated: use pricing.path instead


@dataclass
class PricingConfig:
    """Pricing configuration — model cost estimation data."""
    path: str = ""  # Path to pricing.json


@dataclass
class AgentsConfig:
    path: str = "./agents"
    wiki_path: str = ""  # Optional: path to wiki .md files for KB context injection
    personalities_path: str = "./personalities"  # Optional: path to personality YAML files


@dataclass
class PolicyDefaults:
    max_tokens_per_session: int = 100000
    max_cost_usd: float = 5.0
    allowed_tools: list[str] = field(default_factory=lambda: [
        "read_file", "search_files", "web_search", "web_extract", "terminal",
    ])
    blocked_tools: list[str] = field(default_factory=list)
    allowed_commands: list[str] = field(default_factory=lambda: [
        "hermes", "git", "ls", "cat", "head", "tail", "echo",
        "python3", "pip3", "node", "npm", "which",
    ])
    dangerous_patterns: list[str] = field(default_factory=list)


@dataclass
class PoliciesConfig:
    """Policy configuration with default + named policies.

    Usage:
        cfg.policies.default          # Global default
        cfg.policies.get("restricted")  # Named policy from YAML
        cfg.policies.named             # All named policies dict
    """
    default: PolicyDefaults = field(default_factory=PolicyDefaults)
    named: dict[str, PolicyDefaults] = field(default_factory=dict)

    def get(self, name: str) -> PolicyDefaults:
        """Get a policy by name, falling back to default."""
        if name == "default" or name not in self.named:
            return self.default
        return self.named[name]

    @classmethod
    def from_dict(cls, data: dict) -> "PoliciesConfig":
        """Parse policies section from YAML data.

        Example YAML::

            policies:
              default:
                max_cost_usd: 5.0
                allowed_tools: [...]
              restricted:
                max_cost_usd: 2.0
                blocked_tools: [terminal]
        """
        cfg = cls()
        for name, pd_data in (data or {}).items():
            if not isinstance(pd_data, dict):
                continue
            p = PolicyDefaults(**{
                k: v for k, v in pd_data.items()
                if k in PolicyDefaults.__dataclass_fields__
            })
            if name == "default":
                # Merge into existing defaults (preserving unspecified fields)
                for f in PolicyDefaults.__dataclass_fields__:
                    if f in pd_data:
                        setattr(cfg.default, f, getattr(p, f))
            else:
                cfg.named[name] = p
        return cfg


@dataclass
class WebhookEntry:
    """A single webhook endpoint configuration."""
    url: str
    events: list[str] = field(default_factory=lambda: ["completed", "failed"])
    secret: str = ""


@dataclass
class WebhooksConfig:
    """Webhook notification configuration."""
    enabled: bool = False
    endpoints: list[WebhookEntry] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "WebhooksConfig":
        cfg = cls()
        if "enabled" in data:
            cfg.enabled = bool(data["enabled"])
        for entry_data in data.get("endpoints", []):
            if isinstance(entry_data, dict) and "url" in entry_data:
                cfg.endpoints.append(WebhookEntry(
                    url=entry_data["url"],
                    events=entry_data.get("events", ["completed", "failed"]),
                    secret=entry_data.get("secret", ""),
                ))
        return cfg


@dataclass
class ProjectConfig:
    name: str = "sccsos"
    version: str = "0.9.0"


# ── Auto-merge helper ──────────────────────────────────────────────


def _auto_merge(target: object, data: dict) -> None:
    """Auto-map YAML dict keys to dataclass fields using introspection.

    Walks every field defined in ``target``'s ``__dataclass_fields__``.
    If the field name exists in ``data`` and the value is:
    - A dict and the current attribute value is a dataclass → recurse
    - Anything else → assign directly (str, int, bool, list, etc.)

    Fields not present in ``data`` are left at their default values.
    This means adding a new config field only requires a new dataclass
    field — no mapping code to write.

    Note: uses ``getattr(current_value, ...)`` rather than field-type
    introspection to handle ``from __future__ import annotations``,
    which turns all type hints into strings at runtime.
    """
    for fname, fdef in target.__dataclass_fields__.items():
        if fname not in data:
            continue
        value = data[fname]

        # Check runtime attribute — is it already a dataclass instance?
        # This is more reliable than checking the annotation string,
        # which can be "PoliciesConfig" (string) under PEP 563.
        current = getattr(target, fname, None)
        if isinstance(value, dict) and hasattr(current, '__dataclass_fields__'):
            _auto_merge(current, value)
        else:
            # Simple type (str, int, bool, list, dict, etc.) → direct assign
            setattr(target, fname, value)


@dataclass
class AgentOSConfig:
    """Top-level configuration for a sccsos project."""

    project: ProjectConfig = field(default_factory=ProjectConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    tracing: TracingConfig = field(default_factory=TracingConfig)
    pricing: PricingConfig = field(default_factory=PricingConfig)
    agents: AgentsConfig = field(default_factory=AgentsConfig)
    policies: PoliciesConfig = field(default_factory=PoliciesConfig)
    webhooks: WebhooksConfig = field(default_factory=WebhooksConfig)

    @classmethod
    def load(cls, path: Optional[str] = None) -> "AgentOSConfig":
        """Load config from YAML file, falling back to defaults."""
        path = path or os.environ.get("AGENTOS_CONFIG") or DEFAULT_CONFIG_PATH
        cfg_path = Path(path)

        if not cfg_path.exists():
            return cls()

        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict) -> "AgentOSConfig":
        """Recursively build dataclass from dict using field introspection.

        Eliminates the previous 60-line hand-mapped if/elif chain.
        New config fields only need a dataclass field definition —
        no mapping code to write.

        Special cases (overridden by explicit ``from_dict`` methods):
        - ``policies`` → ``PoliciesConfig.from_dict()``
        - ``webhooks`` → ``WebhooksConfig.from_dict()``

        Legacy fallback:
        - ``tracing.pricing_path`` → ``pricing.path`` (deprecated)
        """
        cfg = cls()

        # Auto-merge: walk every dataclass field, recursively nest into
        # sub-dicts, assign simple values directly.
        _auto_merge(cfg, data)

        # ── Special-case overrides ──────────────────────────────
        policies_data = data.get("policies", {})
        if policies_data:
            policies_parsed = PoliciesConfig.from_dict(policies_data)
            cfg.policies.default = policies_parsed.default
            cfg.policies.named = policies_parsed.named

        webhooks_data = data.get("webhooks", {})
        if webhooks_data:
            cfg.webhooks = WebhooksConfig.from_dict(webhooks_data)

        # Legacy fallback: tracing.pricing_path → pricing.path
        tracing_data = data.get("tracing", {})
        if not cfg.pricing.path and tracing_data.get("pricing_path"):
            cfg.pricing.path = tracing_data["pricing_path"]

        return cfg


# Global config singleton (loaded once, refreshable)
_config: Optional[AgentOSConfig] = None
_config_mtime: float = 0.0  # File modification time at last load
_config_path: Optional[str] = None  # Path of the loaded config file


def get_config(force_reload: bool = False) -> AgentOSConfig:
    """Get the global config, loading on first access.

    Args:
        force_reload: If True, reload from disk even if already loaded.
            Pass this when the config file is known to have changed
            (e.g., after ``sccsos config reload``).

    Returns:
        The (possibly cached) ``AgentOSConfig``.
    """
    global _config, _config_mtime, _config_path

    # First load
    if _config is None:
        _config = AgentOSConfig.load()
        _config_path = os.environ.get("AGENTOS_CONFIG") or DEFAULT_CONFIG_PATH
        if Path(_config_path).exists():
            _config_mtime = Path(_config_path).stat().st_mtime
        return _config

    # Force reload
    if force_reload:
        _config = AgentOSConfig.load()
        _config_path = os.environ.get("AGENTOS_CONFIG") or DEFAULT_CONFIG_PATH
        if Path(_config_path).exists():
            _config_mtime = Path(_config_path).stat().st_mtime
        return _config

    return _config


def reload_config() -> AgentOSConfig:
    """Force-reload config from disk and return the new instance.

    Equivalent to ``get_config(force_reload=True)``, provided as a
    more explicit API for CLI and event handlers.

    Returns:
        Freshly loaded ``AgentOSConfig``.
    """
    return get_config(force_reload=True)


def set_config(cfg: AgentOSConfig) -> None:
    """Set config (used for testing)."""
    global _config
    _config = cfg
