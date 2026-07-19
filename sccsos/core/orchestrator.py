"""Workflow Orchestrator — DAG-based multi-agent workflow engine.

WorkflowDef defines a multi-step pipeline with dependency resolution,
parallel execution groups, and result aggregation.
"""

from __future__ import annotations

import concurrent.futures
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from sccsos.core.database import Database
from sccsos.core.hermes_adapter import HermesAdapter
from sccsos.core.config import AgentOSConfig
from sccsos.core.personality import PersonalityRegistry
from sccsos.core.step_executor import StepExecutor, WorkflowError, WorkflowExecutionError
from sccsos.observability.tracer import Tracer
from sccsos.observability.auditor import Auditor
from sccsos.observability.pricing import PricingTable
from sccsos.observability.webhook import WebhookNotifier
from sccsos.observability.alert_manager import AlertManager
from sccsos.memory.memory_store import MemoryStore


# ── Exceptions ──
# WorkflowError and WorkflowExecutionError imported from step_executor


class WorkflowValidationError(WorkflowError):
    """Workflow YAML is invalid."""
    pass


# ── Data Models ────────────────────────────────────────────────────


@dataclass
class WorkflowStepDef:
    """Definition of a single workflow step."""
    id: str
    name: str = ""
    agent: str = "architect"
    prompt: str = ""
    input: Optional[str] = None
    output: Optional[str] = None
    depends_on: list[str] = field(default_factory=list)
    timeout: int = 600
    retry: int = 0
    condition: Optional[str] = None  # Jinja2 expression; falsy → skip step


@dataclass
class ParallelGroupDef:
    """A group of steps that can run concurrently."""
    id: str
    steps: list[str] = field(default_factory=list)
    max_concurrent: int = 2


