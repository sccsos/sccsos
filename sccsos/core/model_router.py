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
from datetime import datetime, timezone
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


@dataclass
class ModelCallRecord:
    """A single recorded model call."""

    model: str
    agent_name: str = ""
    task_type: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    success: bool = True
    error: str = ""
    timestamp: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


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

        # Runtime metrics tracking
        self._call_records: list[ModelCallRecord] = []
        self._metrics_lock = __import__("threading").Lock()

    @property
    def default(self) -> str:
        return self._default

    @property
    def available_models(self) -> list[str]:
        return list(self._pool.keys())

    def resolve_for_agent(self, agent_name: str,
                           capability: str = "",
                           preferred: str = "") -> str:
        """Resolve a model for an agent with fallback chain.

        Resolution order:
        1. ``preferred`` — explicit model name (highest priority)
        2. ``capability`` — first model matching the required capability
        3. ``default`` — from config

        Args:
            agent_name: Agent name (for future audit/tracking).
            capability: Required capability (``"reasoning"``, ``"fast"``, etc.).
            preferred: Explicit model name override.

        Returns:
            Resolved model name string.
        """
        return self.select(
            agent_name=agent_name,
            preferred=preferred,
            capability=capability or "general",
        )

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

    # ── Metrics / Observability ───────────────────────────────────

    def record_call(self, model: str, *,
                    agent_name: str = "",
                    task_type: str = "",
                    input_tokens: int = 0,
                    output_tokens: int = 0,
                    latency_ms: float = 0.0,
                    success: bool = True,
                    error: str = "") -> ModelCallRecord:
        """Record a model call for metrics tracking.

        Args:
            model: Model name used.
            agent_name: Agent that made the call.
            task_type: Type of task.
            input_tokens: Input token count.
            output_tokens: Output token count.
            latency_ms: Call latency in milliseconds.
            success: Whether the call succeeded.
            error: Error message if failed.

        Returns:
            The recorded ModelCallRecord.
        """
        profile = self._pool.get(model)
        cost = 0.0
        if profile:
            cost = (
                (input_tokens / 1_000_000) * profile.cost_per_1m_input
                + (output_tokens / 1_000_000) * profile.cost_per_1m_output
            )

        record = ModelCallRecord(
            model=model,
            agent_name=agent_name,
            task_type=task_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost,
            success=success,
            error=error,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        with self._metrics_lock:
            self._call_records.append(record)
        return record

    def select_with_fallback(self, *,
                              agent_name: str = "",
                              task_type: str = "",
                              preferred: str = "",
                              capability: str = "") -> tuple[str, bool]:
        """Select a model and detect if falling back due to prior failures.

        If the preferred/capability-matched model has >50% failure rate
        in recent calls, automatically falls back to the next option.

        Args:
            agent_name: Agent name.
            task_type: Task type.
            preferred: Explicit model name.
            capability: Required capability.

        Returns:
            Tuple of ``(model_name, is_fallback)``.
        """
        primary = self.select(
            task_type=task_type,
            agent_name=agent_name,
            preferred=preferred,
            capability=capability,
        )

        # Check failure rate for primary
        with self._metrics_lock:
            recent = [r for r in self._call_records[-50:]
                      if r.model == primary]

        if recent and len(recent) >= 3:
            fail_rate = sum(1 for r in recent if not r.success) / len(recent)
            if fail_rate > 0.5:
                fallback_model = self.fallback(
                    primary, failed_capability=capability,
                )
                if fallback_model and fallback_model != primary:
                    return fallback_model, True

        return primary, False

    def get_metrics(self) -> dict:
        """Get aggregated model metrics.

        Returns:
            Dict with total calls, per-model stats, cost breakdown.
        """
        with self._metrics_lock:
            total_calls = len(self._call_records)
            if total_calls == 0:
                return {
                    "total_calls": 0,
                    "models": {},
                    "total_cost_usd": 0.0,
                    "avg_latency_ms": 0.0,
                }

            models: dict[str, dict] = {}
            total_cost = 0.0
            total_latency = 0.0
            for r in self._call_records:
                total_cost += r.cost_usd
                total_latency += r.latency_ms
                if r.model not in models:
                    models[r.model] = {
                        "calls": 0, "success": 0, "failures": 0,
                        "total_tokens": 0, "total_cost": 0.0,
                        "avg_latency_ms": 0.0,
                    }
                models[r.model]["calls"] += 1
                if r.success:
                    models[r.model]["success"] += 1
                else:
                    models[r.model]["failures"] += 1
                models[r.model]["total_tokens"] += r.total_tokens
                models[r.model]["total_cost"] += r.cost_usd

            # Compute averages
            for m in models.values():
                m["avg_latency_ms"] = round(
                    total_latency / total_calls, 1,
                ) if total_calls else 0.0

            return {
                "total_calls": total_calls,
                "models": models,
                "total_cost_usd": round(total_cost, 6),
                "avg_latency_ms": round(total_latency / total_calls, 1),
            }

    def get_model_stats(self, model: str) -> Optional[dict]:
        """Get stats for a specific model.

        Args:
            model: Model name.

        Returns:
            Dict with stats or None if no calls recorded.
        """
        metrics = self.get_metrics()
        return metrics["models"].get(model)
