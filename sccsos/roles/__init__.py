"""SCCS OS Role Package Registry.

Defines built-in role packages that bundle Hermes skills, SCCS OS
personalities, agents, workflows, and wiki knowledge bases for
one-step installation via ``sccsos init --role <name>``.

Extensible — users can add custom roles by placing YAML files in
``roles/`` directory (future: role marketplace).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import yaml


# ── Data models ─────────────────────────────────────────────────────


@dataclass
class RolePackageSkills:
    """Hermes skills to install/link as part of this role."""
    hermes: list[str] = field(default_factory=list)


@dataclass
class RolePackageFiles:
    """SCCS OS built-in files to deploy for this role.

    File names correspond to templates in
    ``sccsos/cli/sample_templates.py`` or files in
    ``sccsos/personalities/``, ``sccsos/agents/``, etc.
    """
    personalities: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    workflows: list[str] = field(default_factory=list)


@dataclass
class RoleProfileDefaults:
    """Default Hermes profile settings for this role."""
    model: str = "deepseek-v4-flash"
    temperature: float = 0.5


@dataclass
class RolePackage:
    """A single role package definition."""
    name: str = ""
    description: str = ""
    hermes_profile: RoleProfileDefaults = field(default_factory=RoleProfileDefaults)
    skills: RolePackageSkills = field(default_factory=RolePackageSkills)
    files: RolePackageFiles = field(default_factory=RolePackageFiles)


# ── Built-in role definitions (YAML) ────────────────────────────────

BUILTIN_ROLES_YAML = """
roles:
  architect:
    description: 智能体架构设计师 — Agent architecture design specialist
    hermes_profile:
      model: deepseek-v4-flash
      temperature: 0.5
    skills:
      hermes:
        - software-development/architecture-project-audit
        - software-development/sccsos-architecture-patterns
        - software-development/architecture-health-score
    files:
      personalities:
        - agent-architect
      agents:
        - architect
      workflows:
        - 架构评审

  doc-writer:
    description: 技术文档撰写专家 — Technical documentation and report generation
    hermes_profile:
      model: deepseek-v4-flash
      temperature: 0.4
    skills:
      hermes: []
    files:
      personalities:
        - doc-writer
      agents:
        - doc-writer
      workflows:
        - 冒烟测试

  code-reviewer:
    description: 代码质量审查 Agent — Automated code review and quality analysis
    hermes_profile:
      model: deepseek-v4-flash
      temperature: 0.3
    skills:
      hermes:
        - software-development/architecture-code-audit-patterns
        - software-development/coverage-gap-closure
    files:
      personalities:
        - code-reviewer
      agents:
        - code-reviewer
      workflows: []

  strategist:
    description: 战略洞察与分析专家 — Strategic analysis and research
    hermes_profile:
      model: deepseek-v4-pro
      temperature: 0.6
    skills:
      hermes:
        - research/arxiv
        - open-websearch
    files:
      personalities: []
      agents: []
      workflows: []
"""


# ── Registry loader ─────────────────────────────────────────────────


class RoleRegistry:
    """Registry of available role packages.

    Loads built-in roles from embedded YAML. Future: extend with
    user-defined roles from ``roles/`` directory.

    Usage::

        registry = RoleRegistry()
        for role in registry.list_roles():
            print(role.name, role.description)
        pkg = registry.get_role("architect")
    """

    def __init__(self) -> None:
        self._roles: dict[str, RolePackage] = {}
        self._load_builtin()

    def _load_builtin(self) -> None:
        """Parse built-in YAML definitions into RolePackage objects."""
        data = yaml.safe_load(BUILTIN_ROLES_YAML) or {}
        for name, cfg in data.get("roles", {}).items():
            if not isinstance(cfg, dict):
                continue
            profile_data = cfg.get("hermes_profile", {})
            skills_data = cfg.get("skills", {})
            files_data = cfg.get("files", {})

            pkg = RolePackage(
                name=name,
                description=cfg.get("description", ""),
                hermes_profile=RoleProfileDefaults(
                    model=profile_data.get("model", "deepseek-v4-flash"),
                    temperature=float(profile_data.get("temperature", 0.5)),
                ),
                skills=RolePackageSkills(
                    hermes=skills_data.get("hermes", []),
                ),
                files=RolePackageFiles(
                    personalities=files_data.get("personalities", []),
                    agents=files_data.get("agents", []),
                    workflows=files_data.get("workflows", []),
                ),
            )
            self._roles[name] = pkg

    def list_roles(self) -> list[RolePackage]:
        """List all available role packages."""
        return list(self._roles.values())

    def get_role(self, name: str) -> Optional[RolePackage]:
        """Get a role package by name, or None if not found."""
        return self._roles.get(name)

    def has_role(self, name: str) -> bool:
        """Check if a role exists."""
        return name in self._roles


# ── Module-level singleton ─────────────────────────────────────────

_REGISTRY: Optional[RoleRegistry] = None


def get_registry() -> RoleRegistry:
    """Get the global RoleRegistry singleton."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = RoleRegistry()
    return _REGISTRY


def reset_registry() -> None:
    """Reset the registry singleton (for testing)."""
    global _REGISTRY
    _REGISTRY = None
