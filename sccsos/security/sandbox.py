"""Security sandbox — command whitelist and execution isolation.

Provides a CommandWhitelist that checks shell commands against
allowed patterns before execution. Designed as an optional guard
layer for HermesSubprocessAdapter.

Usage:
    whitelist = CommandWhitelist(allowed_commands=["hermes", "git", "ls"])
    result = whitelist.check("hermes -p sccsos -z 'hi'")   # allowed
    result = whitelist.check("rm -rf /")                    # blocked
"""

from __future__ import annotations

import re
import shlex
from typing import Optional

from sccsos.security.base import SandboxABC, SandboxResult, SandboxViolation


# Commands that are ALWAYS blocked regardless of whitelist
DANGEROUS_PATTERNS: list[str] = [
    "sudo", "su ", "chmod 777", "chown", "passwd",
    "rm -rf /", "rm -rf ~", "mkfs", "dd if=",
    ">:",
    "eval ", "exec ", "source /dev",
    "wget ", "curl ", "nc ", "telnet",
    "shutdown", "reboot", "halt",
    "nmap", "masscan",
    # Fork bomb pattern
    ":(){", ":|:&",
]

# Command chaining / injection operators (always blocked)
CHAINING_PATTERNS: list[str] = [
    "&&",
    "||",
    ";",
    "|",  # pipe
    "$(",
    "${",
    "`",
]

# Path traversal patterns (always blocked)
PATH_TRAVERSAL_PATTERNS: list[str] = [
    "../",
    "..\\",
    "/etc/",
    "/var/log/",
    "/proc/",
    "/sys/",
    "/dev/",
]

# Environment variable patterns that should be checked
ENV_VAR_PATTERN = re.compile(r"\b[A-Z_]{4,}=[^\s]", re.IGNORECASE)

# Max command length (characters)
MAX_COMMAND_LENGTH = 4096


class CommandWhitelist(SandboxABC):
    """Whitelist-based command checker.

    Two-layer protection:
      1. Hard block: dangerous patterns are always rejected
         (uses regex word boundary for single-word patterns,
          substring for multi-word patterns)
      2. Whitelist: the command's base executable must match
         an allowed prefix

    Args:
        allowed_commands: List of allowed command prefixes.
            Examples: ``["hermes", "git", "ls", "cat", "python3"]``
        allow_all: If True, skip whitelist checks (dangerous
            patterns are still blocked).
    """

    def __init__(self, allowed_commands: Optional[list[str]] = None,
                 allow_all: bool = False,
                 dangerous_patterns: Optional[list[str]] = None,
                 max_length: int = MAX_COMMAND_LENGTH):
        self._allowed = set(allowed_commands or [])
        self._allow_all = allow_all
        self._extra_dangerous = list(dangerous_patterns or [])
        self._max_length = max_length

    def update_allowed(self, commands: list[str]) -> None:
        """Replace the allowed command set."""
        self._allowed = set(commands)

    def check(self, command: str) -> SandboxResult:
        """Check whether a command string is allowed.

        Returns SandboxResult; raises SandboxViolation when blocked.
        """
        if not command or not command.strip():
            return SandboxResult(allowed=True)

        # Layer 0: Length enforcement
        result = self._check_length(command)
        if not result.allowed:
            return result

        cmd_lower = command.strip().lower()
        cmd_unquoted = re.sub(r"'[^']*'|\"[^\"]*\"", "", cmd_lower)

        # Layer 1: Dangerous patterns (multi-word, alphanumeric, symbolic)
        result = self._check_dangerous_patterns(cmd_unquoted)
        if not result.allowed:
            return result

        # Layer 1.5: Environment variable leak (even in allow_all mode)
        result = self._check_env_leak(cmd_lower)
        if not result.allowed:
            return result

        # Layer 2: Whitelist check
        return self._check_whitelist(command)

    def _check_length(self, command: str) -> SandboxResult:
        """Layer 0: Enforce maximum command length."""
        if len(command) > self._max_length:
            return SandboxResult(
                allowed=False,
                reason=f"Command exceeds max length ({len(command)} > {self._max_length})",
            )
        return SandboxResult(allowed=True)

    def _check_dangerous_patterns(self, cmd_unquoted: str) -> SandboxResult:
        """Layer 1: Check against built-in and configurable dangerous patterns."""
        all_patterns = list(DANGEROUS_PATTERNS)
        all_patterns.extend(CHAINING_PATTERNS)
        all_patterns.extend(PATH_TRAVERSAL_PATTERNS)
        if self._extra_dangerous:
            all_patterns.extend(self._extra_dangerous)

        for pattern in all_patterns:
            p = pattern.strip()
            if not p:
                continue
            if ' ' in p:
                if p in cmd_unquoted:
                    return SandboxResult(allowed=False, reason=f"Command blocked: contains dangerous pattern '{pattern}'")
            elif p.isalnum() or p.replace('-', '').isalnum():
                if re.search(r'\b' + re.escape(p) + r'\b', cmd_unquoted):
                    return SandboxResult(allowed=False, reason=f"Command blocked: contains dangerous pattern '{pattern}'")
            else:
                if p in cmd_unquoted:
                    return SandboxResult(allowed=False, reason=f"Command blocked: contains dangerous pattern '{pattern}'")
        return SandboxResult(allowed=True)

    def _check_env_leak(self, cmd_lower: str) -> SandboxResult:
        """Layer 1.5: Detect environment variable leakage attempts."""
        if not ENV_VAR_PATTERN.search(cmd_lower):
            return SandboxResult(allowed=True)
        env_vars = ENV_VAR_PATTERN.findall(cmd_lower)
        benign_prefixes = ("path=", "home=", "user=", "shell=", "term=",
                           "lang=", "pwd=", "editor=", "http_", "https_")
        for ev in env_vars:
            ev_lower = ev.lower()
            if not any(ev_lower.startswith(bp) for bp in benign_prefixes):
                return SandboxResult(allowed=False, reason=f"Command blocked: environment variable leak '{ev}'")
        return SandboxResult(allowed=True)

    def _check_whitelist(self, command: str) -> SandboxResult:
        """Layer 2: Whitelist-based command verification."""
        if self._allow_all:
            return SandboxResult(allowed=True)
        try:
            tokens = shlex.split(command)
            base_cmd = tokens[0] if tokens else command.strip()
        except ValueError:
            base_cmd = command.strip().split()[0] if command.strip() else ""
        if not base_cmd:
            return SandboxResult(allowed=False, reason="Empty command")
        for allowed in self._allowed:
            if base_cmd == allowed or base_cmd.startswith(allowed + "/"):
                return SandboxResult(allowed=True)
        return SandboxResult(
            allowed=False,
            reason=f"Command '{base_cmd}' not in whitelist. Allowed: {sorted(self._allowed)}",
        )

    def to_config(self) -> dict:
        """Serialize to dict for config storage."""
        return {
            "allowed_commands": sorted(self._allowed),
            "allow_all": self._allow_all,
            "dangerous_patterns": list(self._extra_dangerous),
        }

    @classmethod
    def from_config(cls, data: dict) -> "CommandWhitelist":
        """Create from config dict."""
        return cls(
            allowed_commands=data.get("allowed_commands", []),
            allow_all=data.get("allow_all", False),
            dangerous_patterns=data.get("dangerous_patterns", []),
        )
