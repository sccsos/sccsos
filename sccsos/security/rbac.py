"""RBAC — Role-Based Access Control for the API layer.

Defines roles, permissions, and a RoleChecker for route-level
authorization in SCCS OS.

Roles (hierarchical):
  - admin    — Full system access (every permission)
  - operator — Operational access (manage agents, view monitoring)
  - viewer   — Read-only access (view agents, skills, billing, traces)

Usage in API routes::

    from sccsos.security.rbac import require_permission, Unauthorized

    @router.get("/agents")
    def list_agents(runtime=Depends(get_runtime),
                    _=Depends(require_permission("agents:read"))):
        ...

The ``require_permission`` dependency checks the ``X-Role`` header
(default: ``viewer``) against the required permission.  This can be
overridden for different auth backends (JWT, OIDC, etc.) by replacing
the resolver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from fastapi import Depends, Header, HTTPException, status


# ── Exceptions ───────────────────────────────────────────────────────


class Unauthorized(HTTPException):
    """Raised when a user lacks the required permission."""

    def __init__(self, permission: str, role: str = ""):
        detail = f"Missing permission '{permission}'"
        if role:
            detail += f" (role: {role})"
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


# ── Permission definitions ───────────────────────────────────────────


@dataclass(frozen=True)
class Permissions:
    """Permission constants — use these in require_permission()."""
    # Agents
    AGENTS_READ: str = "agents:read"
    AGENTS_WRITE: str = "agents:write"  # create/delete
    AGENTS_MANAGE: str = "agents:manage"  # start/stop/pause/resume

    # Skills
    SKILLS_READ: str = "skills:read"
    SKILLS_WRITE: str = "skills:write"  # publish/edit
    SKILLS_APPROVE: str = "skills:approve"  # approve/reject reviews

    # Quota
    QUOTA_READ: str = "quota:read"
    QUOTA_WRITE: str = "quota:write"

    # Billing
    BILLING_READ: str = "billing:read"
    BILLING_EXPORT: str = "billing:export"

    # Traces / Observability
    TRACES_READ: str = "traces:read"

    # Sessions
    SESSIONS_READ: str = "sessions:read"
    SESSIONS_WRITE: str = "sessions:write"

    # Webhooks
    WEBHOOKS_READ: str = "webhooks:read"
    WEBHOOKS_WRITE: str = "webhooks:write"

    # Admin (covers everything)
    ADMIN: str = "admin:*"


# Singleton
P = Permissions()


# ── Role definitions ──────────────────────────────────────────────────


ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        P.AGENTS_READ, P.AGENTS_WRITE, P.AGENTS_MANAGE,
        P.SKILLS_READ, P.SKILLS_WRITE, P.SKILLS_APPROVE,
        P.QUOTA_READ, P.QUOTA_WRITE,
        P.BILLING_READ, P.BILLING_EXPORT,
        P.TRACES_READ,
        P.SESSIONS_READ, P.SESSIONS_WRITE,
        P.WEBHOOKS_READ, P.WEBHOOKS_WRITE,
        P.ADMIN,
    },
    "operator": {
        P.AGENTS_READ, P.AGENTS_MANAGE,
        P.SKILLS_READ, P.SKILLS_WRITE,
        P.QUOTA_READ,
        P.BILLING_READ,
        P.TRACES_READ,
        P.SESSIONS_READ,
        P.WEBHOOKS_READ,
    },
    "viewer": {
        P.AGENTS_READ,
        P.SKILLS_READ,
        P.QUOTA_READ,
        P.BILLING_READ,
        P.TRACES_READ,
        P.SESSIONS_READ,
        P.WEBHOOKS_READ,
    },
}

VALID_ROLES: set[str] = set(ROLE_PERMISSIONS.keys())


# ── RoleChecker ──────────────────────────────────────────────────────


class RoleChecker:
    """Lightweight role-based permission checker.

    Can be used as a FastAPI dependency via ``require_permission()``.
    """

    def __init__(self) -> None:
        self._resolve_role = self._default_role_resolver

    def set_role_resolver(self, resolver) -> None:
        """Replace the default header-based role resolver.

        Args:
            resolver: A callable that returns a role string
                (e.g., from JWT, OIDC, or database).
        """
        self._resolve_role = resolver

    def _default_role_resolver(self, x_role: str = "viewer") -> str:
        """Default resolver: read from X-Role header."""
        role = (x_role or "viewer").strip().lower()
        return role if role in VALID_ROLES else "viewer"

    def check(self, role: str, permission: str) -> bool:
        """Check if a role has a specific permission.

        Args:
            role: Role name (admin, operator, viewer).
            permission: Permission string (e.g., ``"agents:read"``).

        Returns:
            True if the role has the permission.
        """
        role = role.strip().lower()
        if role not in VALID_ROLES:
            return False
        perms = ROLE_PERMISSIONS[role]
        # admin:* covers everything
        return permission in perms or P.ADMIN in perms

    def __call__(self, role: str) -> bool:
        """Convenience for direct calls: ``checker(role, perm)``."""
        return self.check(role, "")


# Global singleton
_checker = RoleChecker()


# ── FastAPI dependency ───────────────────────────────────────────────


def require_permission(permission: str):
    """FastAPI dependency factory: require a permission for the route.

    Usage::

        @router.get("/agents")
        def list_agents(
            _: None = Depends(require_permission("agents:read")),
            runtime=Depends(get_runtime),
        ):
            ...

    The role is resolved from the ``X-Role`` HTTP header by default.
    """
    def _dependency(x_role: str = Header("viewer", alias="X-Role")) -> None:
        role = x_role.strip().lower() if x_role else "viewer"
        if role not in VALID_ROLES:
            role = "viewer"
        if not _checker.check(role, permission):
            raise Unauthorized(permission, role)
    return _dependency


def get_role_checker() -> RoleChecker:
    """Return the global RoleChecker singleton (useful for test injection)."""
    return _checker
