"""Abstract base classes for security layer.

Defines the abstract interfaces for policy enforcement and command
sandboxing, enabling pluggable backends for different deployment
environments.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


# ── Policy Engine ───────────────────────────────────────────────────


class PolicyViolation(Exception):
    """Raised when a policy check fails (budget exceeded, tool denied)."""
    pass


@dataclass
class PolicyResult:
    """Result of a policy check."""
    allowed: bool = True
    reason: str = ""


class PolicyEngineABC(ABC):
    """Abstract interface for policy enforcement.

    Implementations provide budget tracking, tool access control, and
    agent-level policy overrides.
    """

    @abstractmethod
    def check_delegation(
        self,
        agent_name: str = "",
        model: str = "deepseek-v4-flash",
        estimated_cost: float = 0.0,
    ) -> PolicyResult:
        """Pre-flight check before delegating a task to an agent.

        Args:
            agent_name: Target agent name (for audit context).
            model: Model name (for cost estimation).
            estimated_cost: Estimated USD cost of this delegation.

        Returns:
            PolicyResult with ``allowed`` and ``reason`` fields.
        """
        ...

    def check_tool_access(self, agent_name: str,
                          tool_name: str) -> PolicyResult:
        """Check if an agent is allowed to use a specific tool.

        Args:
            agent_name: Agent name.
            tool_name: Tool name (e.g. ``"terminal"``).

        Returns:
            ``PolicyResult(allowed=True)`` by default — override to
            enforce tool-level permissions.
        """
        return PolicyResult(allowed=True)

    def check_agent_toolsets(self, agent_name: str,
                             toolsets: list[str]) -> PolicyResult:
        """Validate an agent's declared toolsets against policy.

        Returns:
            ``PolicyResult(allowed=True)`` by default.
        """
        return PolicyResult(allowed=True)

    def set_agent_policy(self, agent_name: str,
                         policy: dict | None) -> None:
        """Register a per-agent policy override."""
        pass


# ── Sandbox ─────────────────────────────────────────────────────────


class SandboxViolation(Exception):
    """Raised when a command is blocked by the sandbox."""
    pass


class SandboxResult:
    """Result of a sandbox check."""

    def __init__(self, allowed: bool = True, reason: str = "") -> None:
        self.allowed = allowed
        self.reason = reason


class SandboxABC(ABC):
    """Abstract interface for command sandboxing.

    Implementations provide whitelist/dangerous-pattern checks for
    shell commands executed by agents.
    """

    @abstractmethod
    def check(self, command: str) -> SandboxResult:
        """Check whether a command string is allowed.

        Args:
            command: The full shell command string.

        Returns:
            SandboxResult; raises SandboxViolation when blocked.
        """
        ...

    def update_allowed(self, commands: list[str]) -> None:
        """Replace the allowed command set."""
        pass

    def to_config(self) -> dict:
        """Serialize to dict for config storage."""
        return {}

    @classmethod
    def from_config(cls, data: dict) -> SandboxABC:
        """Create from config dict."""
        raise NotImplementedError
