"""Hermes Manager — unified facade for Hermes Agent lifecycle.

Provides installation discovery, validation, adapter selection, and
one-click setup for multi-mode Hermes Agent integration.

Key responsibilities:
- ``discover()`` — auto-detect Hermes installation mode (git-installer, pip, docker, …)
- ``validate()`` — check installation completeness
- ``get_adapter()`` — return the best HermesAdapter for the current environment
- ``doctor_report()`` — comprehensive diagnostics dict
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class HermesInstallMode(Enum):
    """Detected Hermes Agent installation method."""

    GIT_INSTALLER = "git-installer"
    PIP = "pip"
    HOMEBREW = "homebrew"
    DESKTOP = "desktop"
    DOCKER = "docker"
    NIX = "nix"
    SOURCE = "source"
    UNKNOWN = "unknown"


@dataclass
class HermesInstallation:
    """Describes a detected Hermes Agent installation.

    Populated by :meth:`HermesManager.discover`.
    """

    mode: HermesInstallMode = HermesInstallMode.UNKNOWN
    binary_path: str = ""               # Full path to hermes CLI binary
    version: str = ""                   # Version string from --version
    home: str = ""                      # Effective HERMES_HOME
    code_path: Optional[str] = None     # Effective HERMES_CODE_PATH (source/git-installer only)
    config_path: str = ""               # Path to Hermes config.yaml
    profiles: list[str] = field(default_factory=list)  # Available profiles
    errors: list[str] = field(default_factory=list)    # Discovery warnings / errors


@dataclass
class DoctorReport:
    """Diagnostic report from :meth:`HermesManager.doctor_report`."""

    installation: Optional[HermesInstallation] = None
    cli_available: bool = False
    hermes_home_exists: bool = False
    profile_count: int = 0
    has_env_api_key: bool = False
    connectivity_ok: bool = False
    issues: list[tuple[str, str, str]] = field(default_factory=list)


class HermesManager:
    """Unified facade for Hermes Agent lifecycle management."""

    def __init__(self) -> None:
        self._installation: Optional[HermesInstallation] = None

    # ── Discovery ───────────────────────────────────────────────────

    def discover(self) -> HermesInstallation:
        """Auto-detect the installed Hermes Agent (multi-strategy probe).

        Runs a probe chain (PATH → config → env → Docker) and classifies the
        installation mode. Results are cached on first call; call with
        ``force=True`` to re-scan.
        """
        if self._installation is not None:
            return self._installation

        inst = HermesInstallation()

        # Priority 1: PATH
        path_binary = shutil.which("hermes")
        if path_binary:
            inst.binary_path = path_binary

        # Priority 2: sccsos.yaml → hermes.binary
        try:
            from sccsos.core.config import get_config
            cfg = get_config().hermes
            if cfg.binary and cfg.binary != "hermes":
                resolved = shutil.which(cfg.binary) or cfg.binary
                if not inst.binary_path:
                    inst.binary_path = resolved
        except Exception:
            pass

        # Priority 3: Environment variables
        inst.home = self._resolve_home()
        inst.code_path = self._resolve_code_path()

        # Classify and fill metadata
        inst.mode = self._classify_mode(inst.binary_path, inst.home, inst.code_path)
        if inst.binary_path:
            inst.version = self._get_version(inst.binary_path)
        inst.config_path = str(Path(inst.home) / "config.yaml")
        if inst.binary_path:
            inst.profiles = self._list_profiles(inst.binary_path)

        self._installation = inst
        return inst

    # ── Resolvers ───────────────────────────────────────────────────

    @staticmethod
    def _resolve_home() -> str:
        """Resolve HERMES_HOME: env var > config > default."""
        from_env = os.environ.get("HERMES_HOME", "")
        if from_env:
            return from_env
        try:
            from sccsos.core.config import get_config
            if get_config().hermes.home:
                return get_config().hermes.home
        except Exception:
            pass
        return str(Path.home() / ".hermes")

    @staticmethod
    def _resolve_code_path() -> Optional[str]:
        """Resolve HERMES_CODE_PATH: env var > config > git-installer default."""
        from_env = os.environ.get("HERMES_CODE_PATH", "")
        if from_env:
            return from_env
        try:
            from sccsos.core.config import get_config
            if get_config().hermes.code_path:
                return get_config().hermes.code_path
        except Exception:
            pass
        # Default: check {hermes_home}/hermes-agent (respects custom home)
        resolved_home = HermesManager._resolve_home()
        default_path = Path(resolved_home) / "hermes-agent"
        if default_path.exists():
            return str(default_path)
        return None

    @staticmethod
    def _classify_mode(
        binary_path: str, home: str, code_path: Optional[str],
    ) -> HermesInstallMode:
        """Classify Hermes installation mode from detected attributes.

        Probe chain:
        1. Code path has .git → SOURCE or GIT_INSTALLER
        2. ``/Applications/`` in binary path → DESKTOP
        3. ``/brew/`` in binary path → HOMEBREW
        4. Docker daemon + running container → DOCKER
        5. ``pip show hermes-agent`` succeeds → PIP
        6. Fallback → UNKNOWN
        """
        # Source / git-installer — code path has .git
        if code_path and (Path(code_path) / ".git").exists():
            return HermesInstallMode.GIT_INSTALLER

        # Desktop — Application bundle path
        if "/Applications/" in binary_path:
            return HermesInstallMode.DESKTOP

        # Homebrew
        if "/brew/" in binary_path:
            return HermesInstallMode.HOMEBREW

        # Docker — check if hermes-agent container is running
        if shutil.which("docker"):
            try:
                r = subprocess.run(
                    ["docker", "ps", "--filter", "name=hermes", "--format", "{{.Names}}"],
                    capture_output=True, text=True, timeout=5,
                )
                if r.returncode == 0 and r.stdout.strip():
                    return HermesInstallMode.DOCKER
            except Exception:
                pass

        # Pip — check pip show
        if self._pip_installed():
            return HermesInstallMode.PIP

        # Nix — check /nix/store or nix profile
        if "/nix/store/" in binary_path or shutil.which("nix-env"):
            return HermesInstallMode.NIX

        # Code path exists but no .git (stable git-installer without repo)
        if code_path:
            return HermesInstallMode.GIT_INSTALLER

        # Could not determine
        return HermesInstallMode.UNKNOWN

    @staticmethod
    def _pip_installed() -> bool:
        """Check if hermes-agent is installed via pip."""
        try:
            r = subprocess.run(
                [sys_exe(), "-m", "pip", "show", "hermes-agent"],
                capture_output=True, text=True, timeout=10,
            )
            return r.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _get_version(binary_path: str) -> str:
        """Get Hermes version string."""
        try:
            r = subprocess.run(
                [binary_path, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            return r.stdout.strip() if r.returncode == 0 else "unknown"
        except Exception:
            return "unknown"

    @staticmethod
    def _list_profiles(binary_path: str) -> list[str]:
        """List available Hermes profiles."""
        try:
            r = subprocess.run(
                [binary_path, "config", "list-profiles"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                return [p.strip() for p in r.stdout.splitlines() if p.strip()]
        except Exception:
            pass
        return []

    # ── Validation ──────────────────────────────────────────────────

    def validate(self, installation: Optional[HermesInstallation] = None) -> list[str]:
        """Validate an installation for completeness.

        Returns a list of missing/incomplete items. Empty list = ready.
        """
        inst = installation or self.discover()
        issues: list[str] = []

        if not inst.binary_path:
            issues.append("Hermes CLI not found in PATH")
        if not inst.version:
            issues.append("Could not determine Hermes version")
        if not Path(inst.home).exists():
            issues.append(f"HERMES_HOME directory missing: {inst.home}")
        if not Path(inst.config_path).exists():
            issues.append(f"Hermes config.yaml missing: {inst.config_path}")
        if not inst.profiles:
            issues.append("No Hermes profiles configured")

        return issues

    # ── Adapter factory ─────────────────────────────────────────────

    def get_adapter(self, mode: str = "auto") -> "HermesAdapter":
        """Return the best HermesAdapter for the current environment.

        Args:
            mode: ``"auto"`` — auto-select based on installation mode.
                  ``"docker-exec"`` — force Docker adapter.
                  ``"subprocess"`` — force subprocess adapter.
                  ``"mock"`` — return MockHermesAdapter (testing).
        """
        return _create_adapter(mode)

    # ── Doctor report ───────────────────────────────────────────────

    def doctor_report(self) -> DoctorReport:
        """Produce a comprehensive Hermes diagnostics report."""
        inst = self.discover()
        report = DoctorReport(installation=inst)

        # CLI check
        report.cli_available = bool(inst.binary_path)

        # Home check
        report.hermes_home_exists = Path(inst.home).exists()

        # Profiles
        report.profile_count = len(inst.profiles)

        # API key check
        for env_key in [
            "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "GROQ_API_KEY", "TOGETHER_API_KEY", "MISTRAL_API_KEY",
        ]:
            if os.environ.get(env_key):
                report.has_env_api_key = True
                break

        # Connectivity test
        if inst.binary_path:
            try:
                r = subprocess.run(
                    [inst.binary_path, "-p", inst.profiles[0] if inst.profiles else "default",
                     "-z", "ping"],
                    capture_output=True, text=True, timeout=30,
                )
                report.connectivity_ok = r.returncode == 0
            except Exception:
                report.connectivity_ok = False

        # Collect issues
        if not report.cli_available:
            report.issues.append(("CLI", "Hermes CLI not found", "pip install hermes-agent"))
        if not report.hermes_home_exists:
            report.issues.append(("HOME", f"HERMES_HOME not found: {inst.home}", "run hermes setup"))
        if report.profile_count == 0:
            report.issues.append(("PROFILE", "No profiles configured", "sccsos hermes setup"))
        if not report.has_env_api_key:
            report.issues.append(("API_KEY", "No API key environment variables set", "sccsos hermes setup"))
        if not report.connectivity_ok and report.profile_count > 0:
            report.issues.append(("CHAT", "Profile connectivity test failed",
                                  "check API key and network"))

        return report


# ── Module-level conveniences ────────────────────────────────────────

_MANAGER: Optional[HermesManager] = None


def get_manager() -> HermesManager:
    """Get the global HermesManager singleton."""
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = HermesManager()
    return _MANAGER


def reset_manager() -> None:
    """Reset the manager singleton (for testing)."""
    global _MANAGER
    _MANAGER = None


def sys_exe() -> str:
    """Get the current Python executable path."""
    import sys
    return sys.executable


# Late import to avoid circular deps in factory
def _create_adapter(mode: str) -> "HermesAdapter":
    """Create a HermesAdapter by mode name.

    ``auto`` mode selects the adapter based on the current
    installation discovery results.
    """
    from sccsos.core.hermes_adapter import create_adapter

    if mode == "auto":
        inst = get_manager().discover()
        if inst.mode == HermesInstallMode.DOCKER:
            mode = "docker-exec"
        else:
            mode = "subprocess"

    if mode == "docker-exec":
        from sccsos.core.config import get_config
        cfg = get_config().hermes.docker
        from sccsos.core.hermes_docker_adapter import DockerHermesAdapter
        return DockerHermesAdapter(container=cfg.container, network=cfg.network)

    return create_adapter(mode)
