"""Step Executor — isolated single-step execution for workflow engine.

Extracted from WorkflowEngine to reduce orchestrator.py's responsibilities.
Handles one workflow step: condition checking, template rendering, personality
wrapping, adapter delegation, observability recording, and DB persistence.

Usage (internal to WorkflowEngine):
    executor = StepExecutor(db, adapter, tracer=t, auditor=a, ...)
    executor.execute_with_retry(run_id, step, step_outputs, parent_span_id)
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Optional

from sccsos.core.database import Database
from sccsos.core.hermes_adapter import HermesAdapter
from sccsos.core.templates import _render_template
from sccsos.core.personality import PersonalityRegistry
from sccsos.observability.tracer import Tracer
from sccsos.observability.auditor import Auditor
from sccsos.observability.pricing import PricingTable
from sccsos.memory.memory_store import MemoryStore


# ── Exceptions ─────────────────────────────────────────────────────


class WorkflowError(Exception):
    """Base exception for workflow errors."""
    pass


class WorkflowExecutionError(WorkflowError):
    """A workflow step failed."""
    pass


class StepExecutor:
    """Executes a single workflow step with observability and retry.

    Thread-safe: all DB writes are serialized under ``_db_lock``.
    """

    def __init__(self, db: Database, adapter: HermesAdapter,
                 tracer: Optional[Tracer] = None,
                 auditor: Optional[Auditor] = None,
                 config=None,
                 registry=None,
                 knowledge_base=None,
                 memory_store: Optional[MemoryStore] = None,
                 personality_registry: Optional[PersonalityRegistry] = None,
                 policy_engine=None,
                 db_lock: Optional[threading.Lock] = None,
                 cancel_event: Optional[threading.Event] = None,
                 template_engine=None):
        self._db = db
        self._adapter = adapter
        self._tracer = tracer or Tracer(db)
        self._auditor = auditor or Auditor(db, PricingTable())
        self._config = config
        self._registry = registry
        self._kb = knowledge_base
        self._personality_registry = personality_registry
        self._policy_engine = policy_engine
        self._db_lock = db_lock or threading.Lock()
        self._memory_store = memory_store
        self._template_engine = template_engine

    # ── Public API ───────────────────────────────────────────────

    def execute_with_retry(self, run_id: str, step,
                           step_outputs: dict[str, dict],
                           parent_span_id: str = "",
                           cancel_event: Optional[threading.Event] = None,
                           trace_span_id: str = "") -> None:
        """Execute step with exponential-backoff retry.

        Args:
            run_id: Workflow run ID.
            step: WorkflowStepDef to execute.
            step_outputs: Shared dict of step results (populated on success).
            parent_span_id: Parent span ID for tracing.
            cancel_event: Optional cancellation signal.
            trace_span_id: Workflow-level span ID (used only for error path).
        """
        max_attempts = 1 + step.retry  # 1 initial + N retries
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            # Check cancellation before each attempt
            if cancel_event and cancel_event.is_set():
                raise WorkflowExecutionError(
                    f"Step '{step.id}' cancelled after {attempt} attempt(s)"
                )

            try:
                self._execute_step(
                    run_id, step, step_outputs, parent_span_id,
                    cancel_event=cancel_event,
                )
                return  # Success -- exit retry loop

            except WorkflowExecutionError as e:
                # Check if this is a policy rejection or cancellation (not retryable)
                if "Policy rejected" in str(e) or "cancelled" in str(e).lower():
                    raise

                last_error = e
                if attempt < max_attempts - 1:
                    # Exponential backoff: 2^attempt seconds, capped at 30s
                    delay = min(2 ** attempt, 30)
                    # Log retry via DB event
                    with self._db_lock:
                        self._db.execute(
                            """INSERT INTO agent_events (agent_id, event, detail)
                               VALUES (?, 'retry', ?)""",
                            (step.agent,
                             f"Step '{step.id}' attempt {attempt + 1}/{max_attempts} "
                             f"failed, retrying in {delay}s: {str(e)[:200]}"),
                        )
                        self._db.get_conn().commit()
                    time.sleep(delay)

        # All attempts exhausted
        raise WorkflowExecutionError(
            f"Step '{step.id}' failed after {max_attempts} attempts: {last_error}"
        ) from last_error

    # ── Internal ─────────────────────────────────────────────────

    def _build_context(self, run_id: str, step,
                       step_outputs: dict[str, dict]) -> tuple[dict, callable]:
        """Build template rendering context for a workflow step.

        Constructs the Jinja2 template context with:
        - steps: All previous step outputs (for ``{{ steps.xxx.response }}``)
        - run_id: The current workflow run ID
        - knowledge: Optional KB context from wiki (if configured)
        - memory: Optional persistent memory for this agent (if configured)

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

    def _execute_step(self, run_id: str, step,
                      step_outputs: dict[str, dict],
                      parent_span_id: str = "",
                      cancel_event: Optional[threading.Event] = None) -> None:
        """Execute a single workflow step (no retry)."""
        start_ts = datetime.now(timezone.utc)

        # Start step span (in-memory, no DB write yet)
        step_span = self._tracer.start_span(
            name=f"step:{step.id}",
            agent=step.agent,
            parent_span_id=parent_span_id,
            trace_id=run_id,
        )

        # Build template context and get render function
        template_context, render_fn = self._build_context(
            run_id, step, step_outputs,
        )

        # ── Condition check: if falsy → skip step ──────────────
        if step.condition:
            condition_result = render_fn(step.condition, template_context)
            if not condition_result or condition_result.strip().lower() in (
                "", "false", "0", "no", "none", "skip",
            ):
                # Record as skipped
                self._tracer.end_span(step_span.span_id, status="skipped")
                with self._db_lock:
                    self._db.execute(
                        """INSERT INTO workflow_steps (run_id, step_id, agent_name, status, started_at, finished_at)
                           VALUES (?, ?, ?, 'skipped', ?, ?)""",
                        (run_id, step.id, step.agent, start_ts.isoformat(),
                         datetime.now(timezone.utc).isoformat()),
                    )
                    self._db.get_conn().commit()
                    # Inject empty output (thread-safe: under lock)
                    step_outputs[step.id] = {"response": "", "stdout": "", "skipped": True}
                return

        # Render prompt with template
        prompt = render_fn(step.prompt, template_context)

        # Wrap prompt with personality system prompt (if personality_registry configured)
        if self._personality_registry is not None and step.agent:
            spec = (self._registry.find(step.agent)
                    if self._registry is not None else None)
            personality_name = getattr(spec, 'personality', None) if spec else None
            if personality_name:
                wrapped = self._personality_registry.wrap_prompt(
                    personality_name, prompt,
                )
                prompt = wrapped.prompt

        # Record step start (DB write)
        with self._db_lock:
            self._db.execute(
                """INSERT INTO workflow_steps (run_id, step_id, agent_name, status, started_at)
                   VALUES (?, ?, ?, 'running', ?)""",
                (run_id, step.id, step.agent, start_ts.isoformat()),
            )
            self._db.get_conn().commit()

        try:
            # Resolve agent model from registry (if available)
            agent_model = None
            if self._registry is not None:
                spec = self._registry.find(step.agent)
                if spec is not None and spec.model:
                    agent_model = spec.model

            # Delegate to agent -- this is the expensive operation (parallel-safe)
            result = self._adapter.delegate_task(
                agent_name=step.agent,
                prompt=prompt,
                model=agent_model,
                timeout=step.timeout,
                policy_engine=self._policy_engine,
                cancel_event=cancel_event,
            )

            end_ts = datetime.now(timezone.utc)

            # -- DB writes serialized under lock --
            with self._db_lock:
                # Record audit trail
                tenant_id = "default"
                if self._registry is not None:
                    spec = self._registry.find(step.agent)
                    if spec is not None:
                        tenant_id = getattr(spec, 'tenant_id', 'default')
                self._auditor.record_llm_call(
                    agent_id=step.agent,
                    model=result.model,
                    tokens_input=result.tokens_input,
                    tokens_output=result.tokens_output,
                    duration_ms=result.duration_ms,
                    success=result.success,
                    tenant_id=tenant_id,
                )

                # -- Failure path --
                if not result.success:
                    self._tracer.end_span(step_span.span_id, status="error")
                    self._db.execute(
                        """UPDATE workflow_steps SET status = 'failed',
                           finished_at = ?, duration_ms = ?, error = ? WHERE run_id = ? AND step_id = ?""",
                        (end_ts.isoformat(), result.duration_ms, result.error[:500], run_id, step.id),
                    )
                    self._db.get_conn().commit()
                    raise WorkflowExecutionError(
                        f"Step '{step.id}' failed: {result.error}"
                    )

                # -- Success path --
                # Cache output
                output_data = {
                    "response": result.response,
                    "stdout": result.response,
                }
                step_outputs[step.id] = output_data

                # End step span (persists to DB inside end_span)
                self._tracer.end_span(step_span.span_id, status="ok")

                # Record step completion
                self._db.execute(
                    """UPDATE workflow_steps SET status = 'completed',
                       finished_at = ?, duration_ms = ?, output = ?
                       WHERE run_id = ? AND step_id = ?""",
                    (end_ts.isoformat(), result.duration_ms, result.response[:1000],
                     run_id, step.id),
                )
                self._db.get_conn().commit()

        except WorkflowExecutionError:
            raise

        except Exception as e:
            # Unexpected error -- span is still active
            error_msg = str(e)
            with self._db_lock:
                self._tracer.end_span(step_span.span_id, status="error")
                now = datetime.now(timezone.utc)
                self._db.execute(
                    """UPDATE workflow_steps SET status = 'failed',
                       finished_at = ?, duration_ms = ?, error = ? WHERE run_id = ? AND step_id = ?""",
                    (now.isoformat(), int((now - start_ts).total_seconds() * 1000),
                     error_msg[:500], run_id, step.id),
                )
                self._db.get_conn().commit()

                if step.retry > 0:
                    # Retry is handled by execute_with_retry
                    raise WorkflowExecutionError(
                        f"Step '{step.id}' failed: {error_msg}"
                    )

                # No retry configured -- propagate to caller
                raise WorkflowExecutionError(
                    f"Step '{step.id}' failed (no retry): {error_msg}"
                )
