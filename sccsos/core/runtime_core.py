"""RuntimeCore — lifecycle-essential services.

Initialises Database, Registry, HermesAdapter, and AgentRunner.
Part of the AgentRuntime decomposition — this is the "must have"
subset that the system cannot function without.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from sccsos.core.config import AgentOSConfig, get_config
from sccsos.core.db import AbstractDatabase, Database, create_database
from sccsos.core.registry import AgentRegistry, AgentSpec
from sccsos.core.lifecycle import LifecycleManager
from sccsos.core.hermes_adapter import HermesAdapter, create_adapter
from sccsos.core.agent_runner import AgentRunner
from sccsos.core.session import AgentSessionManager
from sccsos.core.supervisor import Supervisor
from sccsos.core.supervisor_base import SupervisorABC
from sccsos.memory.memory_store import MemoryStore
from sccsos.memory.knowledge_base import KnowledgeBase
from sccsos.core.model_router import ModelRouter


class RuntimeCore:
    """Core services: config, database, registry, adapter, runner, sessions.

    Usage:
        core = RuntimeCore()
        core.initialize()
        core.registry.list()
    """

    def __init__(self, config: Optional[AgentOSConfig] = None):
        self._config = config
        self._db: AbstractDatabase | None = None
        self._initialized = False
        self._registry: Optional[AgentRegistry] = None
        self._lifecycle: Optional[LifecycleManager] = None
        self._adapter: Optional[HermesAdapter] = None
        self._runner: Optional[AgentRunner] = None
        self._session_manager: Optional[AgentSessionManager] = None
        self._supervisor: Optional[Supervisor] = None
        self._memory_store: Optional[MemoryStore] = None
        self._knowledge_base: Optional[KnowledgeBase] = None
        self._model_router: Optional[ModelRouter] = None

    @property
    def config(self) -> AgentOSConfig:
        if self._config is None:
            self._config = get_config()
        return self._config

    @property
    def db(self) -> Database:
        return self._db

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    @property
    def lifecycle(self) -> LifecycleManager:
        return self._lifecycle

    @property
    def adapter(self) -> HermesAdapter:
        return self._adapter

    @property
    def runner(self) -> AgentRunner:
        return self._runner

    @property
    def session_manager(self) -> AgentSessionManager:
        return self._session_manager

    @property
    def supervisor(self) -> Supervisor:
        return self._supervisor

    @property
    def memory_store(self) -> MemoryStore:
        return self._memory_store

    @property
    def knowledge_base(self):
        return self._knowledge_base

    @property
    def model_router(self):
        return self._model_router

    def initialize(self) -> bool:
        cfg = self.config

        self._db = create_database(cfg.database)
        self._db.initialize()

        # Registry
        agents_dir = Path(cfg.agents.path)
        agents_dir = agents_dir if agents_dir.is_absolute() else Path.cwd() / agents_dir
        self._registry = AgentRegistry()
        if agents_dir.exists():
            self._registry.load_from_dir(agents_dir)

        # Adapter with sandbox
        from sccsos.security.sandbox import CommandWhitelist
        from sccsos.core.hermes_adapter import create_adapter
        wl_allowed = cfg.policies.default.allowed_commands
        wl_dangerous = cfg.policies.default.dangerous_patterns
        sandbox = CommandWhitelist(
            allowed_commands=list(wl_allowed),
            dangerous_patterns=list(wl_dangerous) if wl_dangerous else None,
        )
        hermes_cfg = cfg.hermes
        self._adapter = create_adapter(
            mode=hermes_cfg.adapter,
            whitelist=sandbox,
            hermes_bin=hermes_cfg.binary,
        )

        # Memory, session, model router, KB
        self._memory_store = MemoryStore(self._db)
        self._session_manager = AgentSessionManager(self._db)

        model_pool_cfg = getattr(cfg, 'model_pool', None)
        self._model_router = ModelRouter.from_config(model_pool_cfg)

        self._knowledge_base = None
        wiki_path = cfg.agents.wiki_path
        if wiki_path:
            kb_path = Path(wiki_path)
            if kb_path.exists():
                self._knowledge_base = KnowledgeBase(wiki_path=kb_path, use_vector=True)
            else:
                from sccsos.observability.logger import get_logger
                get_logger().warning(
                    "KnowledgeBase wiki_path '%s' does not exist.",
                    wiki_path,
                )

        # Supervisor + Runner
        self._supervisor = Supervisor(max_restarts=3, heartbeat_timeout=30.0)
        self._runner = AgentRunner(
            self._adapter, memory_store=self._memory_store,
            session_manager=self._session_manager,
            supervisor=self._supervisor,
            model_router=self._model_router,
            knowledge_base=self._knowledge_base,
        )
        self._supervisor.start()

        # Lifecycle
        self._lifecycle = LifecycleManager(self._db, self._registry)
        self._restore_instances()

        return True

    def _restore_instances(self) -> None:
        if self._db is None or self._lifecycle is None:
            return
        import json
        records = self._db.list_agents()
        skipped = 0
        for rec in records:
            status = rec["status"]
            if status in ("terminated",):
                continue
            try:
                spec_dict = json.loads(rec["spec"])
                spec = AgentSpec.from_dict(spec_dict)
                self._lifecycle._restore_instance(rec["id"], spec, rec["status"])
            except Exception as e:
                skipped += 1
        if skipped > 0:
            from sccsos.observability.logger import get_logger
            get_logger().info("Restored agents, skipped %d unreadable records", skipped)
