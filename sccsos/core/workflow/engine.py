"""WorkflowEngine — orchestrates DAG-based multi-agent workflow execution.

This module contains the core orchestration logic: resolving execution
order, dispatching steps to the StepExecutor, and managing parallel
execution groups.  The workflow data model, DAG resolver, and run
context live in sibling modules.
"""

from __future__ import annotations

import concurrent.futures
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

import yaml

from sccsos.core.db import Database
from sccsos.core.db import crud
from sccsos.core.hermes_adapter import HermesAdapter
from sccsos.core.event_bus import get_bus
from sccsos.core.events import (
    WORKFLOW_STARTED, WORKFLOW_COMPLETED, WORKFLOW_FAILED,
)
from sccsos.core.config import AgentOSConfig
from sccsos.core.personality import PersonalityRegistry
from sccsos.core.step_executor import StepExecutor, StepExecutorBuilder, WorkflowError, WorkflowExecutionError
from sccsos.core.workflow.definition import (
    WorkflowDef,
    WorkflowValidationError,
)
from sccsos.core.workflow.dag import DAGResolver
from sccsos.core.workflow.context import WorkflowRunContext
from sccsos.observability.tracer import Tracer
from sccsos.observability.auditor import Auditor
from sccsos.observability.pricing import PricingTable
from sccsos.memory.memory_store import MemoryStore


