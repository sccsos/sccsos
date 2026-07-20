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
]


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
                 dangerous_patterns: Optional[list[str]] = None):
        self._allowed = set(allowed_commands or [])
        self._allow_all = allow_all
        self._extra_dangerous = list(dangerous_patterns or [])

    def update_allowed(self, commands: list[str]) -> None:
        """Replace the allowed command set."""
        self._allowed = set(commands)

    def check(self, command: str) -> SandboxResult:
        """Check whether a command string is allowed.

        Returns SandboxResult; raises SandboxViolation when blocked.
        """
        if not command or not command.strip():
            return SandboxResult(allowed=True)

        # Layer 1: Dangerous pattern check (regex-based)
        cmd_lower = command.strip().lower()

        # Built-in dangerous patterns
        all_patterns = list(DANGEROUS_PATTERNS)
        # Extra dangerous patterns from config (if any)
        if self._extra_dangerous:
            all_patterns.extend(self._extra_dangerous)

        for pattern in all_patterns:
            p = pattern.strip()
            if not p:
                continue
            if ' ' in p:
                # Multi-word pattern — substring match (already specific enough)
                if p in cmd_lower:
                    return SandboxResult(
                        allowed=False,
                        reason=f"Command blocked: contains dangerous pattern '{pattern}'",
                    )
            else:
                # Single-word pattern — use regex word boundary
                # Avoids false positives like "sudo" inside "pseudocode"
                if re.search(r'\b' + re.escape(p) + r'\b', cmd_lower):
                    return SandboxResult(
                        allowed=False,
                        reason=f"Command blocked: contains dangerous pattern '{pattern}'",
                    )

        # Layer 2: Whitelist check
        if self._allow_all:
            return SandboxResult(allowed=True)

        # Extract the base command (first token)
        try:
            tokens = shlex.split(command)
            base_cmd = tokens[0] if tokens else command.strip()
        except ValueError:
            # If shlex fails, use simple split
            base_cmd = command.strip().split()[0] if command.strip() else ""

        if not base_cmd:
            return SandboxResult(allowed=False, reason="Empty command")

        # Check against allowed prefixes
        for allowed in self._allowed:
            if base_cmd == allowed or base_cmd.startswith(allowed + "/"):
                return SandboxResult(allowed=True)

        return SandboxResult(
            allowed=False,
            reason=(
                f"Command '{base_cmd}' not in whitelist. "
                f"Allowed: {sorted(self._allowed)}"
            ),
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
