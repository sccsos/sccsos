"""Tests for ModelRouter metrics and auto-fallback."""

from __future__ import annotations

import pytest

from sccsos.core.model_router import (
    ModelRouter, ModelProfile, ModelCallRecord,
    FALLBACK_COST_ASC, FALLBACK_CAPABILITY_FIRST,
)


@pytest.fixture
def router():
    """ModelRouter with two models for testing."""
    return ModelRouter(
        pool={
            "fast-model": ModelProfile(
                name="fast-model", provider="test",
                capabilities=["fast", "general"],
                cost_per_1m_input=0.10, cost_per_1m_output=0.20,
            ),
            "reasoning-model": ModelProfile(
                name="reasoning-model", provider="test",
                capabilities=["reasoning", "complex"],
                cost_per_1m_input=0.50, cost_per_1m_output=1.00,
            ),
            "cheap-model": ModelProfile(
                name="cheap-model", provider="test",
                capabilities=["general"],
                cost_per_1m_input=0.05, cost_per_1m_output=0.10,
                is_fallback=True,
            ),
        },
        default_model="fast-model",
    )


class TestModelCallRecord:
    """Tests for ModelCallRecord dataclass."""

    def test_total_tokens(self):
        r = ModelCallRecord(model="test", input_tokens=100, output_tokens=50)
        assert r.total_tokens == 150

    def test_defaults(self):
        r = ModelCallRecord(model="test")
        assert r.success is True
        assert r.latency_ms == 0.0


class TestModelRouterRecord:
    """Tests for record_call() and metrics."""

    def test_record_call_computes_cost(self, router):
        """record_call() computes cost from profile data."""
        r = router.record_call(
            "fast-model",
            input_tokens=1_000_000,  # 1M input
            output_tokens=500_000,   # 500K output
        )
        # Cost = (1M/1M)*0.10 + (500K/1M)*0.20 = 0.10 + 0.10 = 0.20
        assert r.cost_usd == 0.20

    def test_record_call_unknown_model(self, router):
        """Unknown model has zero cost."""
        r = router.record_call("unknown-model")
        assert r.cost_usd == 0.0

    def test_get_metrics_empty(self, router):
        """No calls → empty metrics."""
        m = router.get_metrics()
        assert m["total_calls"] == 0

    def test_get_metrics_after_calls(self, router):
        """Metrics reflect recorded calls."""
        router.record_call("fast-model", input_tokens=1000, output_tokens=500, latency_ms=100.0, success=True)
        router.record_call("fast-model", input_tokens=500, output_tokens=200, latency_ms=200.0, success=True)
        router.record_call("reasoning-model", input_tokens=2000, output_tokens=1000, latency_ms=500.0, success=False)
        m = router.get_metrics()
        assert m["total_calls"] == 3
        assert m["models"]["fast-model"]["calls"] == 2
        assert m["models"]["fast-model"]["success"] == 2
        assert m["models"]["fast-model"]["failures"] == 0
        assert m["models"]["reasoning-model"]["failures"] == 1
        assert m["total_cost_usd"] > 0
        assert m["avg_latency_ms"] > 0

    def test_get_model_stats(self, router):
        """get_model_stats returns per-model data."""
        router.record_call("fast-model", latency_ms=150.0)
        stats = router.get_model_stats("fast-model")
        assert stats is not None
        assert stats["calls"] == 1

    def test_get_model_stats_none(self, router):
        """No calls for a model returns None."""
        stats = router.get_model_stats("nonexistent")
        assert stats is None


class TestModelRouterAutoFallback:
    """Tests for select_with_fallback() based on failure rates."""

    def test_no_fallback_on_success(self, router):
        """Low failure rate → no fallback."""
        for _ in range(5):
            router.record_call("fast-model", success=True)
        model, is_fallback = router.select_with_fallback(preferred="fast-model")
        assert model == "fast-model"
        assert is_fallback is False

    def test_auto_fallback_on_high_failures(self, router):
        """High failure rate → auto fallback."""
        for _ in range(5):
            router.record_call("fast-model", success=False)
        # preferred="fast-model" ensures primary is fast-model
        model, is_fallback = router.select_with_fallback(
            preferred="fast-model",
        )
        assert is_fallback is True
        assert model != "fast-model"

    def test_fallback_returns_next_best(self, router):
        """Fallback returns a working model."""
        # Record failures for fast-model
        for _ in range(5):
            router.record_call("fast-model", success=False)
        model, _ = router.select_with_fallback(capability="reasoning")
        # Should get reasoning-model (with reasoning capability)
        assert model == "reasoning-model"

    def test_no_fallback_with_few_calls(self, router):
        """Fewer than 3 calls → no auto fallback."""
        router.record_call("fast-model", success=False)
        router.record_call("fast-model", success=False)
        model, is_fallback = router.select_with_fallback(preferred="fast-model")
        assert is_fallback is False  # Only 2 calls, threshold is 3
        assert model == "fast-model"
