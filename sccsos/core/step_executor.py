"""Step Executor — isolated single-step execution for workflow engine.

Responsibility chain::

    StepExecutor.execute_with_retry()
      └─ RetryPolicy.execute()
           └─ _execute_step()
                ├─ ContextBuilder.build()      → template context
                ├─ _check_condition_and_skip() → condition guard
                ├─ _prepare_prompt()           → injection + personality
                ├─ HermesAdapter.delegate_task → the real work
                └─ _record_audit_and_result()  → observability + DB
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Optional

from sccsos.core.db import Database
from sccsos.core.db import crud
from sccsos.core.hermes_adapter import HermesAdapter
from sccsos.core.personality import PersonalityRegistry
from sccsos.core.retry_policy import RetryPolicy
from sccsos.core.context_builder import ContextBuilder
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
    """Executes a single workflow step with retry, context, and observability.

    Composes ``RetryPolicy`` and ``ContextBuilder`` for delegated
    responsibilities. Thread-safe: all DB writes are serialized under
    ``_db_lock``.

    Note:
        Prefer ``StepExecutorBuilder`` over direct construction when
        passing many optional dependencies.
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
                 template_engine=None,
                 model_router=None,
                 retry_policy: Optional[RetryPolicy] = None,
                 context_builder: Optional[ContextBuilder] = None):
        self._db = db
        self._adapter = adapter
        self._tracer = tracer or Tracer(db)
        self._auditor = auditor or Auditor(db, PricingTable())
        self._config = config
        self._registry = registry
        self._personality_registry = personality_registry
        self._policy_engine = policy_engine
        self._db_lock = db_lock or threading.Lock()
        self._model_router = model_router
        self._injection_guard = None  # Optional PromptInjectionGuard

        # Delegated components
        self._retry_policy = retry_policy or RetryPolicy(db, self._db_lock)
        self._context_builder = context_builder or ContextBuilder(
            knowledge_base=knowledge_base,
            memory_store=memory_store,
            template_engine=template_engine,
        )

    # ── Public API ───────────────────────────────────────────────

    def execute_with_retry(self, run_id: str, step,
                           step_outputs: dict[str, dict],
                           parent_span_id: str = "",
                           cancel_event: Optional[threading.Event] = None,
                           trace_span_id: str = "") -> None:
        """Execute step with exponential-backoff retry via RetryPolicy.

        Args:
            run_id: Workflow run ID.
            step: WorkflowStepDef to execute.
            step_outputs: Shared dict of step results (populated on success).
            parent_span_id: Parent span ID for tracing.
            cancel_event: Optional cancellation signal.
            trace_span_id: Workflow-level span ID (used only for error path).
        """
        max_attempts = 1 + step.retry  # 1 initial + N retries

        self._retry_policy.execute(
            fn=lambda: self._execute_step(
                run_id, step, step_outputs, parent_span_id,
                cancel_event=cancel_event,
            ),
            step_id=step.id,
            step_agent=step.agent,
            max_attempts=max_attempts,
            cancel_event=cancel_event,
        )

    # ── Internal ─────────────────────────────────────────────────

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
        template_context, render_fn = self._context_builder.build(
            step, step_outputs, run_id,
        )

        # ── Condition check: if falsy → skip step ──────────────
        if self._check_condition_and_skip(
            run_id, step, template_context, render_fn,
            step_span, start_ts, step_outputs,
        ):
            return

        # Render prompt with template
        prompt_text = render_fn(step.prompt, template_context)

        # ── Prepare prompt: injection check + personality wrap ──
        prompt = self._prepare_prompt(step, prompt_text)

        # Record step start (DB write)
        with self._db_lock:
            crud.insert_workflow_step(
                self._db, run_id, step.id, step.agent, "running", start_ts.isoformat(),
            )

        try:
            # Resolve agent model from registry (if available)
            agent_model = None
            if self._registry is not None:
                spec = self._registry.find(step.agent)
                if spec is not None and spec.model:
                    agent_model = spec.model
            # Fall back to ModelRouter if no explicit model
            if agent_model is None and self._model_router is not None:
                agent_model = self._model_router.resolve_for_agent(step.agent)

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

            # Record audit trail + step result (DB writes serialized under lock)
            self._record_audit_and_result(
                run_id, step, result, step_span,
                step_outputs, start_ts, end_ts,
            )

        except WorkflowExecutionError:
            raise

        except Exception as e:
            self._handle_execution_error(
                run_id, step, e, step_span, start_ts,
            )

    def _check_condition_and_skip(
        self, run_id: str, step,
        template_context: dict, render_fn,
        step_span, start_ts, step_outputs: dict[str, dict],
    ) -> bool:
        """Check step condition; if falsy, record as skipped and return True."""
        if not step.condition:
            return False
        condition_result = render_fn(step.condition, template_context)
        if not condition_result or condition_result.strip().lower() in (
            "", "false", "0", "no", "none", "skip",
        ):
            self._tracer.end_span(step_span.span_id, status="skipped")
            with self._db_lock:
                crud.insert_workflow_step(
                    self._db, run_id, step.id, step.agent, "skipped",
                    start_ts.isoformat(),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                # Inject empty output (thread-safe: under lock)
                step_outputs[step.id] = {"response": "", "stdout": "", "skipped": True}
            return True
        return False

    def _prepare_prompt(self, step, prompt_text: str) -> str:
        """Render prompt, run injection guard, and wrap with personality."""
        # ── Prompt injection check ──────────────────────────────
        if self._injection_guard is not None:
            sec_result = self._injection_guard.check(prompt_text)
            if not sec_result.allowed:
                raise WorkflowExecutionError(
                    f"Step '{step.id}' blocked by PromptInjectionGuard: "
                    f"{sec_result.reason}"
                )

        # Wrap prompt with personality system prompt (if configured)
        prompt = prompt_text
        if self._personality_registry is not None and step.agent:
            spec = (self._registry.find(step.agent)
                    if self._registry is not None else None)
            personality_name = getattr(spec, 'personality', None) if spec else None
            if personality_name:
                wrapped = self._personality_registry.wrap_prompt(
                    personality_name, prompt,
                )
                prompt = wrapped.prompt
        return prompt

    def _record_audit_and_result(
        self, run_id: str, step, result,
        step_span, step_outputs: dict[str, dict],
        start_ts, end_ts,
    ) -> None:
        """Record audit trail and step result; raise on failure."""
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
                crud.update_workflow_step(
                    self._db, run_id, step.id,
                    status="failed",
                    finished_at=end_ts.isoformat(),
                    duration_ms=result.duration_ms,
                    error=result.error[:500],
                )
                raise WorkflowExecutionError(
                    f"Step '{step.id}' failed: {result.error}"
                )

            # -- Success path --
            output_data = {
                "response": result.response,
                "stdout": result.response,
            }
            step_outputs[step.id] = output_data

            # End step span (persists to DB inside end_span)
            self._tracer.end_span(step_span.span_id, status="ok")

            # Record step completion
            crud.update_workflow_step(
                self._db, run_id, step.id,
                status="completed",
                finished_at=end_ts.isoformat(),
                duration_ms=result.duration_ms,
                output=result.response[:1000],
            )

    def _handle_execution_error(
        self, run_id: str, step, error: Exception,
        step_span, start_ts,
    ) -> None:
        """Handle unexpected exception during step execution."""
        error_msg = str(error)
        with self._db_lock:
            self._tracer.end_span(step_span.span_id, status="error")
            now = datetime.now(timezone.utc)
            crud.update_workflow_step(
                self._db, run_id, step.id,
                status="failed",
                finished_at=now.isoformat(),
                duration_ms=int((now - start_ts).total_seconds() * 1000),
                error=error_msg[:500],
            )

            if step.retry > 0:
                raise WorkflowExecutionError(
                    f"Step '{step.id}' failed: {error_msg}"
                )

            raise WorkflowExecutionError(
                f"Step '{step.id}' failed (no retry): {error_msg}"
            )


# ── Builder ────────────────────────────────────────────────────────


class StepExecutorBuilder:
    """Fluent builder for ``StepExecutor`` with many optional deps.

    Usage::

        executor = (StepExecutorBuilder(db, adapter)
                    .with_tracer(tracer)
                    .with_auditor(auditor)
                    .with_config(config)
                    .with_registry(registry)
                    .with_memory_store(memory_store)
                    .build())

    Also accepts pre-built ``RetryPolicy`` and ``ContextBuilder`` for
    test injection and alternate configurations.
    """

    def __init__(self, db: Database, adapter: HermesAdapter):
        self._db = db
        self._adapter = adapter
        # Optional fields (all None by default)
        self._tracer: Optional[Tracer] = None
        self._auditor: Optional[Auditor] = None
        self._config = None
        self._registry = None
        self._knowledge_base = None
        self._memory_store: Optional[MemoryStore] = None
        self._personality_registry: Optional[PersonalityRegistry] = None
        self._policy_engine = None
        self._db_lock: Optional[threading.Lock] = None
        self._cancel_event: Optional[threading.Event] = None
        self._template_engine = None
        self._model_router = None
        self._injection_guard = None
        self._retry_policy: Optional[RetryPolicy] = None
        self._context_builder: Optional[ContextBuilder] = None

    def with_tracer(self, tracer: Tracer) -> StepExecutorBuilder:
        self._tracer = tracer; return self

    def with_auditor(self, auditor: Auditor) -> StepExecutorBuilder:
        self._auditor = auditor; return self

    def with_config(self, config) -> StepExecutorBuilder:
        self._config = config; return self

    def with_registry(self, registry) -> StepExecutorBuilder:
        self._registry = registry; return self

    def with_knowledge_base(self, kb) -> StepExecutorBuilder:
        self._knowledge_base = kb; return self

    def with_memory_store(self, ms: Optional[MemoryStore]) -> StepExecutorBuilder:
        self._memory_store = ms; return self

    def with_personality_registry(self, pr: Optional[PersonalityRegistry]) -> StepExecutorBuilder:
        self._personality_registry = pr; return self

    def with_policy_engine(self, pe) -> StepExecutorBuilder:
        self._policy_engine = pe; return self

    def with_db_lock(self, lock: threading.Lock) -> StepExecutorBuilder:
        self._db_lock = lock; return self

    def with_template_engine(self, engine) -> StepExecutorBuilder:
        self._template_engine = engine; return self

    def with_model_router(self, router) -> StepExecutorBuilder:
        self._model_router = router; return self

    def with_injection_guard(self, guard) -> StepExecutorBuilder:
        self._injection_guard = guard; return self

    def with_retry_policy(self, rp: RetryPolicy) -> StepExecutorBuilder:
        self._retry_policy = rp; return self

    def with_context_builder(self, cb: ContextBuilder) -> StepExecutorBuilder:
        self._context_builder = cb; return self

    def build(self) -> StepExecutor:
        """Construct the ``StepExecutor`` with configured dependencies."""
        executor = StepExecutor(
            db=self._db,
            adapter=self._adapter,
            tracer=self._tracer,
            auditor=self._auditor,
            config=self._config,
            registry=self._registry,
            knowledge_base=self._knowledge_base,
            memory_store=self._memory_store,
            personality_registry=self._personality_registry,
            policy_engine=self._policy_engine,
            db_lock=self._db_lock,
            cancel_event=self._cancel_event,
            template_engine=self._template_engine,
            model_router=self._model_router,
            retry_policy=self._retry_policy,
            context_builder=self._context_builder,
        )
        if self._injection_guard is not None:
            executor._injection_guard = self._injection_guard
        return executor