class WorkflowEngine:
    """Executes workflows by resolving DAG and delegating steps to agents."""

    def __init__(self, db: Database, adapter: HermesAdapter,
                 tracer: Optional[Tracer] = None,
                 auditor: Optional[Auditor] = None,
                 config: Optional[AgentOSConfig] = None,
                 registry: Optional["AgentRegistry"] = None,
                 knowledge_base: Optional["KnowledgeBase"] = None,
                 memory_store: Optional[MemoryStore] = None,
                 personality_registry: Optional[PersonalityRegistry] = None,
                 model_router=None):
        self._db = db
        self._adapter = adapter
        self._tracer = tracer or Tracer(db)
        self._auditor = auditor or Auditor(db, PricingTable())
        self._config = config
        self._registry = registry
        self._kb = knowledge_base
        self._memory_store = memory_store
        self._personality_registry = personality_registry
        self._model_router = model_router
        self._policy_engine = None
        self._db_lock = threading.Lock()
        self._run_contexts: dict[str, WorkflowRunContext] = {}
        self._bus = get_bus()
        if config is not None:
            from sccsos.security.policy import PolicyEngine
            try:
                self._policy_engine = PolicyEngine(db, config)
            except Exception as e:
                import logging
                _pe_logger = logging.getLogger("sccsos.security")
                _pe_logger.critical(
                    "PolicyEngine init failed — policy enforcement DISABLED: %s", e,
                )
                self._policy_engine = None

        self._step_executor = (StepExecutorBuilder(db, adapter)
            .with_tracer(self._tracer)
            .with_auditor(self._auditor)
            .with_config(config)
            .with_registry(registry)
            .with_knowledge_base(knowledge_base)
            .with_memory_store(self._memory_store)
            .with_personality_registry(personality_registry)
            .with_policy_engine(self._policy_engine)
            .with_db_lock(self._db_lock)
            .with_model_router(model_router)
            .build()
        )

    def validate(self, workflow: WorkflowDef) -> list[str]:
        """Validate a workflow. Returns list of warnings (empty = valid)."""
        warnings = []
        try:
            resolver = DAGResolver(workflow)
            resolver.get_execution_order()
        except WorkflowValidationError:
            raise
        except Exception as e:
            warnings.append(f"Validation warning: {e}")

        for s in workflow.steps:
            if not s.prompt and not s.input and not s.condition:
                warnings.append(f"Step '{s.id}' has no prompt, input, or condition")
        return warnings

    def execute(self, workflow: WorkflowDef,
                input_data: Optional[dict] = None) -> str:
        """Execute a workflow end-to-end. Returns run_id."""
        run_id = f"wf_{uuid.uuid4().hex[:12]}"
        resolver = DAGResolver(workflow)

        parallel_group_map = {
            g.id: g.max_concurrent for g in workflow.parallel_groups
        }
        step_group_map = {}
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

        trace_span = self._tracer.start_span(
            name=f"workflow:{workflow.name}",
            agent="orchestrator",
            trace_id=run_id,
        )

        self._auditor.record_llm_call(
            agent_id="orchestrator",
            model="system",
            tokens_input=0,
            tokens_output=0,
            success=True,
        )

        crud.insert_workflow_run(
            self._db, run_id, workflow.name, yaml.dump(asdict(workflow)),
        )

        step_outputs: dict[str, dict] = {}
        step_outputs["input"] = {"context": "", "stdout": ""}
        if input_data:
            step_outputs["input"] = {
                **input_data,
                "stdout": input_data.get("context", ""),
            }

        self._bus.emit(WORKFLOW_STARTED,
                       run_id=run_id, workflow_name=workflow.name,
                       status="running")

        try:
            layers = ctx.resolver.get_execution_order()
            for layer_idx, layer in enumerate(layers):
                if len(layer) == 1:
                    step = ctx.resolver.get_step(layer[0])
                    self._step_executor.execute_with_retry(
                        run_id, step, step_outputs, trace_span.span_id,
                        cancel_event=ctx.cancel_event,
                    )
                else:
                    self._execute_layer_parallel(
                        run_id, layer, step_outputs, trace_span.span_id, ctx
                    )
                self._db.commit()

            end_time = datetime.now(timezone.utc)
            crud.update_workflow_run_status(
                self._db, run_id, "completed", finished_at=end_time.isoformat(),
            )
            self._bus.emit(WORKFLOW_COMPLETED,
                           run_id=run_id, workflow_name=workflow.name,
                           status="completed", steps=list(step_outputs.keys()))
            self._tracer.end_span(trace_span.span_id, status="ok")

        except Exception as e:
            self._tracer.end_span(trace_span.span_id, status="error")
            crud.update_workflow_run_status(
                self._db, run_id, "failed", error=str(e),
            )
            self._bus.emit(WORKFLOW_FAILED,
                           run_id=run_id, workflow_name=workflow.name,
                           status="failed", error=str(e)[:500])
            raise WorkflowExecutionError(f"Workflow '{workflow.name}' failed: {e}")

        finally:
            self._run_contexts.pop(run_id, None)

        return run_id

    def _get_max_concurrent(self, layer: list[str],
                            ctx: WorkflowRunContext) -> int:
        group_ids = {ctx.step_group_map.get(sid) for sid in layer}
        group_ids.discard(None)

        if len(group_ids) == 1:
            gid = group_ids.pop()
            return ctx.parallel_group_map.get(gid, 3)
        elif len(group_ids) > 1:
            return min(ctx.parallel_group_map.get(gid, 3) for gid in group_ids)
        else:
            return min(len(layer), 5)

    def _execute_layer_parallel(
        self, run_id: str, layer: list[str],
        step_outputs: dict[str, dict],
        parent_span_id: str,
        ctx: WorkflowRunContext,
    ) -> None:
        if ctx.cancel_event and ctx.cancel_event.is_set():
            raise WorkflowExecutionError("Workflow cancelled")

        max_workers = self._get_max_concurrent(layer, ctx)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="wf_step"
        ) as executor:
            future_to_step = {}
            for step_id in layer:
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

            errors = []
            for future in concurrent.futures.as_completed(future_to_step):
                step_id = future_to_step[future]
                try:
                    future.result()
                except (WorkflowExecutionError, Exception) as e:
                    errors.append((step_id, str(e)))
                    for f in future_to_step:
                        f.cancel()
                    break

            if errors:
                error_msg = "; ".join(f"'{sid}': {err}" for sid, err in errors)
                raise WorkflowExecutionError(f"Parallel step(s) failed: {error_msg}")

    def get_run_status(self, run_id: str,
                       tenant_id: Optional[str] = None) -> dict:
        if tenant_id:
            row = self._db.fetchone(
                "SELECT * FROM workflow_runs WHERE id = ? AND tenant_id = ?",
                (run_id, tenant_id),
            )
        else:
            row = self._db.fetchone(
                "SELECT * FROM workflow_runs WHERE id = ?", (run_id,)
            )
        if not row:
            raise KeyError(f"Workflow run '{run_id}' not found")
        result = dict(row)
        steps = crud.get_workflow_steps(self._db, run_id)
        result["steps"] = steps
        return result

    def cancel_run(self, run_id: str,
                   tenant_id: Optional[str] = None) -> None:
        ctx = self._run_contexts.get(run_id)
        if ctx is not None:
            ctx.cancel_event.set()

        # Verify the run exists before cancelling
        row = crud.get_workflow_run(self._db, run_id, tenant_id=tenant_id)
        if tenant_id and not row:
            raise KeyError(f"Workflow run '{run_id}' not found for tenant '{tenant_id}'")
        crud.update_workflow_run_status(self._db, run_id, "cancelled")

    def list_runs(self, limit: int = 20,
                  tenant_id: Optional[str] = None) -> list[dict]:
        return crud.list_workflow_runs(self._db, limit=limit, tenant_id=tenant_id)
