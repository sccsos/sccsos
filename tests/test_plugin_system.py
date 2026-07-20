"""Tests for the plugin system — PluginBase, registry, discovery, hooks."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sccsos.plugin import (
    PluginBase,
    PluginRegistry,
    get_registry,
    reset_registry,
    hook,
)


# ── Sample plugins for testing ───────────────────────────────────────


class HelloPlugin(PluginBase):
    """A simple test plugin."""

    @property
    def name(self) -> str:
        return "hello"

    @property
    def version(self) -> str:
        return "1.0.0"

    @hook
    def on_agent_start(self, agent_name: str) -> None:
        self._last_start = agent_name

    @hook
    def on_shutdown(self) -> None:
        self._shutdown_called = True


class MinimalPlugin(PluginBase):
    """Plugin with no hooks."""

    @property
    def name(self) -> str:
        return "minimal"

    @property
    def version(self) -> str:
        return "0.1.0"


class LifecyclePlugin(PluginBase):
    """Plugin that tracks load/unload."""

    @property
    def name(self) -> str:
        return "lifecycle"

    @property
    def version(self) -> str:
        return "2.0.0"

    def __init__(self):
        self.loaded = False
        self.unloaded = False

    def on_load(self) -> None:
        self.loaded = True

    def on_unload(self) -> None:
        self.unloaded = True


# ── Tests ────────────────────────────────────────────────────────────


class TestPluginBase:
    """PluginBase core functionality."""

    def test_plugin_has_name_and_version(self):
        plugin = HelloPlugin()
        assert plugin.name == "hello"
        assert plugin.version == "1.0.0"

    def test_plugin_description_from_docstring(self):
        plugin = HelloPlugin()
        assert "simple test plugin" in plugin.description

    def test_plugin_empty_description_for_no_docstring(self):
        class NoDocPlugin(PluginBase):
            @property
            def name(self) -> str:
                return "nodoc"

            @property
            def version(self) -> str:
                return "0.1.0"

        assert NoDocPlugin().description == ""

    def test_get_hooks_discovers_decorated_methods(self):
        plugin = HelloPlugin()
        hooks = plugin.get_hooks()
        assert "on_agent_start" in hooks
        assert "on_shutdown" in hooks
        assert callable(hooks["on_agent_start"])

    def test_minimal_plugin_has_no_hooks(self):
        plugin = MinimalPlugin()
        assert plugin.get_hooks() == {}


class TestPluginRegistry:
    """PluginRegistry registration and management."""

    def setup_method(self):
        reset_registry()

    def test_register_and_get(self):
        registry = PluginRegistry()
        p = HelloPlugin()
        registry.register(p)
        assert registry.get("hello") is p

    def test_register_duplicate_raises(self):
        registry = PluginRegistry()
        registry.register(HelloPlugin())
        with pytest.raises(ValueError, match="already registered"):
            registry.register(HelloPlugin())

    def test_unregister_removes_plugin(self):
        registry = PluginRegistry()
        p = HelloPlugin()
        registry.register(p)
        result = registry.unregister("hello")
        assert result is p
        assert registry.get("hello") is None

    def test_unregister_nonexistent_returns_none(self):
        registry = PluginRegistry()
        assert registry.unregister("nope") is None

    def test_list_returns_metadata(self):
        registry = PluginRegistry()
        registry.register(HelloPlugin())
        registry.register(MinimalPlugin())
        plugins = registry.list()
        assert len(plugins) == 2
        names = {p["name"] for p in plugins}
        assert "hello" in names
        assert "minimal" in names

    def test_count(self):
        registry = PluginRegistry()
        assert registry.count() == 0
        registry.register(HelloPlugin())
        assert registry.count() == 1

    def test_clear_unregisters_all(self):
        registry = PluginRegistry()
        registry.register(HelloPlugin())
        registry.register(MinimalPlugin())
        assert registry.count() == 2
        registry.clear()
        assert registry.count() == 0


class TestPluginLifecycle:
    """Plugin load/unload lifecycle."""

    def setup_method(self):
        reset_registry()

    def test_on_load_called_on_register(self):
        registry = PluginRegistry()
        p = LifecyclePlugin()
        registry.register(p)
        assert p.loaded is True

    def test_on_unload_called_on_unregister(self):
        registry = PluginRegistry()
        p = LifecyclePlugin()
        registry.register(p)
        registry.unregister("lifecycle")
        assert p.unloaded is True

    def test_on_load_failure_does_not_block_registry(self):
        registry = PluginRegistry()

        class FailingPlugin(PluginBase):
            @property
            def name(self) -> str:
                return "failing"

            @property
            def version(self) -> str:
                return "0.1.0"

            def on_load(self) -> None:
                raise RuntimeError("oops")

        # Should not raise — error is logged
        registry.register(FailingPlugin())
        assert registry.get("failing") is not None


class TestPluginHooks:
    """Hook dispatch."""

    def setup_method(self):
        reset_registry()

    def test_dispatch_calls_matching_hooks(self):
        registry = PluginRegistry()
        p = HelloPlugin()
        registry.register(p)

        registry.dispatch("on_agent_start", agent_name="architect")
        assert p._last_start == "architect"

    def test_dispatch_skips_non_existent_hooks(self):
        """Dispatching a hook no plugin implements should not error."""
        registry = PluginRegistry()
        p = MinimalPlugin()
        registry.register(p)

        # MinimalPlugin has no hooks — this should not raise
        registry.dispatch("on_agent_start", agent_name="tester")

    def test_dispatch_calls_all_plugins(self):
        registry = PluginRegistry()
        p1 = HelloPlugin()

        # A second plugin with on_agent_start hook
        class AnotherPlugin(PluginBase):
            @property
            def name(self) -> str:
                return "another"

            @property
            def version(self) -> str:
                return "1.0.0"

            def __init__(self):
                self._last_start = ""

            @hook
            def on_agent_start(self, agent_name: str) -> None:
                self._last_start = agent_name

        p2 = AnotherPlugin()
        registry.register(p1)
        registry.register(p2)

        registry.dispatch("on_agent_start", agent_name="builder")
        assert p1._last_start == "builder"
        assert p2._last_start == "builder"

    def test_has_hook(self):
        registry = PluginRegistry()
        p = HelloPlugin()
        registry.register(p)
        assert registry.has_hook("hello", "on_agent_start") is True
        assert registry.has_hook("hello", "on_nonexistent") is False
        assert registry.has_hook("nonexistent", "on_agent_start") is False

    def test_hook_failure_is_isolated(self):
        """A failing hook in one plugin should not affect other plugins."""
        registry = PluginRegistry()

        class BadPlugin(PluginBase):
            @property
            def name(self) -> str:
                return "bad"

            @property
            def version(self) -> str:
                return "0.1.0"

            @hook
            def on_agent_start(self, agent_name: str) -> None:
                raise RuntimeError("bad plugin crash")

        class GoodPlugin(PluginBase):
            @property
            def name(self) -> str:
                return "good"

            @property
            def version(self) -> str:
                return "1.0.0"

            def __init__(self):
                self._started = ""

            @hook
            def on_agent_start(self, agent_name: str) -> None:
                self._started = agent_name

        registry.register(BadPlugin())

        good = GoodPlugin()
        registry.register(good)

        # Should not raise — bad plugin error is caught and logged
        registry.dispatch("on_agent_start", agent_name="tester")
        assert good._started == "tester"


class TestPluginDiscovery:
    """File-based plugin discovery."""

    def setup_method(self):
        reset_registry()

    def test_discover_from_empty_dir(self):
        registry = PluginRegistry()
        with tempfile.TemporaryDirectory() as tmp:
            count = registry.discover_from_path(tmp)
        assert count == 0

    def test_discover_from_nonexistent_dir(self):
        registry = PluginRegistry()
        count = registry.discover_from_path("/nonexistent/plugins")
        assert count == 0

    def test_discover_single_plugin(self):
        registry = PluginRegistry()

        with tempfile.TemporaryDirectory() as tmp:
            plugin_code = '''
from sccsos.plugin import PluginBase, hook

class DiscoveredPlugin(PluginBase):
    @property
    def name(self):
        return "discovered"

    @property
    def version(self):
        return "1.0.0"

    @hook
    def on_agent_start(self, agent_name):
        self._started = agent_name
'''
            plugin_file = Path(tmp) / "my_plugin.py"
            plugin_file.write_text(plugin_code)

            count = registry.discover_from_path(tmp)

        assert count == 1
        p = registry.get("discovered")
        assert p is not None
        assert p.name == "discovered"
        assert "on_agent_start" in p.get_hooks()

    def test_discover_skips_private_files(self):
        registry = PluginRegistry()

        with tempfile.TemporaryDirectory() as tmp:
            # Create a private file (starts with _)
            private_file = Path(tmp) / "_helper.py"
            private_file.write_text("# this should be skipped")
            count = registry.discover_from_path(tmp)

        assert count == 0

    def test_discover_ignores_non_plugin_modules(self):
        registry = PluginRegistry()

        with tempfile.TemporaryDirectory() as tmp:
            not_plugin = Path(tmp) / "not_a_plugin.py"
            not_plugin.write_text("x = 1\\n")
            count = registry.discover_from_path(tmp)

        assert count == 0


class TestPluginSingleton:
    """Global plugin registry singleton."""

    def setup_method(self):
        reset_registry()

    def test_get_registry_returns_same_instance(self):
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_reset_registry_clears(self):
        r = get_registry()
        r.register(HelloPlugin())
        assert r.count() == 1

        reset_registry()
        r2 = get_registry()
        assert r2.count() == 0

    def test_singleton_persistence(self):
        r1 = get_registry()
        r1.register(HelloPlugin())

        r2 = get_registry()
        assert r2.get("hello") is not None
