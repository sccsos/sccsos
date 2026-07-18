"""Policy Engine — budget enforcement and tool access control.

Provides pre-delegation checks:
  1. Budget check — total cost from audit_log vs max_cost_usd threshold
  2. Tool access — allowed_tools / blocked_tools from config

PolicyEngine is instantiated once by the WorkflowEngine and passed
into the HermesAdapter as an optional pre-flight guard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sccsos.core.config import AgentOSConfig, PoliciesConfig
from sccsos.core.database import Database


# ── Default tool allowlist (used as fallback) ──────────────────────

DEFAULT_ALLOWED_TOOLS: list[str] = [
    "read_file", "search_files", "web_search", "web_extract",
    "terminal",
]

DEFAULT_BLOCKED_TOOLS: list[str] = []


class PolicyViolation(Exception):
    """Raised when a policy check fails (budget exceeded, tool denied)."""
    pass


@dataclass
class PolicyResult:
    """Result of a policy check."""
    allowed: bool = True
    reason: str = ""


class BudgetTracker:
    """Tracks running budget by querying the audit_log.

    Thread-safe: each query is a fresh read from the DB (WAL mode
    supports concurrent readers).
    """

    def __init__(self, db: Database, max_cost_usd: float):
        self._db = db
        self._max_cost_usd = max_cost_usd

    @property
    def max_cost_usd(self) -> float:
        return self._max_cost_usd

    def spent_so_far(self, agent_name: Optional[str] = None) -> float:
        """Query total cost from audit_log.

        Args:
            agent_name: If provided, only count costs for this agent.
        """
        conn = self._db.get_conn()
        if agent_name:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM audit_log WHERE agent_id = ?",
                (agent_name,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM audit_log"
            ).fetchone()
        return float(row[0]) if row else 0.0

    def remaining_budget(self, agent_name: Optional[str] = None) -> float:
        return max(0.0, self._max_cost_usd - self.spent_so_far(agent_name))

    def check(self, estimated_cost: float = 0.0,
              agent_name: Optional[str] = None) -> PolicyResult:
        """Check if the delegation would exceed budget.

        Args:
            estimated_cost: Estimated cost of the upcoming call (USD).
            agent_name: Optional agent name for per-agent budget isolation.
        """
        spent = self.spent_so_far(agent_name)
        projected = spent + estimated_cost
        if projected > self._max_cost_usd:
            return PolicyResult(
                allowed=False,
                reason=(
                    f"Budget exceeded: ${projected:.4f} projected > "
                    f"${self._max_cost_usd:.4f} limit "
                    f"(spent=${spent:.4f} + estimated=${estimated_cost:.4f})"
                ),
            )
        return PolicyResult(allowed=True)


class PolicyEngine:
    """Central policy enforcement point for agent operations.

    Usage:
        engine = PolicyEngine(db, config)
        result = engine.check_delegation("architect", estimated_cost=0.01)
        if not result.allowed:
            raise PolicyViolation(result.reason)

    Integrates:
      - Budget limits (max_cost_usd from config.policies.default)
      - Tool access (allowed_tools / blocked_tools — planned for Phase 2)
    """

    def __init__(self, db: Database, config: AgentOSConfig | None = None):
        self._db = db
        self._cfg = config
        self._agent_policies: dict[str, dict] = {}

    def set_agent_policy(self, agent_name: str, policy: dict | None) -> None:
        """Register a per-agent policy override.

        Args:
            agent_name: Agent name.
            policy: Policy dict (same keys as ``PolicyDefaults``).
                Pass ``None`` to clear.
        """
        if policy is None:
            self._agent_policies.pop(agent_name, None)
        else:
            self._agent_policies[agent_name] = policy

    def _get_policy_for(self, agent_name: str) -> "PolicyDefaults":
        """Get effective policy for an agent (agent-level overrides default).

        Resolution order:
        1. Agent's policy ``ref`` → named policy from config
        2. Agent's inline policy dict → override fields on default
        3. Global default
        """
        from sccsos.core.config import PolicyDefaults
        base = self._cfg.policies.default if self._cfg else PolicyDefaults()
        ap = self._agent_policies.get(agent_name)
        if not ap:
            return base

        # Support ``ref: "policy_name"`` — named policy from config
        if "ref" in ap:
            ref_name = ap["ref"]
            if self._cfg and ref_name in self._cfg.policies.named:
                return self._cfg.policies.named[ref_name]
            return base

        # Inline override fields on top of default
        return PolicyDefaults(
            max_tokens_per_session=ap.get("max_tokens_per_session", base.max_tokens_per_session),
            max_cost_usd=ap.get("max_cost_usd", base.max_cost_usd),
            allowed_tools=ap.get("allowed_tools", list(base.allowed_tools)),
            blocked_tools=ap.get("blocked_tools", list(base.blocked_tools)),
            allowed_commands=ap.get("allowed_commands", list(base.allowed_commands)),
        )

    def check_delegation(
        self,
        agent_name: str = "",
        model: str = "deepseek-v4-flash",
        estimated_cost: float = 0.0,
    ) -> PolicyResult:
        """Pre-flight check before delegating a task to an agent.

        Checks:
          1. Budget — total cost across all agents against max_cost_usd
          2. (Future) Agent-specific tool permissions

        Args:
            agent_name: Name of the target agent (for audit context).
            model: Model name (for cost estimation).
            estimated_cost: Estimated USD cost of this delegation.

        Returns:
            PolicyResult with allowed=True/False and reason string.
        """
        if not self._cfg:
            return PolicyResult(allowed=True)

        policy = self._get_policy_for(agent_name)

        # -- Budget check --
        if policy.max_cost_usd > 0:
            tracker = BudgetTracker(self._db, policy.max_cost_usd)
            budget_result = tracker.check(
                estimated_cost=estimated_cost,
                agent_name=agent_name or None,
            )
            if not budget_result.allowed:
                return budget_result

        return PolicyResult(allowed=True)

    def check_tool_access(self, agent_name: str, tool_name: str) -> PolicyResult:
        """Check if an agent is allowed to use a specific tool.

        Args:
            agent_name: Name of the agent (for audit context).
            tool_name: Tool name to check (e.g. ``"terminal"``).

        Returns:
            PolicyResult — allowed=True if the tool is in allowed_tools
            and not in blocked_tools.
        """
        if not self._cfg:
            return PolicyResult(allowed=True)

        policy = self._get_policy_for(agent_name)
        allowed = policy.allowed_tools or DEFAULT_ALLOWED_TOOLS
        blocked = policy.blocked_tools or DEFAULT_BLOCKED_TOOLS

        if tool_name in blocked:
            return PolicyResult(
                allowed=False,
                reason=f"Tool '{tool_name}' is blocked for agent '{agent_name}'",
            )

        if tool_name not in allowed:
            return PolicyResult(
                allowed=False,
                reason=(
                    f"Tool '{tool_name}' not allowed for agent '{agent_name}'. "
                    f"Allowed: {allowed}"
                ),
            )

        return PolicyResult(allowed=True)

    def check_agent_toolsets(self, agent_name: str,
                             toolsets: list[str]) -> PolicyResult:
        """Validate an agent's declared toolsets against policy.

        Checks that the toolset names don't include blocked tools.
        Uses per-agent policy override if configured via
        ``AgentSpec.policy``.
        """
        if not self._cfg or not toolsets:
            return PolicyResult(allowed=True)

        policy = self._get_policy_for(agent_name)
        blocked = policy.blocked_tools or DEFAULT_BLOCKED_TOOLS

        # Check if any toolset name matches a blocked tool pattern
        for ts in toolsets:
            ts_lower = ts.lower()
            for blocked_tool in blocked:
                if blocked_tool.lower() in ts_lower:
                    return PolicyResult(
                        allowed=False,
                        reason=(
                            f"Agent '{agent_name}' toolset '{ts}' "
                            f"matches blocked tool '{blocked_tool}'"
                        ),
                    )

        return PolicyResult(allowed=True)
