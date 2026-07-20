"""WorkflowRunContext — per-run mutable state for one workflow execution.

Each call to ``WorkflowEngine.execute()`` creates its own context,
eliminating thread-safety issues from shared instance variables.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from sccsos.core.workflow.definition import WorkflowDef
from sccsos.core.workflow.dag import DAGResolver


@dataclass
class WorkflowRunContext:
    """Per-run context encapsulating mutable state for one workflow execution."""

    run_id: str
    workflow: WorkflowDef
    resolver: DAGResolver
    cancel_event: threading.Event = field(default_factory=threading.Event)
    parallel_group_map: dict[str, int] = field(default_factory=dict)
    step_group_map: dict[str, str] = field(default_factory=dict)
