"""Tests for RoleRegistry — role package registry."""

from __future__ import annotations

from sccsos.roles import RoleRegistry, get_registry, reset_registry


class TestRoleRegistry:
    """RoleRegistry singleton and built-in roles."""

    def test_get_registry_singleton(self):
        """get_registry returns a RoleRegistry."""
        registry = get_registry()
        assert isinstance(registry, RoleRegistry)

    def test_get_registry_reuses_singleton(self):
        """get_registry returns the same instance each call."""
        reset_registry()
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_reset_registry(self):
        """reset_registry clears the singleton."""
        reset_registry()
        r1 = get_registry()
        reset_registry()
        r2 = get_registry()
        assert r1 is not r2

    def test_list_roles_contains_builtins(self):
        """list_roles returns built-in role packages."""
        reset_registry()
        registry = get_registry()
        roles = registry.list_roles()
        assert len(roles) > 0
        names = [r.name for r in roles]
        assert "architect" in names
        assert "doc-writer" in names
        assert "code-reviewer" in names
        assert "strategist" in names

    def test_get_role_returns_role(self):
        """get_role returns a RolePackage by name."""
        reset_registry()
        registry = get_registry()
        role = registry.get_role("architect")
        assert role is not None
        assert role.name == "architect"
        assert role.description != ""

    def test_get_role_unknown_returns_none(self):
        """get_role returns None for unknown role."""
        reset_registry()
        registry = get_registry()
        assert registry.get_role("nonexistent") is None

    def test_has_role_true(self):
        """has_role returns True for existing role."""
        reset_registry()
        registry = get_registry()
        assert registry.has_role("architect")
        assert registry.has_role("doc-writer")

    def test_has_role_false(self):
        """has_role returns False for unknown role."""
        reset_registry()
        registry = get_registry()
        assert not registry.has_role("nonexistent")

    def test_builtin_role_has_skills(self):
        """Built-in roles have hermes skills configured."""
        reset_registry()
        registry = get_registry()
        role = registry.get_role("architect")
        assert len(role.skills.hermes) > 0

    def test_builtin_role_has_files(self):
        """Built-in roles have files configured."""
        reset_registry()
        registry = get_registry()
        role = registry.get_role("architect")
        assert len(role.files.personalities) > 0
        assert len(role.files.agents) > 0
        assert len(role.files.workflows) > 0

    def test_builtin_role_has_profile(self):
        """Built-in roles have profile defaults."""
        reset_registry()
        registry = get_registry()
        role = registry.get_role("architect")
        assert role.hermes_profile.model != ""
        assert role.hermes_profile.temperature > 0
