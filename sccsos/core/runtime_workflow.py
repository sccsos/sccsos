"""WorkflowRuntime — workflow engine, policy, personality, events.

Initialises WorkflowEngine, PolicyEngine, PersonalityRegistry, EventBus
observers, and model router wiring.  Depends on RuntimeCore for DB/adapter
and ObservabilityRuntime for tracer/auditor.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Optional

from sccsos.core.event_bus import EventBus
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

        # Workflow engine
        self._engine = WorkflowEngine(
            core.db, core.adapter,
            tracer=self._obs.tracer,
            auditor=self._obs.auditor,
            config=cfg,
            registry=core.registry,
            knowledge_base=core.knowledge_base,
            memory_store=core.memory_store,
            personality_registry=self._personality_registry,
            model_router=core.model_router,
        )

        # EventBus wiring
        bus = EventBus.get_instance()

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
               lambda **kw: threading.Thread(
                   target=self._obs.alert_manager.evaluate_after_run,
                   args=(kw.get("run_id", ""),),
                   daemon=True,
               ).start())
        bus.on(WORKFLOW_FAILED,
               lambda **kw: self._obs.webhook.fire(
                   event="failed",
                   run_id=kw.get("run_id", ""),
                   workflow_name=kw.get("workflow_name", ""),
                   status="failed",
                   error=kw.get("error"),
               ))
        bus.on(WORKFLOW_FAILED,
               lambda **kw: threading.Thread(
                   target=self._obs.alert_manager.evaluate_after_run,
                   args=(kw.get("run_id", ""),),
                   daemon=True,
               ).start())
