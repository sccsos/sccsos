"""Model Router — task-aware model selection from a configurable pool.

Allows SCCS OS to dynamically select the optimal model for each task
based on capability requirements, cost budget, and availability.

Model pool is configured in ``sccsos.yaml`` under ``model_pool``:

.. code-block:: yaml

    model_pool:
      default: deepseek-v4-flash
      fallback_strategy: cost_asc   # cost_asc | capability_first | prefer_fast
      profiles:
        deepseek-v4-flash:
          provider: deepseek
          capabilities: [fast, general]
        deepseek-v4-pro:
          provider: deepseek
          capabilities: [reasoning, complex]
        claude-sonnet-4:
          provider: anthropic
          capabilities: [reasoning, coding, vision]

Usage::

    router = ModelRouter.from_config(cfg)
    model = router.select(task_type="reasoning", agent="architect")
    model = router.select(preferred="claude-sonnet-4")
    fallback = router.fallback("claude-sonnet-4")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Data Models ────────────────────────────────────────────────────


@dataclass
class ModelProfile:
    """A single model in the pool."""

    name: str
    provider: str = "openrouter"
    capabilities: list[str] = field(default_factory=lambda: ["general"])
    cost_per_1m_input: float = 0.0
    cost_per_1m_output: float = 0.0
    is_fallback: bool = False
    max_tokens: int = 32000


# ── Fallback strategy ──────────────────────────────────────────────

FALLBACK_COST_ASC = "cost_asc"
FALLBACK_CAPABILITY_FIRST = "capability_first"
FALLBACK_PREFER_FAST = "prefer_fast"

_VALID_STRATEGIES = {
    FALLBACK_COST_ASC,
    FALLBACK_CAPABILITY_FIRST,
    FALLBACK_PREFER_FAST,
}


# ── Model Router ───────────────────────────────────────────────────


class ModelRouter:
    """Routes tasks to appropriate models based on task type and cost.

    Thread-safe: all state is read-only after construction.
    """

    def __init__(
        self,
        pool: dict[str, ModelProfile],
        default_model: str = "",
        fallback_strategy: str = FALLBACK_COST_ASC,
    ):
        self._pool = dict(pool)
        self._default = default_model or next(iter(pool.keys()), "")
        self._fallback_strategy = (
            fallback_strategy if fallback_strategy in _VALID_STRATEGIES
            else FALLBACK_COST_ASC
        )

        # Pre-compute sorted fallback chains
        self._by_cost = sorted(
            pool.values(), key=lambda p: p.cost_per_1m_input
        )
        self._by_capability: dict[str, list[ModelProfile]] = {}
        for p in pool.values():
            for cap in p.capabilities:
                self._by_capability.setdefault(cap, []).append(p)

    @property
    def default(self) -> str:
        return self._default

    @property
    def available_models(self) -> list[str]:
        return list(self._pool.keys())

    # ── Public API ───────────────────────────────────────────────

    def select(
        self,
        task_type: str = "",
        agent_name: str = "",
        preferred: str = "",
        capability: str = "",
    ) -> str:
        """Select the best model for a task.

        Resolution order:
        1. ``preferred`` — explicit model name (highest priority)
        2. ``capability`` — first model matching the required capability
        3. ``default`` — from config

        Args:
            task_type: High-level task category (reserved for future use).
            agent_name: Agent name requesting the model (for audit).
            preferred: Explicit model name override.
            capability: Required capability (``"reasoning"``, ``"fast"``, etc.).

        Returns:
            Model name string.
        """
        # 1. Preferred model
        if preferred and preferred in self._pool:
            return preferred

        # 2. Capability match
        if capability:
            matches = self._by_capability.get(capability, [])
            if matches:
                # Within matches, pick the cheapest
                return min(matches, key=lambda p: p.cost_per_1m_input).name

        # 3. Default
        return self._default

    def fallback(self, primary: str, failed_capability: str = "") -> str:
        """Get a fallback model if the primary fails or is unavailable.

        The fallback is selected based on ``fallback_strategy``:
        - ``cost_asc``: cheapest available model
        - ``capability_first``: model with matching capability
        - ``prefer_fast``: model tagged with ``"fast"`` capability

        Args:
            primary: The model name that failed.
            failed_capability: Capability that the fallback must provide.

        Returns:
            A different model name, or the default if no alternative.
        """
        if self._fallback_strategy == FALLBACK_COST_ASC:
            for p in self._by_cost:
                if p.name != primary and not p.is_fallback:
                    return p.name

        elif self._fallback_strategy == FALLBACK_CAPABILITY_FIRST and failed_capability:
            matches = self._by_capability.get(failed_capability, [])
            for p in matches:
                if p.name != primary:
                    return p.name

        elif self._fallback_strategy == FALLBACK_PREFER_FAST:
            fast_models = self._by_capability.get("fast", [])
            for p in fast_models:
                if p.name != primary:
                    return p.name

        return self._default

    def estimate_cost(self, model: str, input_tokens: int,
                      output_tokens: int) -> float:
        """Estimate the cost of a model call in USD.

        Args:
            model: Model name.
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.

        Returns:
            Estimated cost in USD, or 0 if model is unknown.
        """
        profile = self._pool.get(model)
        if profile is None:
            return 0.0
        return (
            (input_tokens / 1_000_000) * profile.cost_per_1m_input
            + (output_tokens / 1_000_000) * profile.cost_per_1m_output
        )

    @classmethod
    def from_config(cls, config: Optional[dict] = None) -> "ModelRouter":
        """Create a ModelRouter from a config dict (``model_pool`` section).

        If no config is provided, returns a router with a single default
        model (``deepseek-v4-flash``).

        Args:
            config: The ``model_pool`` section from sccsos.yaml, or None.

        Returns:
            Configured ModelRouter instance.
        """
        if not config:
            return cls(
                pool={
                    "deepseek-v4-flash": ModelProfile(
                        name="deepseek-v4-flash",
                        provider="deepseek",
                        capabilities=["fast", "general"],
                        cost_per_1m_input=0.14,
                        cost_per_1m_output=0.28,
                    ),
                },
                default_model="deepseek-v4-flash",
            )

        pool = {}
        default = config.get("default", "")
        fallback_strategy = config.get("fallback_strategy", FALLBACK_COST_ASC)

        for name, profile_data in config.get("profiles", {}).items():
            pool[name] = ModelProfile(
                name=name,
                provider=profile_data.get("provider", "openrouter"),
                capabilities=profile_data.get("capabilities", ["general"]),
                cost_per_1m_input=profile_data.get("cost_per_1m_input", 0.0),
                cost_per_1m_output=profile_data.get("cost_per_1m_output", 0.0),
                is_fallback=profile_data.get("is_fallback", False),
                max_tokens=profile_data.get("max_tokens", 32000),
            )

        # If default isn't specified, use first profile
        if not default and pool:
            default = next(iter(pool.keys()))

        return cls(
            pool=pool,
            default_model=default,
            fallback_strategy=fallback_strategy,
        )
