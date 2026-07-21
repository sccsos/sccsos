"""Role Package Installer — one-step Hermes + SCCS OS role setup.

Installs a role package by:
1. Linking/verifying Hermes skills in $HERMES_HOME/skills/<role>/
2. Writing SCCS OS personality, agent, and workflow files
3. Configuring Hermes profile defaults
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sccsos.cli.sample_templates import SAMPLE_FILES
from sccsos.roles import RolePackage


@dataclass
class InstallReport:
    """Result of a role package installation."""
    role: str = ""
    skills_verified: int = 0
    personalities_installed: int = 0
    agents_installed: int = 0
    workflows_installed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class RolePackageInstaller:
    """Install a role package into a SCCS OS project directory.

    Usage::

        installer = RolePackageInstaller(
            project_root="/path/to/my-project",
            hermes_home="/path/to/hermes-home",
        )
        report = installer.install("architect")
        print(report)
    """

    def __init__(
        self,
        project_root: str | Path,
        hermes_home: str | Path | None = None,
    ) -> None:
        self._project_root = Path(project_root)
        # Resolve HERMES_HOME
        if hermes_home:
            self._hermes_home = Path(hermes_home)
        else:
            from sccsos.core.hermes_manager import HermesManager
            self._hermes_home = Path(HermesManager._resolve_home())

    def install(self, role: RolePackage) -> InstallReport:
        """Execute full role package installation."""
        report = InstallReport(role=role.name)

        # 1. Verify Hermes skills exist (don't install, just check/verify)
        report.skills_verified = self._verify_skills(role, report)

        # 2. Install SCCS OS files (personalities, agents, workflows)
        report.personalities_installed = self._install_files(
            role.files.personalities, "personalities", ".yaml",
            report,
        )
        report.agents_installed = self._install_files(
            role.files.agents, "agents", ".yaml",
            report,
        )
        report.workflows_installed = self._install_files(
            role.files.workflows, "workflows", ".yaml",
            report,
        )

        # 3. Configure Hermes profile defaults
        self._configure_profile(role, report)

        return report

    def _verify_skills(
        self, role: RolePackage, report: InstallReport,
    ) -> int:
        """Verify that required Hermes skills exist.

        Checks ``$HERMES_HOME/skills/<skill_path>/SKILL.md``.
        Skills that don't exist are added to report errors but don't
        block installation.
        """
        verified = 0
        skills_dir = self._hermes_home / "skills"
        for skill_path in role.skills.hermes:
            skill_dir = skills_dir / skill_path
            if skill_dir.exists():
                verified += 1
            else:
                report.errors.append(
                    f"Hermes skill not found: {skill_path} "
                    f"(expected at {skill_dir})"
                )
        return verified

    def _install_files(
        self,
        file_names: list[str],
        subdir: str,
        extension: str,
        report: InstallReport,
    ) -> int:
        """Install SCCS OS definition files from built-in samples.

        Copies from the package's built-in sample templates to the
        project's ``<subdir>/`` directory.
        """
        installed = 0
        target_dir = self._project_root / subdir
        target_dir.mkdir(parents=True, exist_ok=True)

        for name in file_names:
            # Map to sample template key
            template_key = None
            target_filename = None

            if subdir == "personalities":
                template_key = f"personalities/{name}.yaml"
                target_filename = f"{name}.yaml"
            elif subdir == "agents":
                template_key = f"agents/{name}.yaml"
                target_filename = f"{name}.yaml"
            elif subdir == "workflows":
                template_key = f"workflows/{name}.yaml"
                target_filename = f"{name}.yaml"

            if not template_key or template_key not in SAMPLE_FILES:
                report.errors.append(
                    f"No built-in template for {subdir}/{name}"
                )
                continue

            assert target_filename is not None, f"target_filename not set for {subdir}/{name}"
            target_path = target_dir / target_filename

            # Skip if already exists (don't overwrite user changes)
            if target_path.exists():
                continue

            target_path.write_text(
                SAMPLE_FILES[template_key],
                encoding="utf-8",
            )
            installed += 1

        return installed

    def _configure_profile(
        self, role: RolePackage, report: InstallReport,
    ) -> None:
        """Set Hermes profile defaults for this role.

        Updates the active Hermes profile's model and temperature
        settings to match the role's recommendations.
        """
        from sccsos.cli.hermes_cmd import _run_hermes
        from sccsos.core.config import get_config

        profile = get_config().hermes.profile or "sccsos"

        model = role.hermes_profile.model
        if model:
            _run_hermes(["config", "set", "--profile", profile,
                         "model", model])

        temp = role.hermes_profile.temperature
        # Some Hermes profiles support temperature, some don't
        _run_hermes(["config", "set", "--profile", profile,
                     "temperature", str(temp)])

    @staticmethod
    def discover_roles() -> list[dict]:
        """List all available role packages (for CLI display)."""
        from sccsos.roles import get_registry
        return [
            {
                "name": r.name,
                "description": r.description,
                "model": r.hermes_profile.model,
                "skills": len(r.skills.hermes),
                "files": (
                    len(r.files.personalities)
                    + len(r.files.agents)
                    + len(r.files.workflows)
                ),
            }
            for r in get_registry().list_roles()
        ]

    @staticmethod
    def get_role_info(name: str) -> Optional[dict]:
        """Get detailed info about a specific role."""
        from sccsos.roles import get_registry
        role = get_registry().get_role(name)
        if not role:
            return None
        return {
            "name": role.name,
            "description": role.description,
            "hermes_profile": {
                "model": role.hermes_profile.model,
                "temperature": role.hermes_profile.temperature,
            },
            "skills": role.skills.hermes,
            "personalities": role.files.personalities,
            "agents": role.files.agents,
            "workflows": role.files.workflows,
        }
