"""WorkflowEngineBuilder — fluent builder for WorkflowEngine construction.

Eliminates the 12+ parameter constructor by providing a chainable builder
pattern.  Test code that only needs a basic engine can keep using the
``WorkflowEngine(db, adapter)`` constructor — it delegates to the builder
internally.
"""
from __future__ import annotations

from typing import Optional

from sccsos.core.db import Database
from sccsos.core.hermes_adapter import HermesAdapter
from sccsos.core.config import AgentOSConfig
from sccsos.core.personality import PersonalityRegistry
from sccsos.core.step_executor import StepExecutorBuilder
from sccsos.core.workflow.engine import WorkflowEngine
from sccsos.observability.tracer import Tracer
from sccsos.observability.auditor import Auditor
from sccsos.memory.memory_store import MemoryStore


class WorkflowEngineBuilder:
    """Fluent builder for WorkflowEngine.

    Usage::

        engine = (WorkflowEngineBuilder(db, adapter)
            .with_tracer(tracer)
            .with_auditor(auditor)
            .with_config(cfg)
            .with_registry(registry)
            .with_knowledge_base(kb)
            .with_memory_store(ms)
            .with_personality_registry(pr)
            .with_model_router(mr)
            .build())
    """

    def __init__(self, db: Database, adapter: HermesAdapter) -> None:
        self._db = db
        self._adapter = adapter
        self._tracer: Optional[Tracer] = None
        self._auditor: Optional[Auditor] = None
        self._config: Optional[AgentOSConfig] = None
        self._registry = None
        self._knowledge_base = None
        self._memory_store: Optional[MemoryStore] = None
        self._personality_registry: Optional[PersonalityRegistry] = None
        self._model_router = None
        self._policy_engine = None
        self._injection_guard = None

    def with_tracer(self, tracer: Optional[Tracer]) -> WorkflowEngineBuilder:
        self._tracer = tracer
        return self

    def with_auditor(self, auditor: Optional[Auditor]) -> WorkflowEngineBuilder:
        self._auditor = auditor
        return self

    def with_config(self, config: Optional[AgentOSConfig]) -> WorkflowEngineBuilder:
        self._config = config
        return self

    def with_registry(self, registry) -> WorkflowEngineBuilder:
        self._registry = registry
        return self

    def with_knowledge_base(self, kb) -> WorkflowEngineBuilder:
        self._knowledge_base = kb
        return self

    def with_memory_store(self, ms: Optional[MemoryStore]) -> WorkflowEngineBuilder:
        self._memory_store = ms
        return self

    def with_personality_registry(self, pr: Optional[PersonalityRegistry]) -> WorkflowEngineBuilder:
        self._personality_registry = pr
        return self

    def with_model_router(self, mr) -> WorkflowEngineBuilder:
        self._model_router = mr
        return self

    def with_policy_engine(self, pe) -> WorkflowEngineBuilder:
        self._policy_engine = pe
        return self

    def with_injection_guard(self, guard) -> WorkflowEngineBuilder:
        self._injection_guard = guard
        return self

    def build(self) -> WorkflowEngine:
        """Construct and return a WorkflowEngine instance."""
        return WorkflowEngine(
            self._db,
            self._adapter,
            tracer=self._tracer,
            auditor=self._auditor,
            config=self._config,
            registry=self._registry,
            knowledge_base=self._knowledge_base,
            memory_store=self._memory_store,
            personality_registry=self._personality_registry,
            model_router=self._model_router,
            policy_engine=self._policy_engine,
            injection_guard=self._injection_guard,
        )
