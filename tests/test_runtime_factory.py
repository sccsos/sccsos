"""Tests for multi-tenant runtime factory — per-tenant isolation and lifecycle."""

from __future__ import annotations

import threading
import time

import pytest


class TestRuntimeFactory:
    """Tests for AgentRuntime factory (get_runtime / reset_runtime / set_runtime).

    These tests verify the factory's dict management, per-tenant isolation,
    and reset semantics without initializing real runtimes.

    Uses ``set_runtime`` with a mock instead to avoid side effects.
    """

    @pytest.fixture(autouse=True)
    def clean_factory(self):
        """Reset the factory before and after each test."""
        from sccsos.core.agent_runtime import reset_runtime
        reset_runtime()
        yield
        reset_runtime()

    def make_mock_runtime(self):
        """Create a minimal mock with close() for factory tracking."""
        import types
        rt = types.SimpleNamespace()
        rt._initialized = False
        rt._core = None
        rt.closed = False

        def close():
            rt.closed = True
        rt.close = close
        return rt

    def test_default_tenant_returns_same(self):
        """Default tenant returns the same instance on repeated calls."""
        from sccsos.core.agent_runtime import get_runtime, set_runtime

        r1 = self.make_mock_runtime()
        r2 = self.make_mock_runtime()
        set_runtime(r1)
        assert get_runtime() is r1
        assert get_runtime(tenant_id="default") is r1
        assert get_runtime() is not r2

    def test_tenant_isolation(self):
        """Different tenants get different runtime instances."""
        from sccsos.core.agent_runtime import get_runtime, set_runtime

        r_a = self.make_mock_runtime()
        r_b = self.make_mock_runtime()
        set_runtime(r_a, tenant_id="tenant-a")
        set_runtime(r_b, tenant_id="tenant-b")

        assert get_runtime("tenant-a") is r_a
        assert get_runtime("tenant-b") is r_b
        assert get_runtime("tenant-a") is not r_b

    def test_same_tenant_caching(self):
        """Same tenant returns cached instance."""
        from sccsos.core.agent_runtime import get_runtime, set_runtime

        r = self.make_mock_runtime()
        set_runtime(r, tenant_id="my-tenant")
        assert get_runtime("my-tenant") is r
        assert get_runtime("my-tenant") is r  # twice

    def test_tenant_isolation_from_default(self):
        """Custom tenant does not affect default tenant."""
        from sccsos.core.agent_runtime import get_runtime, set_runtime

        r_default = self.make_mock_runtime()
        r_custom = self.make_mock_runtime()
        set_runtime(r_default)
        set_runtime(r_custom, tenant_id="custom")

        assert get_runtime() is r_default
        assert get_runtime("custom") is r_custom
        assert get_runtime() is not r_custom

    def test_reset_single_tenant(self):
        """reset_runtime(tenant_id) removes only that tenant's runtime."""
        from sccsos.core.agent_runtime import get_runtime, set_runtime, reset_runtime

        r_a = self.make_mock_runtime()
        r_b = self.make_mock_runtime()
        set_runtime(r_a, tenant_id="tenant-a")
        set_runtime(r_b, tenant_id="tenant-b")

        reset_runtime(tenant_id="tenant-a")

        # r_a should be closed
        assert r_a.closed
        # r_b should remain
        assert get_runtime("tenant-b") is r_b
        assert not r_b.closed

    def test_reset_all_tenants(self):
        """reset_runtime() without args removes all runtimes."""
        from sccsos.core.agent_runtime import get_runtime, set_runtime, reset_runtime

        r_a = self.make_mock_runtime()
        r_b = self.make_mock_runtime()
        set_runtime(r_a, tenant_id="tenant-a")
        set_runtime(r_b, tenant_id="tenant-b")

        reset_runtime()

        assert r_a.closed
        assert r_b.closed

    def test_thread_safety(self):
        """Concurrent get_runtime calls do not race."""
        from sccsos.core.agent_runtime import get_runtime, set_runtime

        mock = self.make_mock_runtime()
        set_runtime(mock, tenant_id="shared")

        errors = []
        def access():
            try:
                for _ in range(50):
                    rt = get_runtime("shared")
                    assert rt is mock
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=access) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Thread safety errors: {errors}"

    def test_set_runtime_replaces_existing(self):
        """set_runtime replaces an existing tenant's runtime and closes old."""
        from sccsos.core.agent_runtime import get_runtime, set_runtime

        old = self.make_mock_runtime()
        new = self.make_mock_runtime()
        set_runtime(old, tenant_id="replaced")
        set_runtime(new, tenant_id="replaced")

        assert old.closed  # Old instance was closed
        assert get_runtime("replaced") is new  # New instance is active
