"""SCCS OS Plugin System — SDK for extending platform capabilities.

A plugin is a Python class that subclasses ``PluginBase`` and implements
one or more hooks.  Plugins are discovered at runtime from a plugin
directory and registered with the PluginRegistry.

Usage::

    from sccsos.plugin import PluginBase, hook

    class MyPlugin(PluginBase):
        \"\"\"My custom extension.\"\"\"

        @property
        def name(self) -> str:
            return \"my-plugin\"

        @property
        def version(self) -> str:
            return \"1.0.0\"

        @hook
        def on_agent_start(self, agent_name: str) -> None:
            print(f\"Agent {agent_name} started\")

        @hook
        def on_workflow_complete(self, run_id: str) -> None:
            print(f\"Workflow {run_id} completed\")
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("sccsos.plugin")


# ── Hooks ─────────────────────────────────────────────────────────────

PLUGIN_HOOKS = {
    "on_agent_start": "Called when an agent starts. Args: agent_name (str)",
    "on_agent_stop": "Called when an agent stops. Args: agent_name (str)",
    "on_workflow_start": "Called when a workflow starts. Args: run_id (str)",
    "on_workflow_complete": "Called when a workflow completes. Args: run_id (str)",
    "on_workflow_fail": "Called when a workflow fails. Args: run_id (str), error (str)",
    "on_api_request": "Called before an API request is processed. Args: method (str), path (str)",
    "on_api_response": "Called after an API response is sent. Args: method (str), path (str), status (int)",
    "on_tool_call": "Called before a tool is invoked. Args: agent_name (str), tool (str)",
    "on_shutdown": "Called during system shutdown.",
}


def hook(func: Callable) -> Callable:
    """Decorator to mark a method as a plugin hook.

    Hooks are discovered at registration time.  Only methods decorated
    with ``@hook`` are called when the corresponding lifecycle event fires.
    """
    func._is_plugin_hook = True  # type: ignore[attr-defined]
    return func


# ── Plugin base class ────────────────────────────────────────────────


class PluginBase(ABC):
    """Base class for all SCCS OS plugins.

    Subclasses must define ``name`` and ``version`` as properties.
    Optional hooks (decorated with ``@hook``) are auto-discovered.

    Minimal example::

        class MyPlugin(PluginBase):
            @property
            def name(self) -> str:
                return \"my-plugin\"

            @property
            def version(self) -> str:
                return \"1.0.0\"
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin name (hyphen-separated, e.g. \"my-plugin\")."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Semantic version string (e.g. \"1.0.0\")."""
        ...

    @property
    def description(self) -> str:
        """Short description (default: class docstring)."""
        doc = self.__class__.__doc__
        return doc.strip() if doc else ""

    def get_hooks(self) -> dict[str, Callable]:
        """Discover hook methods decorated with ``@hook``."""
        hooks: dict[str, Callable] = {}
        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            if hasattr(method, "_is_plugin_hook") and method._is_plugin_hook:
                hooks[name] = method
        return hooks

    def on_load(self) -> None:
        """Called when the plugin is registered (for one-time setup)."""
        pass

    def on_unload(self) -> None:
        """Called when the plugin is unregistered (for cleanup)."""
        pass


# ── Plugin registry ──────────────────────────────────────────────────


class PluginRegistry:
    """Central registry for all plugins.

    Thread-safe: uses a dict lock for registration/unregistration.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, PluginBase] = {}

    # ── Registration ─────────────────────────────────────────────────

    def register(self, plugin: PluginBase) -> None:
        """Register a plugin instance.

        Raises:
            ValueError: If a plugin with the same name is already registered.
        """
        if plugin.name in self._plugins:
            raise ValueError(f"Plugin '{plugin.name}' is already registered (v{self._plugins[plugin.name].version})")
        self._plugins[plugin.name] = plugin
        try:
            plugin.on_load()
        except Exception:
            logger.exception("Plugin '%s' on_load() failed", plugin.name)
        logger.info("Plugin registered: %s v%s", plugin.name, plugin.version)

    def unregister(self, name: str) -> Optional[PluginBase]:
        """Unregister a plugin by name."""
        plugin = self._plugins.pop(name, None)
        if plugin:
            try:
                plugin.on_unload()
            except Exception:
                logger.exception("Plugin '%s' on_unload() failed", name)
            logger.info("Plugin unregistered: %s", name)
        return plugin

    def get(self, name: str) -> Optional[PluginBase]:
        """Get a registered plugin by name."""
        return self._plugins.get(name)

    def list(self) -> list[dict[str, Any]]:
        """List all registered plugins with metadata."""
        return [
            {
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "hooks": list(p.get_hooks().keys()),
            }
            for p in self._plugins.values()
        ]

    def count(self) -> int:
        return len(self._plugins)

    def clear(self) -> None:
        """Unregister all plugins."""
        for name in list(self._plugins.keys()):
            self.unregister(name)

    # ── Discovery ────────────────────────────────────────────────────

    def discover_from_path(self, plugin_dir: str | Path) -> int:
        """Discover and load plugins from a directory.

        Scans ``.py`` files in the directory (non-recursive), imports
        each module, and registers every ``PluginBase`` subclass found.

        Args:
            plugin_dir: Directory path containing plugin modules.

        Returns:
            Number of plugins successfully loaded.
        """
        plugin_dir = Path(plugin_dir)
        if not plugin_dir.is_dir():
            logger.warning("Plugin directory not found: %s", plugin_dir)
            return 0

        count = 0
        for py_file in sorted(plugin_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue  # Skip __init__.py, __pycache__, etc.
            try:
                loaded = self._load_module(py_file)
                count += loaded
            except Exception:
                logger.exception("Failed to load plugin from %s", py_file)
        return count

    def _load_module(self, py_file: Path) -> int:
        """Load a single Python file and register any plugins found."""
        module_name = py_file.stem

        # Add plugin dir to sys.path if needed
        plugin_dir = str(py_file.parent)
        if plugin_dir not in sys.path:
            sys.path.insert(0, plugin_dir)

        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            logger.warning("Cannot load spec for %s", py_file)
            return 0

        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)

        # Find all PluginBase subclasses in the module
        count = 0
        for obj_name in dir(mod):
            obj = getattr(mod, obj_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, PluginBase)
                and obj is not PluginBase
            ):
                try:
                    instance = obj()
                    self.register(instance)
                    count += 1
                except Exception:
                    logger.exception("Failed to instantiate plugin %s.%s", module_name, obj_name)
        return count

    # ── Hook dispatch ────────────────────────────────────────────────

    def dispatch(self, hook_name: str, **kwargs: Any) -> None:
        """Dispatch a lifecycle event to all plugins that implement the hook.

        Args:
            hook_name: Name of the hook (e.g. ``\"on_agent_start\"``).
            **kwargs: Arguments passed to the hook method.
        """
        for plugin in self._plugins.values():
            hook_method = getattr(plugin, hook_name, None)
            if hook_method is not None:
                try:
                    hook_method(**kwargs)
                except Exception:
                    logger.exception(
                        "Plugin '%s' hook '%s' failed",
                        plugin.name,
                        hook_name,
                    )

    def has_hook(self, name: str, hook_name: str) -> bool:
        """Check if a plugin implements a specific hook.

        Args:
            name: Plugin name.
            hook_name: Hook method name (e.g. \"on_agent_start\").

        Returns:
            True if the plugin has the hook.
        """
        plugin = self._plugins.get(name)
        if plugin is None:
            return False
        return hasattr(plugin, hook_name) and hasattr(
            getattr(plugin, hook_name), "_is_plugin_hook"
        )


# ── Singleton ────────────────────────────────────────────────────────


_registry: Optional[PluginRegistry] = None


def get_registry() -> PluginRegistry:
    """Get or create the global plugin registry singleton."""
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
    return _registry


def reset_registry() -> None:
    """Reset the global plugin registry (for testing)."""
    global _registry
    if _registry is not None:
        _registry.clear()
    _registry = None
