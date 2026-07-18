"""Agent Registry — manage agent definitions.

AgentSpec represents a declarative agent definition loaded from YAML.
AgentRegistry manages the lifecycle of agent specs (register, find, list).
"""

from __future__ import annotations

import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

import yaml


logger = logging.getLogger("sccsos.registry")


@dataclass
class AgentLifecycle:
    """Lifecycle constraints for an agent."""
    max_turns: int = 90
    timeout: int = 1800
    auto_recover: bool = True


@dataclass
class AgentSpec:
    """Declarative agent definition (loaded from YAML)."""

    name: str
    version: str = "1.0"
    description: str = ""
    personality: str = ""
    profile: str = "sccsos"
    tenant_id: str = "default"
    model: Optional[str] = None
    toolsets: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    lifecycle: AgentLifecycle = field(default_factory=AgentLifecycle)
    policy: Optional[dict] = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AgentSpec":
        """Load an AgentSpec from a YAML file."""
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "name" not in data:
            raise ValueError(f"Agent YAML must have a 'name' field: {path}")

        lifecycle_data = data.pop("lifecycle", {})
        if isinstance(lifecycle_data, dict):
            data["lifecycle"] = AgentLifecycle(**lifecycle_data)
        else:
            data["lifecycle"] = AgentLifecycle()

        # policy is passed as raw dict (parsed by PolicyEngine)
        data.setdefault("policy", None)

        return cls(**data)

    def to_dict(self) -> dict:
        """Serialize to dict (for JSON storage)."""
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "AgentSpec":
        """Deserialize from dict."""
        lifecycle_data = data.pop("lifecycle", {})
        if isinstance(lifecycle_data, dict):
            data["lifecycle"] = AgentLifecycle(**lifecycle_data)
        else:
            data["lifecycle"] = AgentLifecycle()
        data.setdefault("policy", None)
        return cls(**data)


class AgentRegistry:
    """Registry for agent definitions.

    Manages a collection of AgentSpec objects, loaded from YAML files
    or registered programmatically.
    """

    def __init__(self, search_paths: Optional[list[str | Path]] = None):
        self._agents: dict[str, AgentSpec] = {}
        self._search_paths: list[Path] = []
        if search_paths:
            self._search_paths = [Path(p) for p in search_paths]

    def register(self, spec: AgentSpec) -> str:
        """Register an agent spec. Returns agent name."""
        if spec.name in self._agents:
            raise ValueError(f"Agent '{spec.name}' already registered")
        self._agents[spec.name] = spec
        return spec.name

    def unregister(self, name: str) -> None:
        """Remove an agent from the registry."""
        if name not in self._agents:
            raise KeyError(f"Agent '{name}' not found")
        del self._agents[name]

    def get(self, name: str) -> AgentSpec:
        """Get an agent spec by name."""
        if name not in self._agents:
            raise KeyError(f"Agent '{name}' not found")
        return self._agents[name]

    def find(self, name: str) -> Optional[AgentSpec]:
        """Find an agent by name, returning None if not found."""
        return self._agents.get(name)

    def list(self, tag: Optional[str] = None) -> list[AgentSpec]:
        """List all agents, optionally filtered by tag."""
        if tag:
            return [a for a in self._agents.values() if tag in a.tags]
        return list(self._agents.values())

    def list_names(self, tag: Optional[str] = None) -> list[str]:
        """List agent names, optionally filtered by tag."""
        return [a.name for a in self.list(tag=tag)]

    def load_from_dir(self, directory: str | Path) -> int:
        """Load all YAML agent definitions from a directory. Returns count."""
        directory = Path(directory)
        count = 0
        if not directory.exists():
            return 0

        for fpath in sorted(directory.iterdir()):
            if fpath.suffix in (".yaml", ".yml") and not fpath.name.startswith("."):
                try:
                    spec = AgentSpec.from_yaml(fpath)
                    self._agents[spec.name] = spec
                    count += 1
                except Exception as e:
                    # Log and skip invalid files
                    logger.warning("Skipping %s: %s", fpath.name, e)
        return count

    def count(self) -> int:
        """Number of registered agents."""
        return len(self._agents)

    def clear(self) -> None:
        """Remove all agents."""
        self._agents.clear()
