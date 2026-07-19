"""AgentRuntime — unified entry point for all sccsos core services.

Replaces the previous pattern of 5 global variables in CLI.py with
a single Runtime object that manages lazy initialization, dependency
injection, and graceful shutdown.

Usage:
    runtime = AgentRuntime()
    runtime.initialize()
    runtime.registry.list()
    runtime.lifecycle.start("agent-1")
    runtime.close()
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from sccsos.core.config import AgentOSConfig, get_config
from sccsos.core.database import Database
from sccsos.core.registry import AgentRegistry, AgentSpec
from sccsos.core.lifecycle import LifecycleManager
from sccsos.core.hermes_adapter import HermesAdapter, create_adapter
from sccsos.core.agent_runner import AgentRunner
from sccsos.core.orchestrator import WorkflowEngine
from sccsos.observability.tracer import Tracer
from sccsos.observability.auditor import Auditor
from sccsos.observability.pricing import PricingTable


class AgentRuntime:
    """Central runtime that owns all core services.

    Initialization is deferred until first access or explicit
    initialize() call, so the Runtime object can be created early
    without side effects.
    """

    def __init__(self, config: Optional[AgentOSConfig] = None):
        self._config = config
        self._db: Optional[Database] = None
        self._registry: Optional[AgentRegistry] = None
        self._lifecycle: Optional[LifecycleManager] = None
        self._adapter: Optional[HermesAdapter] = None
        self._engine: Optional[WorkflowEngine] = None
        self._tracer: Optional[Tracer] = None
        self._auditor: Optional[Auditor] = None
        self._runner: Optional[AgentRunner] = None
        self._initialized: bool = False

    # ── Properties (lazy accessors) ───────────────────────────────

    @property
    def config(self) -> AgentOSConfig:
        if self._config is None:
            self._config = get_config()
        return self._config

    @property
    def db(self) -> Database:
        self._ensure_initialized()
        return self._db

    @property
    def registry(self) -> AgentRegistry:
        self._ensure_initialized()
        return self._registry

    @property
    def lifecycle(self) -> LifecycleManager:
        self._ensure_initialized()
        return self._lifecycle

    @property
    def adapter(self) -> HermesAdapter:
        self._ensure_initialized()
        return self._adapter

    @property
    def engine(self) -> WorkflowEngine:
        self._ensure_initialized()
        return self._engine

    @property
    def tracer(self) -> Tracer:
        self._ensure_initialized()
        return self._tracer

    @property
    def auditor(self) -> Auditor:
        self._ensure_initialized()
        return self._auditor

    @property
    def runner(self) -> AgentRunner:
        self._ensure_initialized()
        return self._runner

    @property
    def policy_engine(self):
        self._ensure_initialized()
        if self._engine and hasattr(self._engine, '_policy_engine'):
            return self._engine._policy_engine
        return None

    @property
    def memory(self):
        """Access the MemoryStore (persistent cross-session KV store)."""
        self._ensure_initialized()
        return self._memory_store

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    # ── Initialisation ───────────────────────────────────────────

    def initialize(self) -> bool:
        """Explicitly initialise all core services.

        Returns True if initialisation succeeded, False on failure.
        Safe to call multiple times — subsequent calls are no-ops.
        """
        if self._initialized:
            return True

        cfg = self.config

        # Resolve agents directory
        agents_dir = Path(cfg.agents.path)
        agents_dir = agents_dir if agents_dir.is_absolute() else Path.cwd() / agents_dir

        # ── Database ──────────────────────────────────────────────
        try:
            self._db = Database(cfg.database.path)
            self._db.initialize()
        except Exception:
            return False

        # ── Registry ──────────────────────────────────────────────
        self._registry = AgentRegistry()
        if agents_dir.exists():
            self._registry.load_from_dir(agents_dir)

        # ── Hermes adapter with sandbox ──────────────────────────────
        from sccsos.security.sandbox import CommandWhitelist
        wl_allowed = cfg.policies.default.allowed_commands
        wl_dangerous = cfg.policies.default.dangerous_patterns
        self._sandbox = CommandWhitelist(
            allowed_commands=list(wl_allowed),
            dangerous_patterns=list(wl_dangerous) if wl_dangerous else None,
        )
        self._adapter = create_adapter("subprocess", whitelist=self._sandbox)

        # ── Memory store (created early so runner can use it) ──────
        from sccsos.memory.memory_store import MemoryStore
        self._memory_store = MemoryStore(self._db)

        # ── Agent Runner (manages running agent processes) ─────────
        self._runner = AgentRunner(self._adapter, memory_store=self._memory_store)

        # ── Tracer & Auditor ──────────────────────────────────────
        self._tracer = Tracer(
            self._db,
            export_path=cfg.tracing.export_path if cfg.tracing.enabled else None,
        )
        # Create PricingTable from config if pricing_path is set
        pricing_path = cfg.tracing.pricing_path
        if pricing_path:
            pricing = PricingTable(Path(pricing_path))
        else:
            pricing = PricingTable()
        self._auditor = Auditor(self._db, pricing=pricing)

        # ── Lifecycle (restore running instances from DB) ─────────
        self._lifecycle = LifecycleManager(self._db, self._registry)
        self._restore_instances()

        # ── Knowledge base (optional, for context injection) ───────
        from sccsos.memory.knowledge_base import KnowledgeBase
        self._knowledge_base = None
        wiki_path = cfg.agents.wiki_path
        if wiki_path:
            kb_path = Path(wiki_path)
            if kb_path.exists():
                self._knowledge_base = KnowledgeBase(
                    wiki_path=kb_path, use_vector=True,
                )
            else:
                from sccsos.observability.logger import get_logger
                get_logger().warning(
                    "KnowledgeBase wiki_path '%s' does not exist. "
                    "Set 'agents.wiki_path' in sccsos.yaml or create the directory.",
                    wiki_path,
                )

        # ── Personality registry ────────────────────────────────────
        from sccsos.core.personality import PersonalityRegistry
        self._personality_registry = PersonalityRegistry()
        personalities_dir = Path(cfg.agents.personalities_path)
        if personalities_dir.exists():
            count = self._personality_registry.load_from_dir(personalities_dir)
        else:
            count = 0

        # ── Workflow engine ───────────────────────────────────────
        self._engine = WorkflowEngine(
            self._db, self._adapter,
            tracer=self._tracer,
            auditor=self._auditor,
            config=cfg,
            registry=self._registry,
            knowledge_base=self._knowledge_base,
            memory_store=self._memory_store,
            personality_registry=self._personality_registry,
        )

        self._initialized = True
        # Optional: config consistency checks
        self._check_config(cfg)
        return True

    def _check_config(self, cfg) -> None:
        """Run optional config consistency checks (best-effort, no failure)."""
        # Check pricing file existence
        pricing_path = cfg.tracing.pricing_path
        if pricing_path:
            pp = Path(pricing_path)
            if not pp.exists():
                from sccsos.observability.logger import get_logger
                get_logger().warning(
                    "Pricing file '%s' not found. Using default pricing.",
                    pricing_path,
                )

    def _ensure_initialized(self) -> None:
        """Auto-initialise on first property access."""
        if not self._initialized:
            ok = self.initialize()
            if not ok:
                raise RuntimeError(
                    "AgentRuntime initialisation failed. "
                    "Run 'sccsos init' first or check config."
                )

    def _restore_instances(self) -> None:
        """Load existing agent records from DB into lifecycle manager."""
        if self._db is None or self._lifecycle is None:
            return
        records = self._db.list_agents()
        skipped = 0
        for rec in records:
            status = rec["status"]
            if status in ("terminated",):
                continue
            try:
                spec_dict = json.loads(rec["spec"])
                spec = AgentSpec.from_dict(spec_dict)
                self._lifecycle._restore_instance(
                    rec["id"], spec, rec["status"]
                )
            except Exception as e:
                skipped += 1
                from sccsos.observability.logger import get_logger
                get_logger().warning(
                    "Skipped unreadable agent record '%s': %s",
                    rec.get("id", "?"), e,
                )
        if skipped > 0:
            from sccsos.observability.logger import get_logger
            get_logger().info(
                "Restored %d agents, skipped %d unreadable records",
                len(records) - skipped - sum(1 for r in records if r["status"] in ("terminated",)),
                skipped,
            )

    # ── Health ───────────────────────────────────────────────────

    def health(self) -> dict:
        """Return system health information."""
        if not self._initialized:
            return {
                "status": "not_initialized",
                "version": self.config.project.version,
            }

        result = {
            "version": self.config.project.version,
            "initialized": True,
            "database": self._db.check_health(),
            "hermes": self._adapter.check_connectivity() if self._adapter else False,
            "agents": self._registry.count() if self._registry else 0,
        }

        if self._engine:
            try:
                traces = self._tracer.list_traces(limit=1)
                result["traces_available"] = len(traces) > 0
            except Exception:
                result["traces_available"] = False

        return result

    # ── Lifecycle ─────────────────────────────────────────────────

    def register_agent(self, spec: AgentSpec) -> str:
        """Register an agent with policy validation.

        Validates the agent's toolsets against the policy engine
        before registering. Raises PolicyViolation if toolsets
        contain blocked tools.

        Args:
            spec: AgentSpec to register.

        Returns:
            Agent name (from spec.name).
        """
        self._ensure_initialized()
        # Validate toolsets against policy (if policy engine is available)
        if hasattr(self._engine, '_policy_engine') and self._engine._policy_engine:
            pe = self._engine._policy_engine
            # Register per-agent policy override
            pe.set_agent_policy(spec.name, spec.policy)
            # Validate toolsets
            result = pe.check_agent_toolsets(
                spec.name, spec.toolsets,
            )
            if not result.allowed:
                from sccsos.security.policy import PolicyViolation
                raise PolicyViolation(result.reason)
        return self._registry.register(spec)

    def close(self) -> None:
        """Release resources (DB connections, stop agents, etc.)."""
        if self._runner:
            try:
                self._runner.stop_all()
            except Exception:
                pass
        if self._db:
            try:
                self._db.close()
            except Exception:
                pass
        self._initialized = False


# ── Runtime Factory (shared singleton for CLI & API) ────────


class RuntimeFactory:
    """Factory for AgentRuntime that supports test override.

    Shared singleton used by both CLI (cli.py) and API server
    (api/server.py) to avoid dual-runtime anti-pattern.
    """

    def __init__(self):
        self._runtime: AgentRuntime | None = None

    def get(self) -> AgentRuntime:
        if self._runtime is None:
            self._runtime = AgentRuntime()
        return self._runtime

    def set(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime


_runtime_factory = RuntimeFactory()


def get_runtime() -> AgentRuntime:
    """Get the current AgentRuntime singleton."""
    return _runtime_factory.get()


def set_runtime(runtime: AgentRuntime) -> None:
    """Override the runtime singleton (used in tests)."""
    _runtime_factory.set(runtime)