@dataclass
class WorkflowDef:
    """Complete workflow definition loaded from YAML."""
    name: str
    version: str = "1.0"
    description: str = ""
    steps: list[WorkflowStepDef] = field(default_factory=list)
    parallel_groups: list[ParallelGroupDef] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "WorkflowDef":
        """Load a WorkflowDef from a YAML file with schema validation."""
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "name" not in data:
            raise WorkflowValidationError(
                f"Workflow YAML must have a 'name' field: {path}"
            )

        if not isinstance(data.get("steps"), list) or len(data["steps"]) == 0:
            raise WorkflowValidationError(
                f"Workflow '{data.get('name', '?')}' must have at least one step: {path}"
            )

        # Validate each step definition
        step_ids = set()
        for i, s in enumerate(data["steps"]):
            if not isinstance(s, dict):
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' step[{i}] is not a dict: {path}"
                )
            if "id" not in s or not isinstance(s["id"], str) or not s["id"].strip():
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' step[{i}] missing 'id' field: {path}"
                )
            if s["id"] in step_ids:
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' duplicate step ID '{s['id']}': {path}"
                )
            step_ids.add(s["id"])
            if "agent" not in s:
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' step '{s['id']}' missing 'agent' field: {path}"
                )
            if "prompt" not in s and "condition" not in s and "input" not in s:
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' step '{s['id']}' "
                    f"must have 'prompt', 'input', or 'condition': {path}"
                )
            if "timeout" in s and (not isinstance(s["timeout"], int) or s["timeout"] < 1):
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' step '{s['id']}' "
                    f"invalid 'timeout': must be positive integer: {path}"
                )
            if "retry" in s and (not isinstance(s["retry"], int) or s["retry"] < 0):
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' step '{s['id']}' "
                    f"invalid 'retry': must be non-negative integer: {path}"
                )
            if "depends_on" in s:
                if not isinstance(s["depends_on"], list):
                    raise WorkflowValidationError(
                        f"Workflow '{data.get('name', '?')}' step '{s['id']}' "
                        f"'depends_on' must be a list: {path}"
                    )
                for dep in s["depends_on"]:
                    if not isinstance(dep, str):
                        raise WorkflowValidationError(
                            f"Workflow '{data.get('name', '?')}' step '{s['id']}' "
                            f"dependency '{dep}' is not a string: {path}"
                        )

        # Validate parallel_groups (if present)
        for gi, g in enumerate(data.get("parallel_groups", [])):
            if not isinstance(g, dict):
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' parallel_group[{gi}] is not a dict: {path}"
                )
            if "id" not in g:
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' parallel_group[{gi}] missing 'id': {path}"
                )
            if "steps" not in g or not isinstance(g["steps"], list):
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' parallel_group '{g.get('id', '?')}' "
                    f"missing or invalid 'steps' list: {path}"
                )
            for sid in g["steps"]:
                if sid not in step_ids:
                    raise WorkflowValidationError(
                        f"Workflow '{data.get('name', '?')}' parallel_group '{g['id']}' "
                        f"references unknown step '{sid}': {path}"
                    )

        steps = []
        for s in data.get("steps", []):
            steps.append(WorkflowStepDef(**s))

        parallel_groups = []
        for g in data.get("parallel_groups", []):
            parallel_groups.append(ParallelGroupDef(**g))

        return cls(
            name=data["name"],
            version=data.get("version", "1.0"),
            description=data.get("description", ""),
            steps=steps,
            parallel_groups=parallel_groups,
        )

    def to_yaml(self) -> str:
        """Serialize back to YAML."""
        data = {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "steps": [asdict(s) for s in self.steps],
        }
        if self.parallel_groups:
            data["parallel_groups"] = [asdict(g) for g in self.parallel_groups]
        return yaml.dump(data, default_flow_style=False, allow_unicode=True,
                         sort_keys=False)

    def to_mermaid(self) -> str:
        """Generate a Mermaid flowchart from the workflow DAG.

        Returns a Markdown-fenced Mermaid flowchart that renders
        natively in GitHub/GitLab, Obsidian, and Mermaid tools.

        Example output::

            ```mermaid
            flowchart TD
                requirements_analysis["Requirements Analysis"]
                architecture_design["Architecture Design"]
                requirements_analysis --> architecture_design
            ```
        """
        if not self.steps:
            return "```mermaid\nflowchart TD\n  empty[\"(no steps)\"]\n```"

        step_map = {s.id: s for s in self.steps}
        lines: list[str] = []
        lines.append("```mermaid")
        lines.append("flowchart TD")
        lines.append("")

        # Node definitions (use name if available, fall back to id)
        for s in self.steps:
            label = (s.name or s.id).replace('"', "'")
            # Escape special chars for Mermaid
            label = label.replace("[", "(").replace("]", ")")
            lines.append(f'    {s.id}["{label}"]')

        lines.append("")

        # Edge definitions
        for s in self.steps:
            for dep in s.depends_on:
                if dep in step_map:
                    lines.append(f"    {dep} --> {s.id}")

        # Parallel groups — annotate with subgraph if multiple steps
        for g in self.parallel_groups:
            if len(g.steps) > 1:
                label = (g.id or "parallel").replace('"', "'")
                lines.append("")
                lines.append(f"    subgraph {label} [\"{label}\"]")
                for sid in g.steps:
                    lines.append(f"        {sid}")
                lines.append("    end")

        lines.append("```")
        return "\n".join(lines)


# ── DAG Resolver ────────────────────────────────────────────────────


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
        # Compute in-degree for each step
        in_degree = {}
        for s in self._workflow.steps:
            in_degree[s.id] = len(s.depends_on)

        # Kahn's algorithm
        queue = deque([sid for sid, deg in in_degree.items() if deg == 0])
        layers = []

        while queue:
            layer = []
            for _ in range(len(queue)):
                sid = queue.popleft()
                layer.append(sid)
            layers.append(layer)

            # Decrease in-degree for dependents
            for s in self._workflow.steps:
                if s.id in in_degree and in_degree[s.id] > 0:
                    if all(dep in [i for layer in layers for i in layer]
                           for dep in s.depends_on):
                        in_degree[s.id] = 0
                        queue.append(s.id)

        # Verify all steps scheduled
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


# ── Workflow Run Context (thread-safe per-run state) ────────────────


