"""ContextBuilder — template rendering context assembly for workflow steps.

Assembles Jinja2 rendering context from:
- Step outputs (``{{ steps.xxx.response }}``)
- Knowledge base context (``{{ knowledge }}``)
- Persistent memory (``{{ memory }}``)
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from sccsos.core.templates import _render_template
from sccsos.memory.memory_store import MemoryStore


class ContextBuilder:
    """Build template context and resolve render function for a step."""

    def __init__(self,
                 knowledge_base: Any = None,
                 memory_store=None,
                 template_engine: Optional[Callable] = None):
        self._kb = knowledge_base
        self._memory_store = memory_store
        self._template_engine = template_engine

    def build(self, step, step_outputs: dict[str, dict],
              run_id: str) -> tuple[dict, Callable]:
        """Build template context and return (context, render_fn).

        Args:
            step: WorkflowStepDef for the current step.
            step_outputs: Dict of all completed step results (``{step_id: {...}}``).
            run_id: Current workflow run ID.

        Returns:
            Tuple of (template_context dict, render_function).
        """
        template_context: dict = {
            "steps": step_outputs,
            "run_id": run_id,
        }

        # Query knowledge base for relevant context (if configured)
        if self._kb is not None:
            kb_results = self._kb.get_context_for(
                f"{step.agent} {step.name} {step.prompt[:200]}"
            )
            if kb_results:
                template_context["knowledge"] = kb_results

        # Query persistent memory for this agent (if configured)
        if self._memory_store is not None:
            memory_data = self._memory_store.get_all(step.agent)
            if memory_data:
                template_context["memory"] = memory_data

        # Use injected template engine if available, fall back to default
        render_fn = self._template_engine or _render_template
        return template_context, render_fn
