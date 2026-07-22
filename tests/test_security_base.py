"""Tests for security base ABCs — PolicyEngineABC, SandboxABC, data classes."""

from __future__ import annotations

import pytest

from sccsos.security.base import (
    PolicyEngineABC,
    PolicyResult,
    PolicyViolation,
    SandboxABC,
    SandboxResult,
    SandboxViolation,
)


class TestPolicyResult:
    """PolicyResult dataclass."""

    def test_default(self):
        """Default PolicyResult allows."""
        r = PolicyResult()
        assert r.allowed
        assert r.reason == ""

    def test_denied(self):
        """Denied result with reason."""
        r = PolicyResult(allowed=False, reason="Budget exceeded")
        assert not r.allowed
        assert r.reason == "Budget exceeded"


class TestPolicyViolation:
    """PolicyViolation exception."""

    def test_is_exception(self):
        """PolicyViolation inherits from Exception."""
        assert issubclass(PolicyViolation, Exception)

    def test_can_raise(self):
        """PolicyViolation can be raised and caught."""
        with pytest.raises(PolicyViolation):
            raise PolicyViolation("blocked")


class TestPolicyEngineABC:
    """ABC default method implementations."""

    class _ConcretePolicyEngine(PolicyEngineABC):
        """Minimal concrete implementation for testing."""
        def check_delegation(self, agent_name="", model="", estimated_cost=0.0):
            return PolicyResult(allowed=True)

    @pytest.fixture
    def engine(self):
        return self._ConcretePolicyEngine()

    def test_check_tool_access_default(self, engine):
        """check_tool_access returns allowed by default."""
        result = engine.check_tool_access("agent-1", "terminal")
        assert result.allowed

    def test_check_agent_toolsets_default(self, engine):
        """check_agent_toolsets returns allowed by default."""
        result = engine.check_agent_toolsets("agent-1", ["terminal"])
        assert result.allowed

    def test_set_agent_policy_noop(self, engine):
        """set_agent_policy is a no-op by default (does not raise)."""
        engine.set_agent_policy("agent-1", {"budget": 10.0})
        # Should not raise


class TestSandboxResult:
    """SandboxResult dataclass."""

    def test_default(self):
        """Default SandboxResult allows."""
        r = SandboxResult()
        assert r.allowed
        assert r.reason == ""

    def test_blocked(self):
        """Blocked result with reason."""
        r = SandboxResult(allowed=False, reason="dangerous command")
        assert not r.allowed
        assert r.reason == "dangerous command"


class TestSandboxViolation:
    """SandboxViolation exception."""

    def test_is_exception(self):
        """SandboxViolation inherits from Exception."""
        assert issubclass(SandboxViolation, Exception)

    def test_can_raise(self):
        """SandboxViolation can be raised and caught."""
        with pytest.raises(SandboxViolation):
            raise SandboxViolation("blocked")


class TestSandboxABC:
    """ABC default method implementations."""

    class _ConcreteSandbox(SandboxABC):
        """Minimal concrete implementation for testing."""
        def check(self, command: str) -> SandboxResult:
            return SandboxResult(allowed=True)

    @pytest.fixture
    def sandbox(self):
        return self._ConcreteSandbox()

    def test_update_allowed_noop(self, sandbox):
        """update_allowed is a no-op by default."""
        sandbox.update_allowed(["ls", "pwd"])
        # Should not raise

    def test_to_config_returns_empty_dict(self, sandbox):
        """to_config returns empty dict by default."""
        assert sandbox.to_config() == {}

    def test_from_config_raises_not_implemented(self):
        """from_config raises NotImplementedError by default."""
        with pytest.raises(NotImplementedError):
            SandboxABC.from_config({})
