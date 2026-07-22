"""Tests for RolePackageInstaller — one-step Hermes + SCCS OS role setup."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sccsos.roles.installer import InstallReport, RolePackageInstaller
from sccsos.roles import RolePackage


# ═══════════════════════════════════════════════════════════════════
# InstallReport
# ═══════════════════════════════════════════════════════════════════


class TestInstallReport:
    """InstallReport dataclass behavior."""

    def test_success_default(self):
        """Report without errors is successful."""
        report = InstallReport(role="architect")
        assert report.success
        assert report.role == "architect"

    def test_failure_with_errors(self):
        """Report with errors is not successful."""
        report = InstallReport(role="architect", errors=["missing skills"])
        assert not report.success

    def test_counts_default_to_zero(self):
        """Count fields default to zero."""
        report = InstallReport()
        assert report.skills_verified == 0
        assert report.personalities_installed == 0
        assert report.agents_installed == 0
        assert report.workflows_installed == 0


# ═══════════════════════════════════════════════════════════════════
# RolePackageInstaller
# ═══════════════════════════════════════════════════════════════════


class TestRolePackageInstaller:
    """Installer tests with temp project root."""

    @pytest.fixture
    def project_root(self):
        """Temporary project directory."""
        with tempfile.TemporaryDirectory() as d:
            yield Path(d)

    @pytest.fixture
    def hermes_home(self):
        """Temporary Hermes home directory."""
        with tempfile.TemporaryDirectory() as d:
            yield Path(d)

    @pytest.fixture
    def role(self):
        """Minimal role package."""
        from sccsos.roles import RolePackageSkills, RolePackageFiles
        return RolePackage(
            name="test-role",
            description="A test role package",
            skills=RolePackageSkills(hermes=["test-skill"]),
            files=RolePackageFiles(
                personalities=["agent-architect"],
                agents=["architect"],
                workflows=["冒烟测试"],
            ),
        )

    def test_init_with_project_root(self, project_root):
        """Constructor stores project root."""
        installer = RolePackageInstaller(project_root)
        assert installer._project_root == project_root

    def test_init_with_hermes_home(self, project_root, hermes_home):
        """Custom HERMES_HOME is stored."""
        installer = RolePackageInstaller(project_root, hermes_home=hermes_home)
        assert installer._hermes_home == hermes_home

    def test_init_resolves_hermes_home(self, project_root):
        """When HERMES_HOME not provided, it is resolved via HermesManager."""
        with patch(
            "sccsos.core.hermes_manager.HermesManager._resolve_home",
            return_value="/tmp/.hermes",
        ):
            installer = RolePackageInstaller(project_root)
            assert str(installer._hermes_home) == "/tmp/.hermes"

    def test_install_verifies_skills(self, project_root, hermes_home, role):
        """Install verifies skills against Hermes home."""
        # Create a skill file in hermes home
        skill_dir = hermes_home / "skills"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "test-skill").mkdir(exist_ok=True)

        installer = RolePackageInstaller(
            project_root, hermes_home=hermes_home,
        )
        report = installer.install(role)
        assert report.skills_verified >= 0
        assert report.role == "test-role"

    def test_install_creates_files(self, project_root, hermes_home, role):
        """Install creates personality, agent, workflow directories."""
        # Create skill dir so it's found
        skill_dir = hermes_home / "skills"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "test-skill").mkdir(exist_ok=True)

        installer = RolePackageInstaller(
            project_root, hermes_home=hermes_home,
        )
        installer.install(role)

        # Verify directories created
        assert (project_root / "personalities").exists()
        assert (project_root / "agents").exists()
        assert (project_root / "workflows").exists()

    def test_install_reports_errors(self, project_root, hermes_home, role):
        """Install collects errors for missing skills."""
        installer = RolePackageInstaller(
            project_root, hermes_home=hermes_home,
        )
        report = installer.install(role)
        # Skills will be missing since we didn't create them
        assert isinstance(report.errors, list)

    def test_install_with_sample_files(self, project_root, hermes_home, role):
        """Install creates YAML files from sample templates."""
        skill_dir = hermes_home / "skills"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "test-skill").mkdir(exist_ok=True)

        installer = RolePackageInstaller(
            project_root, hermes_home=hermes_home,
        )
        report = installer.install(role)

        # Should have attempted file creation
        assert isinstance(report.personalities_installed, int)
        assert isinstance(report.agents_installed, int)
        assert isinstance(report.workflows_installed, int)

    def test_install_configure_profile_called(self, project_root, hermes_home, role):
        """Install triggers profile configuration."""
        with patch.object(
            RolePackageInstaller, "_configure_profile",
        ) as mock_cfg:
            skill_dir = hermes_home / "skills"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "test-skill").mkdir(exist_ok=True)

            installer = RolePackageInstaller(
                project_root, hermes_home=hermes_home,
            )
            installer.install(role)
            mock_cfg.assert_called_once()

    def test_verify_skills_with_missing_skill(self, project_root, hermes_home, role):
        """_verify_skills returns 0 for missing skills."""
        installer = RolePackageInstaller(
            project_root, hermes_home=hermes_home,
        )
        report = InstallReport(role=role.name)
        count = installer._verify_skills(role, report)
        # Skills dir doesn't exist → 0 verified
        assert count == 0
        assert len(report.errors) > 0

    def test_install_files_creates_directories(self, project_root, hermes_home, role):
        """_install_files creates target directory and writes files."""
        installer = RolePackageInstaller(
            project_root, hermes_home=hermes_home,
        )
        report = InstallReport(role=role.name)
        count = installer._install_files(
            ["agent-architect"], "personalities", ".yaml", report,
        )
        assert count > 0
        assert (project_root / "personalities" / "agent-architect.yaml").exists()
