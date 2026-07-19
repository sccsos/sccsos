"""Tests for ModelRouter — multi-model pool routing."""

from __future__ import annotations

import pytest

from sccsos.core.model_router import (
    ModelRouter, ModelProfile,
    FALLBACK_COST_ASC, FALLBACK_CAPABILITY_FIRST, FALLBACK_PREFER_FAST,
)


class TestModelRouterCore:
    """Basic selection and fallback."""

    def test_default_selection(self):
        router = ModelRouter.from_config(None)
        model = router.select()
        assert model == "deepseek-v4-flash"

    def test_preferred_model(self):
        router = ModelRouter.from_config({
            "default": "model-a",
            "profiles": {
                "model-a": {"provider": "test"},
                "model-b": {"provider": "test"},
            },
        })
        assert router.select(preferred="model-b") == "model-b"

    def test_preferred_unknown_falls_back_to_default(self):
        router = ModelRouter.from_config({
            "default": "default-model",
            "profiles": {
                "default-model": {"provider": "test"},
                "other": {"provider": "test"},
            },
        })
        assert router.select(preferred="nonexistent") == "default-model"

    def test_capability_matching(self):
        router = ModelRouter.from_config({
            "default": "general",
            "profiles": {
                "general": {"provider": "t", "capabilities": ["general"]},
                "reasoner": {"provider": "t", "capabilities": ["reasoning"]},
                "coder": {"provider": "t", "capabilities": ["coding"]},
            },
        })
        assert router.select(capability="reasoning") == "reasoner"
        assert router.select(capability="coding") == "coder"
        assert router.select(capability="general") == "general"

    def test_capability_chooses_cheapest(self):
        router = ModelRouter.from_config({
            "default": "cheap",
            "profiles": {
                "expensive": {
                    "provider": "t", "capabilities": ["reasoning"],
                    "cost_per_1m_input": 10.0,
                },
                "cheap": {
                    "provider": "t", "capabilities": ["reasoning"],
                    "cost_per_1m_input": 1.0,
                },
            },
        })
        assert router.select(capability="reasoning") == "cheap"

    def test_available_models(self):
        router = ModelRouter.from_config({
            "profiles": {
                "a": {"provider": "t"},
                "b": {"provider": "t"},
            },
        })
        models = router.available_models
        assert "a" in models
        assert "b" in models

    @property
    def default(self):
        router = ModelRouter.from_config({"default": "my-model", "profiles": {"my-model": {}}})
        return router.default


class TestModelRouterFallback:
    """Fallback strategies."""

    def test_fallback_cost_asc(self):
        router = ModelRouter(
            pool={
                "cheap": ModelProfile(name="cheap", cost_per_1m_input=0.1),
                "medium": ModelProfile(name="medium", cost_per_1m_input=1.0),
                "expensive": ModelProfile(name="expensive", cost_per_1m_input=10.0),
            },
            default_model="expensive",
            fallback_strategy=FALLBACK_COST_ASC,
        )
        # Fallback from expensive should pick cheapest (cheap)
        assert router.fallback("expensive") == "cheap"

    def test_fallback_skips_primary(self):
        router = ModelRouter(
            pool={
                "only": ModelProfile(name="only"),
                "other": ModelProfile(name="other"),
            },
            default_model="only",
        )
        # Fallback should skip "only" and return "other"
        fb = router.fallback("only")
        assert fb != "only"

    def test_fallback_to_default_when_no_alternative(self):
        router = ModelRouter(
            pool={"only": ModelProfile(name="only")},
            default_model="only",
        )
        fb = router.fallback("only")
        assert fb == "only"  # No alternative, back to default

    def test_fallback_prefer_fast(self):
        router = ModelRouter(
            pool={
                "slow": ModelProfile(name="slow", capabilities=["general"]),
                "fast-one": ModelProfile(name="fast-one", capabilities=["fast"]),
                "also-fast": ModelProfile(name="also-fast", capabilities=["fast"]),
            },
            default_model="slow",
            fallback_strategy=FALLBACK_PREFER_FAST,
        )
        fb = router.fallback("slow")
        assert fb in ("fast-one", "also-fast")
        assert fb != "slow"


class TestModelRouterCost:
    """Cost estimation."""

    def test_estimate_cost(self):
        router = ModelRouter(
            pool={
                "test-model": ModelProfile(
                    name="test-model",
                    cost_per_1m_input=1.0,
                    cost_per_1m_output=2.0,
                ),
            },
        )
        cost = router.estimate_cost("test-model", input_tokens=500_000, output_tokens=100_000)
        # input: 0.5M * $1.0/M = $0.50, output: 0.1M * $2.0/M = $0.20
        assert abs(cost - 0.70) < 0.001

    def test_estimate_cost_unknown_model(self):
        router = ModelRouter(default_model="x", pool={})
        assert router.estimate_cost("unknown", 100, 100) == 0.0


class TestModelRouterFromConfig:
    """Config parsing."""

    def test_full_config(self):
        config = {
            "default": "pro",
            "fallback_strategy": "capability_first",
            "profiles": {
                "fast": {
                    "provider": "deepseek",
                    "capabilities": ["fast", "general"],
                    "cost_per_1m_input": 0.14,
                    "cost_per_1m_output": 0.28,
                },
                "pro": {
                    "provider": "deepseek",
                    "capabilities": ["reasoning", "complex"],
                    "cost_per_1m_input": 0.44,
                    "cost_per_1m_output": 0.87,
                },
            },
        }
        router = ModelRouter.from_config(config)
        assert router.default == "pro"
        assert len(router.available_models) == 2
        assert router.select(capability="fast") == "fast"
        assert router.select(capability="reasoning") == "pro"

    def test_no_config_uses_builtin_defaults(self):
        router = ModelRouter.from_config(None)
        assert router.default == "deepseek-v4-flash"
        assert "deepseek-v4-flash" in router.available_models

    def test_empty_config_uses_builtin_defaults(self):
        router = ModelRouter.from_config({})
        assert router.default == "deepseek-v4-flash"
