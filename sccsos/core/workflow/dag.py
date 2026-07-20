"""DAG resolver — topological sort and cycle detection for workflow steps.

Extracted from ``orchestrator.py``.  Operates on a ``WorkflowDef``
and returns execution layers (parallel-capable groupings).
"""

from __future__ import annotations

from collections import deque
from typing import Optional

from sccsos.core.workflow.definition import (
    WorkflowDef,
    WorkflowStepDef,
    WorkflowValidationError,
)


class DAGResolver:
    """Resolves step dependencies into an execution order.

    Supports:
    - Topological sort for sequential dependencies
    - Parallel groups for concurrent execution
    - Cycle detection
    """

    def __init__(self, workflow: WorkflowDef):
        self._workflow = workflow
        self._step_map = {s.id: s for s in workflow.steps}
        self._validate()

    def _validate(self):
        """Validate step definitions."""
        if not self._workflow.steps:
            raise WorkflowValidationError("Workflow has no steps")

        for s in self._workflow.steps:
            if s.id not in self._step_map:
                raise WorkflowValidationError(f"Step ID conflict: {s.id}")
            for dep in s.depends_on:
                if dep not in self._step_map:
                    raise WorkflowValidationError(
                        f"Step '{s.id}' depends on unknown step '{dep}'"
                    )

        # Detect cycles
        visited = set()
        rec_stack = set()

        def _dfs(node):
            if node in rec_stack:
                raise WorkflowValidationError(
                    f"Cycle detected involving step '{node}'"
                )
            if node in visited:
                return
            visited.add(node)
            rec_stack.add(node)
            step = self._step_map[node]
            for dep in step.depends_on:
                _dfs(dep)
            rec_stack.remove(node)

        for s in self._workflow.steps:
            _dfs(s.id)

    def get_execution_order(self) -> list[list[str]]:
        """Return execution layers (list of lists for parallel execution).

        Each inner list contains step IDs that can run in parallel.
        The outer list enforces sequential ordering between layers.
        """
        in_degree = {s.id: len(s.depends_on) for s in self._workflow.steps}

        # Kahn's algorithm
        queue = deque([sid for sid, deg in in_degree.items() if deg == 0])
        layers = []

        while queue:
            layer = []
            for _ in range(len(queue)):
                sid = queue.popleft()
                layer.append(sid)
            layers.append(layer)

            for s in self._workflow.steps:
                if s.id in in_degree and in_degree[s.id] > 0:
                    scheduled = {i for layer in layers for i in layer}
                    if all(dep in scheduled for dep in s.depends_on):
                        in_degree[s.id] = 0
                        queue.append(s.id)

        scheduled = {sid for layer in layers for sid in layer}
        unscheduled = set(self._step_map.keys()) - scheduled
        if unscheduled:
            raise WorkflowValidationError(
                f"Cannot schedule steps: {unscheduled} (circular dependency?)"
            )

        return layers

    def get_step(self, step_id: str) -> WorkflowStepDef:
        """Get a step definition by ID."""
        if step_id not in self._step_map:
            raise KeyError(f"Step '{step_id}' not found")
        return self._step_map[step_id]
