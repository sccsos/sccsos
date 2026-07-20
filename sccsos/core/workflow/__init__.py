"""Workflow package — workflow data model, DAG resolver, and engine.

Extracted from ``orchestrator.py`` into four focused modules:

- **definition**: WorkflowDef, WorkflowStepDef, ParallelGroupDef, YAML load/migrate
- **dag**: DAGResolver (topological sort + cycle detection)
- **context**: WorkflowRunContext (per-run mutable state)
- **engine**: WorkflowEngine (orchestration logic)
"""

from sccsos.core.workflow.definition import (
    WorkflowDef,
    WorkflowStepDef,
    ParallelGroupDef,
    WorkflowValidationError,
    _migrate_workflow_schema,
)
from sccsos.core.workflow.dag import DAGResolver
from sccsos.core.workflow.context import WorkflowRunContext
from sccsos.core.workflow.engine import WorkflowEngine

__all__ = [
    "WorkflowDef",
    "WorkflowStepDef",
    "ParallelGroupDef",
    "WorkflowValidationError",
    "DAGResolver",
    "WorkflowRunContext",
    "WorkflowEngine",
]
