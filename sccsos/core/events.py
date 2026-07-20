"""Canonical event name constants for SCCS OS EventBus.

All producers and consumers should reference these constants instead of
raw strings to avoid typos.  Import from this module:

    from sccsos.core.events import WORKFLOW_STARTED, WORKFLOW_COMPLETED
"""

# ── Workflow events ────────────────────────────────────────────────

WORKFLOW_STARTED = "workflow.started"
WORKFLOW_COMPLETED = "workflow.completed"
WORKFLOW_FAILED = "workflow.failed"
WORKFLOW_CANCELLED = "workflow.cancelled"

# ── Step events ────────────────────────────────────────────────────

STEP_STARTED = "step.started"
STEP_COMPLETED = "step.completed"
STEP_FAILED = "step.failed"
STEP_SKIPPED = "step.skipped"
