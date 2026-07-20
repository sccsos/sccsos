"""Tests for RBAC — Role-Based Access Control.

Tests cover:
  - Permission constants
  - Role definitions and permission sets
  - RoleChecker.check() for all roles and permissions
  - FastAPI dependency integration (require_permission)
  - Unauthorized exception
"""

from __future__ import annotations

import pytest

from sccsos.security.rbac import (
    P,
    ROLE_PERMISSIONS,
    VALID_ROLES,
    RoleChecker,
    Unauthorized,
    require_permission,
)


# ── Permission Constants ──────────────────────────────────────────────


class TestPermissions:
    def test_all_permissions_defined(self):
        """All permission constants should be non-empty strings."""
        for attr in dir(P):
            if attr.startswith("_") or attr.isupper():
                continue
            val = getattr(P, attr)
            assert isinstance(val, str) and len(val) > 0, f"{attr}={val}"

    def test_admin_wildcard(self):
        assert P.ADMIN == "admin:*"


# ── Role Definitions ─────────────────────────────────────────────────


class TestRoleDefinitions:
    def test_all_roles_have_permissions(self):
        """Every defined role must have a permission set."""
        for role in VALID_ROLES:
            assert role in ROLE_PERMISSIONS
            assert len(ROLE_PERMISSIONS[role]) > 0

    def test_admin_has_most_permissions(self):
        """Admin should have more permissions than any other role."""
        admin_perms = len(ROLE_PERMISSIONS["admin"])
        for role in VALID_ROLES:
            if role == "admin":
                continue
            assert len(ROLE_PERMISSIONS[role]) <= admin_perms

    def test_viewer_has_read_only(self):
        """Viewer should only have read permissions."""
        viewer_perms = ROLE_PERMISSIONS["viewer"]
        assert "agents:read" in viewer_perms
        assert "skills:read" in viewer_perms
        assert "quota:read" in viewer_perms
        assert "billing:read" in viewer_perms
        assert "traces:read" in viewer_perms
        assert "webhooks:read" in viewer_perms

        # Viewer should NOT have write permissions
        assert "agents:write" not in viewer_perms
        assert "agents:manage" not in viewer_perms
        assert "skills:approve" not in viewer_perms
        assert "quota:write" not in viewer_perms
        assert "webhooks:write" not in viewer_perms

    def test_operator_has_manage_not_approve(self):
        """Operator can manage agents but not approve skills."""
        op_perms = ROLE_PERMISSIONS["operator"]
        assert "agents:manage" in op_perms
        assert "agents:read" in op_perms
        assert "skills:read" in op_perms
        assert "skills:write" in op_perms
        assert "skills:approve" not in op_perms
        assert "quota:write" not in op_perms
        assert "webhooks:write" not in op_perms

    def test_admin_has_every_permission(self):
        """Admin should have all permissions defined."""
        all_perms = set()
        for attr in dir(P):
            if attr.startswith("_"):
                continue
            val = getattr(P, attr)
            if isinstance(val, str) and ":" in val:
                all_perms.add(val)

        admin_perms = ROLE_PERMISSIONS["admin"]
        for perm in all_perms:
            assert perm in admin_perms or "admin:*" in admin_perms

    def test_invalid_role_not_in_valid_roles(self):
        assert "superuser" not in VALID_ROLES
        assert "" not in VALID_ROLES


# ── RoleChecker ──────────────────────────────────────────────────────


class TestRoleChecker:
    def _make_checker(self) -> RoleChecker:
        return RoleChecker()

    def test_admin_can_do_everything(self):
        checker = self._make_checker()
        assert checker.check("admin", "agents:read")
        assert checker.check("admin", "agents:write")
        assert checker.check("admin", "skills:approve")
        assert checker.check("admin", "billing:export")
        assert checker.check("admin", "nonexistent:perm")  # admin:* covers all

    def test_viewer_read_only(self):
        checker = self._make_checker()
        assert checker.check("viewer", "agents:read")
        assert checker.check("viewer", "skills:read")
        assert checker.check("viewer", "billing:read")

        assert not checker.check("viewer", "agents:write")
        assert not checker.check("viewer", "agents:manage")
        assert not checker.check("viewer", "skills:approve")
        assert not checker.check("viewer", "quota:write")

    def test_operator_can_manage_agents(self):
        checker = self._make_checker()
        assert checker.check("operator", "agents:read")
        assert checker.check("operator", "agents:manage")
        assert checker.check("operator", "skills:write")
        assert checker.check("operator", "billing:read")

        assert not checker.check("operator", "skills:approve")
        assert not checker.check("operator", "quota:write")

    def test_invalid_role_returns_false(self):
        checker = self._make_checker()
        assert not checker.check("hacker", "agents:read")
        assert not checker.check("", "agents:read")

    def test_role_is_case_insensitive(self):
        checker = self._make_checker()
        assert checker.check("ADMIN", "agents:read")
        assert checker.check("Viewer", "skills:read")
        assert not checker.check("Viewer", "agents:write")

    def test_default_role_resolver(self):
        checker = self._make_checker()
        role = checker._default_role_resolver("admin")
        assert role == "admin"
        role = checker._default_role_resolver("")
        assert role == "viewer"  # Falls back to viewer
        role = checker._default_role_resolver("unknown")
        assert role == "viewer"  # Falls back to viewer


# ── FastAPI Dependency Integration ──────────────────────────────────


class TestRequirePermission:
    def test_permission_granted(self):
        """require_permission should raise nothing for valid role."""
        dep = require_permission("agents:read")
        # Simulate FastAPI calling the dependency with X-Role=admin
        dep("admin")  # Should not raise

    def test_permission_denied(self):
        """require_permission should raise Unauthorized for missing perm."""
        dep = require_permission("skills:approve")
        with pytest.raises(Unauthorized) as exc:
            dep("viewer")
        assert "Missing permission" in str(exc.value.detail)

    def test_permission_denied_with_role(self):
        """Unauthorized detail should mention the role."""
        dep = require_permission("agents:manage")
        with pytest.raises(Unauthorized) as exc:
            dep("viewer")
        assert "viewer" in str(exc.value.detail)

    def test_nonexistent_role_falls_back(self):
        """Unknown role should fall back to viewer."""
        dep = require_permission("agents:write")
        with pytest.raises(Unauthorized):
            dep("superadmin")

    def test_different_permission_names(self):
        """Test several specific permission checks."""
        for perm in ["agents:read", "skills:read", "quota:read",
                     "billing:read", "traces:read", "webhooks:read"]:
            dep = require_permission(perm)
            dep("admin")  # Should pass
            dep("viewer")  # Should pass (read perms)

        for perm in ["agents:write", "skills:approve", "quota:write",
                     "billing:export", "webhooks:write"]:
            dep = require_permission(perm)
            dep("admin")  # Should pass
            with pytest.raises(Unauthorized):
                dep("viewer")  # Should fail


# ── Unauthorized Exception ──────────────────────────────────────────


class TestUnauthorized:
    def test_default_message(self):
        exc = Unauthorized("agents:write")
        assert exc.status_code == 403
        assert "Missing permission" in exc.detail

    def test_with_role(self):
        exc = Unauthorized("skills:approve", role="viewer")
        assert "viewer" in exc.detail

    def test_is_http_exception(self):
        from fastapi import HTTPException
        exc = Unauthorized("test")
        assert isinstance(exc, HTTPException)
