"""Tests for CommandWhitelist security sandbox."""

from __future__ import annotations

import pytest

from sccsos.security.sandbox import CommandWhitelist


class TestCommandWhitelist:
    """CommandWhitelist — dangerous patterns, whitelist, and edge cases."""

    def test_empty_command_allowed(self):
        """Empty or whitespace-only command is allowed."""
        wl = CommandWhitelist(allowed_commands=["echo"])
        assert wl.check("").allowed
        assert wl.check("   ").allowed

    def test_max_length_exceeded(self):
        """Command exceeding max length is blocked."""
        wl = CommandWhitelist(allowed_commands=["echo"], max_length=10)
        result = wl.check("echo " + "x" * 20)
        assert not result.allowed
        assert "exceeds max length" in result.reason

    def test_extra_dangerous_patterns(self):
        """Extra dangerous patterns from config are checked."""
        wl = CommandWhitelist(
            allowed_commands=["echo"],
            dangerous_patterns=["dropdb", ""],  # empty pattern triggers continue
        )
        result = wl.check("echo dropdb mydb")
        assert not result.allowed
        assert "dropdb" in result.reason

    def test_shlex_split_error(self):
        """Malformed quotes cause shlex.split to fail gracefully."""
        wl = CommandWhitelist(allowed_commands=[])
        # Unmatched quote causes shlex ValueError, fallback to simple split
        result = wl.check("echo 'hello")
        assert not result.allowed
        assert "not in whitelist" in result.reason

    def test_update_allowed_replaces(self):
        """update_allowed replaces the allowed command set."""
        wl = CommandWhitelist(allowed_commands=["echo"])
        wl.update_allowed(["git", "python3"])
        assert wl.check("git status").allowed
        assert not wl.check("echo hello").allowed

    def test_allow_all_mode(self):
        """allow_all=True bypasses whitelist but not dangerous patterns."""
        wl = CommandWhitelist(allow_all=True)
        assert wl.check("any command").allowed
        # But dangerous patterns still blocked
        result = wl.check("rm -rf /")
        assert not result.allowed

    def test_to_config_roundtrip(self):
        """to_config and from_config preserve settings."""
        wl = CommandWhitelist(
            allowed_commands=["git", "python3"],
            allow_all=False,
            dangerous_patterns=["rm -rf"],
        )
        cfg = wl.to_config()
        restored = CommandWhitelist.from_config(cfg)
        assert restored._allowed == {"git", "python3"}
