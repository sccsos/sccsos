"""WorkflowRuntime — workflow engine, policy, personality, events.

Initialises WorkflowEngine, PolicyEngine, PersonalityRegistry, EventBus
observers, and model router wiring.  Depends on RuntimeCore for DB/adapter
and ObservabilityRuntime for tracer/auditor.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from sccsos.core.event_bus import get_bus
from sccsos.core.events import (
    WORKFLOW_STARTED, WORKFLOW_COMPLETED, WORKFLOW_FAILED,
)
from sccsos.core.config import AgentOSConfig
from sccsos.core.personality import PersonalityRegistry
from sccsos.core.workflow import WorkflowEngine
from sccsos.core.db import crud


class WorkflowRuntime:
    """Workflow services: engine, personality registry, EventBus wiring."""

    def __init__(self, core, observability, config: AgentOSConfig):
        self._core = core
        self._obs = observability
        self._cfg = config
        self._engine: Optional[WorkflowEngine] = None
        self._personality_registry: Optional[PersonalityRegistry] = None
        # Shared thread pool for fire-and-forget background tasks
        # (alert evaluation, webhook dispatch — already best-effort)
        self._bg_executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="wf_bg",
        )

    @property
    def engine(self) -> WorkflowEngine:
        return self._engine

    @property
    def personality_registry(self) -> PersonalityRegistry:
        return self._personality_registry

    def initialize(self) -> None:
        cfg = self._cfg
        core = self._core

        # Personality registry
        from pathlib import Path
        self._personality_registry = PersonalityRegistry()
        personalities_dir = Path(cfg.agents.personalities_path)
        if personalities_dir.exists():
            self._personality_registry.load_from_dir(personalities_dir)

        # Workflow engine (via builder)
        from sccsos.core.workflow.builder import WorkflowEngineBuilder
        self._engine = (
            WorkflowEngineBuilder(core.db, core.adapter)
            .with_tracer(self._obs.tracer)
            .with_auditor(self._obs.auditor)
            .with_config(cfg)
            .with_registry(core.registry)
            .with_knowledge_base(core.knowledge_base)
            .with_memory_store(core.memory_store)
            .with_personality_registry(self._personality_registry)
            .with_model_router(core.model_router)
            .build()
        )

        # EventBus wiring
        bus = get_bus()

        def _persist_event(event: str, data: dict) -> None:
            crud.insert_event_queue_item(
                core.db, event, json.dumps(data, ensure_ascii=False, default=str),
            )

        bus.set_persist(_persist_event)

        def _on_workflow_event(event_label: str, **kw: Any) -> None:
            self._obs.webhook.fire(
                event=event_label,
                run_id=kw.get("run_id", ""),
                workflow_name=kw.get("workflow_name", ""),
                status=kw.get("status", ""),
                error=kw.get("error"),
                steps=kw.get("steps"),
            )

        bus.on(WORKFLOW_STARTED,
               lambda **kw: _on_workflow_event("started", **kw))
        bus.on(WORKFLOW_COMPLETED,
               lambda **kw: self._obs.webhook.fire(
                   event="completed",
                   run_id=kw.get("run_id", ""),
                   workflow_name=kw.get("workflow_name", ""),
                   status="completed",
                   steps=kw.get("steps"),
               ))
        bus.on(WORKFLOW_COMPLETED,
               lambda **kw: self._bg_executor.submit(
                   self._obs.alert_manager.evaluate_after_run,
                   kw.get("run_id", ""),
               ))
        bus.on(WORKFLOW_FAILED,
               lambda **kw: self._obs.webhook.fire(
                   event="failed",
                   run_id=kw.get("run_id", ""),
                   workflow_name=kw.get("workflow_name", ""),
                   status="failed",
                   error=kw.get("error"),
               ))
        bus.on(WORKFLOW_FAILED,
               lambda **kw: self._bg_executor.submit(
                   self._obs.alert_manager.evaluate_after_run,
                   kw.get("run_id", ""),
               ))
