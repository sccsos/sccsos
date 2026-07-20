"""Tests for SubscriptionManager — multi-tier billing plans."""
from __future__ import annotations

import os
import tempfile

import pytest

from sccsos.core.db import Database
from sccsos.observability.billing import (
    SubscriptionManager, SubscriptionPlan, PricingTier,
)


@pytest.fixture
def db():
    tmp = tempfile.mktemp(suffix=".db")
    database = Database(db_path=tmp)
    database.initialize()
    yield database
    database.close()
    os.unlink(tmp)


@pytest.fixture
def mgr(db):
    return SubscriptionManager(db)


class TestSubscriptionCRUD:
    """Subscription plan CRUD operations."""

    def test_get_default_plan(self, mgr):
        plan = mgr.get_plan("nonexistent")
        assert plan.tenant_id == "nonexistent"
        assert plan.tier == PricingTier.PAY_PER_TOKEN
        assert plan.monthly_fee == 0.0

    def test_set_and_get_plan(self, mgr):
        plan = SubscriptionPlan(
            tenant_id="tenant-1",
            tier=PricingTier.SUBSCRIPTION,
            monthly_fee=99.0,
            active=True,
        )
        updated = mgr.set_plan(plan)
        assert updated.tenant_id == "tenant-1"
        assert updated.tier == PricingTier.SUBSCRIPTION
        assert updated.monthly_fee == 99.0

        fetched = mgr.get_plan("tenant-1")
        assert fetched.tier == PricingTier.SUBSCRIPTION
        assert fetched.monthly_fee == 99.0

    def test_set_per_call_plan(self, mgr):
        plan = SubscriptionPlan(
            tenant_id="caller-1",
            tier=PricingTier.PER_CALL,
            flat_fee_per_call=0.05,
        )
        mgr.set_plan(plan)
        fetched = mgr.get_plan("caller-1")
        assert fetched.tier == PricingTier.PER_CALL
        assert fetched.flat_fee_per_call == 0.05

    def test_update_plan(self, mgr):
        mgr.set_plan(SubscriptionPlan(tenant_id="updatable", monthly_fee=50.0))
        mgr.set_plan(SubscriptionPlan(tenant_id="updatable", monthly_fee=100.0))
        fetched = mgr.get_plan("updatable")
        assert fetched.monthly_fee == 100.0

    def test_list_plans(self, mgr):
        mgr.set_plan(SubscriptionPlan(tenant_id="a", monthly_fee=10.0))
        mgr.set_plan(SubscriptionPlan(tenant_id="b", monthly_fee=20.0))
        plans = mgr.list_plans()
        assert len(plans) == 2
        assert {p.tenant_id for p in plans} == {"a", "b"}

    def test_reset_plan(self, mgr):
        mgr.set_plan(SubscriptionPlan(tenant_id="to-reset", monthly_fee=50.0))
        mgr.reset_plan("to-reset")
        # After reset, should return defaults
        plan = mgr.get_plan("to-reset")
        assert plan.tenant_id == "to-reset"
        assert plan.tier == PricingTier.PAY_PER_TOKEN
        assert plan.monthly_fee == 0.0


class TestTierCostCalculation:
    """Cost calculation for different pricing tiers."""

    def test_pay_per_token(self, mgr):
        cost = mgr.calculate_cost("default", tokens_used=1000, model="gpt-4")
        # gpt-4 rate = 0.03 per 1M tokens → cost = 1000 * 0.03 / 1M
        assert cost == pytest.approx(0.00003, rel=1e-3)

    def test_pay_per_token_custom_rate(self, mgr):
        mgr.set_plan(SubscriptionPlan(
            tenant_id="custom-rate",
            tier=PricingTier.PAY_PER_TOKEN,
            model_rates={"default": 0.05},
        ))
        cost = mgr.calculate_cost("custom-rate", tokens_used=100000)
        assert cost == pytest.approx(0.005, rel=1e-3)

    def test_per_call(self, mgr):
        mgr.set_plan(SubscriptionPlan(
            tenant_id="per-call-1",
            tier=PricingTier.PER_CALL,
            flat_fee_per_call=0.02,
        ))
        cost = mgr.calculate_cost("per-call-1", tokens_used=0, calls=3)
        assert cost == 0.06  # 3 × 0.02

    def test_subscription(self, mgr):
        mgr.set_plan(SubscriptionPlan(
            tenant_id="sub-1",
            tier=PricingTier.SUBSCRIPTION,
            monthly_fee=199.0,
        ))
        cost = mgr.calculate_cost("sub-1", tokens_used=1000000, calls=100)
        assert cost == 0.0  # No per-event cost

    def test_inactive_plan(self, mgr):
        mgr.set_plan(SubscriptionPlan(
            tenant_id="inactive",
            tier=PricingTier.PER_CALL,
            flat_fee_per_call=0.10,
            active=False,
        ))
        cost = mgr.calculate_cost("inactive", tokens_used=0, calls=1)
        assert cost == 0.0  # Inactive = free

    def test_model_rates_fallback(self, mgr):
        cost = mgr.calculate_cost("default", tokens_used=5000, model="unknown-model")
        # Falls back to "default" rate = 0.01
        assert cost == pytest.approx(0.00005, rel=1e-3)