@dataclass
class WorkflowRunContext:
    """Per-run context encapsulating mutable state for one workflow execution.

     Each call to ``WorkflowEngine.execute()`` creates its own context,
     stored in ``self._run_contexts[run_id]``.  This eliminates the
     thread-safety issue of sharing instance variables across concurrent
     ``execute()`` calls.
     """

    run_id: str
    workflow: WorkflowDef
    resolver: DAGResolver
    cancel_event: "threading.Event" = field(default_factory=threading.Event)
    parallel_group_map: dict[str, int] = field(default_factory=dict)
    step_group_map: dict[str, str] = field(default_factory=dict)


# ── Workflow Engine ────────────────────────────────────────────────


class WorkflowEngine:
    """Executes workflows by resolving DAG and delegating steps to agents."""

    def __init__(self, db: Database, adapter: HermesAdapter,
                 tracer: Optional[Tracer] = None,
                 auditor: Optional[Auditor] = None,
                 config: Optional[AgentOSConfig] = None,
                 registry: Optional["AgentRegistry"] = None,
                 knowledge_base: Optional["KnowledgeBase"] = None,
                 memory_store: Optional[MemoryStore] = None,
                 personality_registry: Optional[PersonalityRegistry] = None):
        self._db = db
        self._adapter = adapter
        self._tracer = tracer or Tracer(db)
        self._auditor = auditor or Auditor(db, PricingTable())
        self._config = config
        self._registry = registry
        self._kb = knowledge_base
        self._memory_store = memory_store
        self._personality_registry = personality_registry
        self._policy_engine = None
        self._db_lock = threading.Lock()
        # Per-run contexts (thread-safe: each execute() gets its own)
        self._run_contexts: dict[str, WorkflowRunContext] = {}
        self._notifier = WebhookNotifier(
            config.webhooks if config else None
        )
        # StepExecutor — isolated step execution
        self._step_executor: Optional[StepExecutor] = None
        # AlertManager — threshold monitoring
        self._alert_manager = AlertManager(db, config, self._notifier)
        if config is not None:
            from sccsos.security.policy import PolicyEngine
            try:
                self._policy_engine = PolicyEngine(db, config)
            except Exception:
                self._policy_engine = None

        # Create StepExecutor after all dependencies are ready
        self._step_executor = StepExecutor(
            db, adapter,
            tracer=self._tracer,
            auditor=self._auditor,
            config=config,
            registry=registry,
            knowledge_base=knowledge_base,
            memory_store=self._memory_store,
            personality_registry=personality_registry,
            policy_engine=self._policy_engine,
            db_lock=self._db_lock,
        )

    def validate(self, workflow: WorkflowDef) -> list[str]:
        """Validate a workflow. Returns list of warnings (empty = valid)."""
        warnings = []
        try:
            resolver = DAGResolver(workflow)
            resolver.get_execution_order()
        except WorkflowValidationError as e:
            raise
        except Exception as e:
            warnings.append(f"Validation warning: {e}")

        for s in workflow.steps:
            if not s.prompt and not s.input and not s.condition:
                warnings.append(f"Step '{s.id}' has no prompt, input, or condition")
        return warnings

    def execute(self, workflow: WorkflowDef,
                input_data: Optional[dict] = None) -> str:
        """Execute a workflow end-to-end. Returns run_id.

        Args:
            workflow: The workflow definition to execute.
            input_data: Optional dict injected as ``steps.input``
                in template context. Workflow steps can reference
                ``{{ steps.input.context }}``, ``{{ steps.input.query }}``,
                etc. depending on the keys provided.

        Example:
            engine.execute(wf, input_data={"context": "Build auth module"})
            # Step templates can use: {{ steps.input.context }}
        """
        run_id = f"wf_{uuid.uuid4().hex[:12]}"
        resolver = DAGResolver(workflow)

        # Build per-run context
        parallel_group_map: dict[str, int] = {
            g.id: g.max_concurrent for g in workflow.parallel_groups
        }
        step_group_map: dict[str, str] = {}
        for g in workflow.parallel_groups:
            for sid in g.steps:
                step_group_map[sid] = g.id

        ctx = WorkflowRunContext(
            run_id=run_id,
            workflow=workflow,
            resolver=resolver,
            parallel_group_map=parallel_group_map,
            step_group_map=step_group_map,
        )
        self._run_contexts[run_id] = ctx

        # Create trace
        trace_span = self._tracer.start_span(
            name=f"workflow:{workflow.name}",
            agent="orchestrator",
            trace_id=run_id,
        )

        # Record workflow start in audit
        self._auditor.record_llm_call(
            agent_id="orchestrator",
            model="system",
            tokens_input=0,
            tokens_output=0,
            success=True,
        )

        # Persist run
        self._db.execute(
            """INSERT INTO workflow_runs (id, workflow_name, workflow_content, status)
               VALUES (?, ?, ?, 'running')""",
            (run_id, workflow.name, yaml.dump(asdict(workflow))),
        )
        self._db.get_conn().commit()

        # Step results cache for template resolution
        step_outputs: dict[str, dict] = {}

        # Inject input data as synthetic step output.
        # Always present -- workflows can safely use {{ steps.input.context }}
        # even without --input (returns empty string).
        step_outputs["input"] = {"context": "", "stdout": ""}
        if input_data:
            step_outputs["input"] = {
                **input_data,
                "stdout": input_data.get("context", ""),
            }

        # Fire "started" event
        self._notifier.fire("started", run_id=run_id,
                            workflow_name=workflow.name, status="running")

        try:
            layers = ctx.resolver.get_execution_order()
            start_time = datetime.now(timezone.utc)

            for layer_idx, layer in enumerate(layers):
                if len(layer) == 1:
                    # Single step -- execute directly, no thread overhead
                    step = ctx.resolver.get_step(layer[0])
                    self._step_executor.execute_with_retry(
                        run_id, step, step_outputs, trace_span.span_id,
                        cancel_event=ctx.cancel_event,
                    )
                else:
                    # Multiple steps -- execute layer in parallel
                    self._execute_layer_parallel(
                        run_id, layer, step_outputs, trace_span.span_id, ctx
                    )

                self._db.get_conn().commit()

            # Mark run as completed
            end_time = datetime.now(timezone.utc)
            self._tracer.end_span(trace_span.span_id, status="ok")
            self._db.execute(
                """UPDATE workflow_runs SET status = 'completed',
                   finished_at = ? WHERE id = ?""",
                (end_time.isoformat(), run_id),
            )
            self._db.get_conn().commit()

            # Fire "completed" event
            self._notifier.fire("completed", run_id=run_id,
                                workflow_name=workflow.name, status="completed",
                                steps=list(step_outputs.keys()))
            # Evaluate alert thresholds
            self._alert_manager.evaluate_after_run(run_id=run_id)

        except Exception as e:
            self._tracer.end_span(trace_span.span_id, status="error")
            self._db.execute(
                """UPDATE workflow_runs SET status = 'failed', error = ?
                   WHERE id = ?""",
                (str(e), run_id),
            )
            self._db.get_conn().commit()

            # Fire "failed" event
            self._notifier.fire("failed", run_id=run_id,
                                workflow_name=workflow.name, status="failed",
                                error=str(e)[:500])
            # Evaluate alert thresholds (even on failure)
            self._alert_manager.evaluate_after_run(run_id=run_id)

            raise WorkflowExecutionError(f"Workflow '{workflow.name}' failed: {e}")

        finally:
            # Clean up per-run context (thread-safe)
            self._run_contexts.pop(run_id, None)

        return run_id

    def _get_max_concurrent(self, layer: list[str],
                            ctx: WorkflowRunContext) -> int:
        """Determine max concurrency for a layer.

        Checks parallel_groups for explicit constraints; otherwise
        defaults to running all steps in the layer concurrently.
        """
        # Check if all steps in the layer belong to the same parallel group
        group_ids = {ctx.step_group_map.get(sid) for sid in layer}
        group_ids.discard(None)  # Steps not in any group

        if len(group_ids) == 1:
            # All steps belong to the same group -- use group's max_concurrent
            gid = group_ids.pop()
            return ctx.parallel_group_map.get(gid, 3)
        elif len(group_ids) > 1:
            # Multiple groups in same layer -- use the most restrictive
            return min(
                ctx.parallel_group_map.get(gid, 3) for gid in group_ids
            )
        else:
            # No groups defined -- run all in parallel (up to 5)
            return min(len(layer), 5)

    def _execute_layer_parallel(
        self, run_id: str, layer: list[str],
        step_outputs: dict[str, dict],
        parent_span_id: str,
        ctx: WorkflowRunContext,
    ) -> None:
        """Execute a DAG layer's steps in parallel using a thread pool."""
        # Check cancellation before starting a new layer
        if ctx.cancel_event and ctx.cancel_event.is_set():
            raise WorkflowExecutionError("Workflow cancelled")

        max_workers = self._get_max_concurrent(layer, ctx)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="wf_step"
        ) as executor:
            future_to_step: dict[concurrent.futures.Future, str] = {}
            for step_id in layer:
                # Check cancellation before submitting each step
                if ctx.cancel_event and ctx.cancel_event.is_set():
                    for f in future_to_step:
                        f.cancel()
                    raise WorkflowExecutionError("Workflow cancelled")
                step = ctx.resolver.get_step(step_id)
                future = executor.submit(
                    self._step_executor.execute_with_retry,
                    run_id, step, step_outputs, parent_span_id,
                    cancel_event=ctx.cancel_event,
                )
                future_to_step[future] = step_id

            # Collect results -- bail on first failure
            errors: list[tuple[str, str]] = []
            for future in concurrent.futures.as_completed(future_to_step):
                step_id = future_to_step[future]
                try:
                    future.result()
                except WorkflowExecutionError as e:
                    errors.append((step_id, str(e)))
                    # Cancel remaining futures
                    for f in future_to_step:
                        f.cancel()
                    break
                except Exception as e:
                    errors.append((step_id, str(e)))
                    for f in future_to_step:
                        f.cancel()
                    break

            if errors:
                error_msg = "; ".join(
                    f"'{sid}': {err}" for sid, err in errors
                )
                raise WorkflowExecutionError(
                    f"Parallel step(s) failed: {error_msg}"
                )

    def get_run_status(self, run_id: str,
                       tenant_id: Optional[str] = None) -> dict:
        """Get the status of a workflow run.

        Args:
            run_id: Workflow run ID.
            tenant_id: Optional tenant ID filter for multi-tenant isolation.

        Returns:
            Run status dict with step details.
        """
        if tenant_id:
            row = self._db.fetchone(
                """SELECT * FROM workflow_runs
                   WHERE id = ? AND tenant_id = ?""",
                (run_id, tenant_id),
            )
        else:
            row = self._db.fetchone(
                "SELECT * FROM workflow_runs WHERE id = ?", (run_id,)
            )
        if not row:
            raise KeyError(f"Workflow run '{run_id}' not found")
        result = dict(row)

        # Get step statuses
        steps = self._db.execute(
            "SELECT * FROM workflow_steps WHERE run_id = ? ORDER BY id",
            (run_id,)
        ).fetchall()
        result["steps"] = [dict(s) for s in steps]
        return result

    def cancel_run(self, run_id: str,
                   tenant_id: Optional[str] = None) -> None:
        """Cancel a running workflow.

        Args:
            run_id: Workflow run ID.
            tenant_id: Optional tenant ID for multi-tenant isolation.
        """
        # Signal cancellation to running threads via per-run context
        ctx = self._run_contexts.get(run_id)
        if ctx is not None:
            ctx.cancel_event.set()

        if tenant_id:
            # Verify the run belongs to the tenant before cancelling
            row = self._db.fetchone(
                "SELECT id FROM workflow_runs WHERE id = ? AND tenant_id = ?",
                (run_id, tenant_id),
            )
            if not row:
                raise KeyError(f"Workflow run '{run_id}' not found for tenant '{tenant_id}'")
        self._db.execute(
            """UPDATE workflow_runs SET status = 'cancelled',
               finished_at = datetime('now') WHERE id = ?""",
            (run_id,),
        )
        self._db.get_conn().commit()

    def list_runs(self, limit: int = 20,
                  tenant_id: Optional[str] = None) -> list[dict]:
        """List recent workflow runs.

        Args:
            limit: Max number of runs to return.
            tenant_id: Optional tenant ID for multi-tenant isolation.

        Returns:
            List of run dicts.
        """
        if tenant_id:
            rows = self._db.execute(
                """SELECT * FROM workflow_runs WHERE tenant_id = ?
                   ORDER BY started_at DESC LIMIT ?""",
                (tenant_id, limit),
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM workflow_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
