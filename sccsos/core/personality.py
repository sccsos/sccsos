"""Personality system — persona definitions and system prompt injection.

Each agent can be assigned a personality that defines its system prompt,
default model, and behavior parameters. The personality is resolved at
task delegation time and injected as a prefix to the agent's prompt.

Usage:
    registry = PersonalityRegistry()
    registry.load_from_dir("./personalities")
    persona = registry.get("agent-architect")
    # → Personality(name="agent-architect", system_prompt="...")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class Personality:
    """A personality/persona definition for an agent.

    Attributes:
        name: Unique personality identifier (matches AgentSpec.personality).
        description: Human-readable description.
        system_prompt: Prompt prefix injected before every task prompt.
        model: Optional model override for agents using this personality.
        temperature: Sampling temperature (0.0-1.0, default 0.7).
    """
    name: str
    description: str = ""
    system_prompt: str = ""
    model: Optional[str] = None
    temperature: float = 0.7


@dataclass
class WrappedPrompt:
    """Result of wrapping a prompt with personality context."""
    prompt: str
    system_prompt: str = ""
    applied_personality: Optional[str] = None


class PersonalityRegistry:
    """Loads and looks up personality definitions from YAML files.

    Usage:
        registry = PersonalityRegistry()
        registry.load_from_dir("./personalities")
        persona = registry.get("agent-architect")
        wrapped = registry.wrap_prompt("agent-architect", "Design a module")
    """

    def __init__(self):
        self._personalities: dict[str, Personality] = {}

    def load_from_dir(self, directory: str | Path) -> int:
        """Load all YAML personality files from a directory. Returns count."""
        directory = Path(directory)
        count = 0
        if not directory.exists():
            return 0

        for fpath in sorted(directory.iterdir()):
            if fpath.suffix in (".yaml", ".yml") and not fpath.name.startswith("."):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    if data and "name" in data:
                        self._personalities[data["name"]] = Personality(
                            name=data["name"],
                            description=data.get("description", ""),
                            system_prompt=data.get("system_prompt", ""),
                            model=data.get("model"),
                            temperature=float(data.get("temperature", 0.7)),
                        )
                        count += 1
                except Exception:
                    pass  # Skip invalid files
        return count

    def register(self, personality: Personality) -> str:
        """Register a personality programmatically. Returns name."""
        self._personalities[personality.name] = personality
        return personality.name

    def get(self, name: str) -> Optional[Personality]:
        """Look up a personality by name."""
        return self._personalities.get(name)

    def list(self) -> list[Personality]:
        """List all registered personalities."""
        return list(self._personalities.values())

    def list_names(self) -> list[str]:
        """List all registered personality names."""
        return sorted(self._personalities.keys())

    def count(self) -> int:
        """Number of registered personalities."""
        return len(self._personalities)

    def wrap_prompt(self, personality_name: str | None, prompt: str) -> WrappedPrompt:
        """Wrap a prompt with a personality's system prompt.

        Args:
            personality_name: Personality name (or None to skip wrapping).
            prompt: Original prompt text.

        Returns:
            WrappedPrompt with the potentially modified prompt.
        """
        if not personality_name:
            return WrappedPrompt(prompt=prompt)

        persona = self._personalities.get(personality_name)
        if not persona or not persona.system_prompt:
            return WrappedPrompt(prompt=prompt)

        wrapped = (
            f"{persona.system_prompt.strip()}\n\n"
            f"---\n\n"
            f"{prompt}"
        )
        return WrappedPrompt(
            prompt=wrapped,
            system_prompt=persona.system_prompt,
            applied_personality=personality_name,
        )

    def clear(self) -> None:
        """Remove all registered personalities."""
        self._personalities.clear()
