"""Basic CLI tests for sccsos — Click-based command line interface.

Tests cover the top-level commands using Click's CliRunner.
These are the first CLI tests, targeting the highest-coverage-ROI paths.

Coverage targets:
  - cli/__init__.py: version, init, init --samples
  - cli/agent_cmd.py: agent list, agent status (basic)
  - cli/system_cmd.py: system health
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_project():
    """Create a temporary directory that looks like a project root."""
    tmp = tempfile.mkdtemp(prefix="sccsos_cli_test_")
    # Create minimal config
    config_dir = Path(tmp) / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    yield tmp
    # Cleanup
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


class TestCLIVersion:
    """sccsos version command."""

    def test_version_output(self, runner):
        """version should print a version string."""
        from sccsos.cli import version as version_cmd
        result = runner.invoke(version_cmd)
        assert result.exit_code == 0
        assert "v" in result.output


class TestCLIInit:
    """sccsos init command."""

    def test_init_creates_directory_structure(self, runner, tmp_project):
        from sccsos.cli import init as init_cmd
        project_dir = Path(tmp_project) / "my-project"
        result = runner.invoke(init_cmd, ["--dir", str(project_dir)])
        assert result.exit_code == 0
        assert project_dir.exists()
        # Should have created standard subdirectories
        assert (project_dir / "data").exists()
        assert (project_dir / "agents").exists()
        assert (project_dir / "workflows").exists()
        assert (project_dir / "personalities").exists()

    def test_init_creates_sccsos_yaml(self, runner, tmp_project):
        from sccsos.cli import init as init_cmd
        project_dir = Path(tmp_project) / "yaml-test"
        result = runner.invoke(init_cmd, ["--dir", str(project_dir)])
        assert result.exit_code == 0
        yaml_file = project_dir / "sccsos.yaml"
        assert yaml_file.exists()
        content = yaml_file.read_text()
        assert "version" in content

    def test_init_with_samples(self, runner, tmp_project):
        from sccsos.cli import init as init_cmd
        project_dir = Path(tmp_project) / "samples-test"
        result = runner.invoke(init_cmd, ["--dir", str(project_dir), "--samples"])
        assert result.exit_code == 0
        # Should have agent samples
        agent_dir = project_dir / "agents"
        assert agent_dir.exists()
        yamls = list(agent_dir.glob("*.yaml"))
        assert len(yamls) >= 1


class TestCLIInfo:
    """Info/info commands that don't need a runtime."""

    def test_cli_group_help(self, runner):
        """The main CLI group should show available commands."""
        from sccsos.cli import main
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        # Should list key command groups
        for cmd in ["agent", "workflow", "init", "version"]:
            assert cmd in result.output
