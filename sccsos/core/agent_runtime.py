"""AgentRuntime — unified entry point for all sccsos core services.

Composes three focused sub-runtimes:

  - RuntimeCore    → DB, Registry, Adapter, Runner, Sessions, Supervisor
  - ObservabilityRuntime → Tracer, Auditor, Pricing, Alerts, Webhooks
  - WorkflowRuntime → WorkflowEngine, PersonalityRegistry, EventBus wiring

Usage:
    runtime = AgentRuntime()
    runtime.initialize()
    runtime.registry.list()
    runtime.lifecycle.start("agent-1")
    runtime.close()
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Optional

from sccsos.core.config import AgentOSConfig, get_config
from sccsos.core.db import Database
from sccsos.core.registry import AgentRegistry, AgentSpec
from sccsos.core.lifecycle import LifecycleManager
from sccsos.core.hermes_adapter import HermesAdapter
from sccsos.core.agent_runner import AgentRunner
from sccsos.core.session import AgentSessionManager
from sccsos.core.supervisor import Supervisor
from sccsos.core.workflow import WorkflowEngine
from sccsos.memory.memory_store import MemoryStore
from sccsos.observability.tracer import Tracer
from sccsos.observability.auditor import Auditor
from sccsos.observability.logger import get_logger

logger = get_logger()


class AgentRuntime:
    """Central runtime composing CoreRuntime + ObservabilityRuntime + WorkflowRuntime."""

    def __init__(self, config: Optional[AgentOSConfig] = None):
        self._config = config
        self._initialized = False

        # Sub-runtimes (lazy)
        self._core = None
        self._obs = None
        self._wf = None

    # ── Properties delegate to sub-runtimes ─────────────────────────

    @property
    def config(self) -> AgentOSConfig:
        if self._config is None:
            self._config = get_config()
        return self._config

    @property
    def db(self) -> Database:
        self._ensure_initialized()
        return self._core.db

    @property
    def registry(self) -> AgentRegistry:
        self._ensure_initialized()
        return self._core.registry

    @property
    def lifecycle(self) -> LifecycleManager:
        self._ensure_initialized()
        return self._core.lifecycle

    @property
    def adapter(self) -> HermesAdapter:
        self._ensure_initialized()
        return self._core.adapter

    @property
    def engine(self) -> WorkflowEngine:
        self._ensure_initialized()
        return self._wf.engine

    @property
    def tracer(self) -> Tracer:
        self._ensure_initialized()
        return self._obs.tracer

    @property
    def auditor(self) -> Auditor:
        self._ensure_initialized()
        return self._obs.auditor

    @property
    def runner(self) -> AgentRunner:
        self._ensure_initialized()
        return self._core.runner

    @property
    def policy_engine(self):
        self._ensure_initialized()
        if self._wf and self._wf.engine and hasattr(self._wf.engine, '_policy_engine'):
            return self._wf.engine._policy_engine
        return None

    @property
    def memory(self) -> MemoryStore:
        self._ensure_initialized()
        return self._core.memory_store

    @property
    def model_router(self):
        self._ensure_initialized()
        return self._core.model_router

    @property
    def session_manager(self) -> AgentSessionManager:
        self._ensure_initialized()
        return self._core.session_manager

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    # ── Initialisation ─────────────────────────────────────────────

    def initialize(self) -> bool:
        if self._initialized:
            return True

        cfg = self.config

        try:
            from sccsos.core.runtime_core import RuntimeCore
            self._core = RuntimeCore(cfg)
            self._core.initialize()

            from sccsos.core.runtime_observability import ObservabilityRuntime
            self._obs = ObservabilityRuntime(self._core.db, cfg)
            self._obs.initialize()

            # Configure event bus backend from config
            from sccsos.core.event_bus import configure_event_bus
            configure_event_bus(
                backend=cfg.event_bus.backend,
                bootstrap_servers=cfg.event_bus.bootstrap_servers,
                client_id=cfg.event_bus.client_id,
                group_id=cfg.event_bus.group_id,
            )

            from sccsos.core.runtime_workflow import WorkflowRuntime
            self._wf = WorkflowRuntime(self._core, self._obs, cfg)
            self._wf.initialize()

            self._initialized = True
            self._check_config(cfg)
            return True
        except Exception:
            import logging
            logging.getLogger("sccsos.runtime").exception("AgentRuntime init failed")
            return False

    def _check_config(self, cfg) -> None:
        pricing_path = cfg.pricing.path or cfg.tracing.pricing_path
        if pricing_path:
            pp = Path(pricing_path)
            if not pp.exists():
                from sccsos.observability.logger import get_logger
                get_logger().info(
                    "Pricing file '%s' not found. Using default pricing.",
                    pricing_path,
                )

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            ok = self.initialize()
            if not ok:
                raise RuntimeError(
                    "AgentRuntime initialisation failed. "
                    "Run 'sccsos init' first or check config."
                )

    # ── Health ──────────────────────────────────────────────────────

    def health(self) -> dict:
        if not self._initialized:
            return {
                "status": "not_initialized",
                "version": self.config.project.version,
            }

        result = {
            "version": self.config.project.version,
            "initialized": True,
            "database": self._core.db.check_health(),
            "hermes": self._core.adapter.check_connectivity() if self._core.adapter else False,
            "agents": self._core.registry.count() if self._core.registry else 0,
        }

        if self._wf and self._wf.engine:
            try:
                traces = self._obs.tracer.list_traces(limit=1)
                result["traces_available"] = len(traces) > 0
            except Exception:
                result["traces_available"] = False

        return result

    # ── Lifecycle ──────────────────────────────────────────────────

    def register_agent(self, spec: AgentSpec) -> str:
        self._ensure_initialized()
        if self._wf and self._wf.engine and hasattr(self._wf.engine, '_policy_engine'):
            pe = self._wf.engine._policy_engine
            pe.set_agent_policy(spec.name, spec.policy)
            result = pe.check_agent_toolsets(spec.name, spec.toolsets)
            if not result.allowed:
                from sccsos.security.policy import PolicyViolation
                raise PolicyViolation(result.reason)
        return self._core.registry.register(spec)

    def close(self) -> None:
        if self._core and self._core.supervisor:
            try:
                self._core.supervisor.stop()
            except Exception as e:
                logger.warning("Supervisor stop failed: %s", e)
        if self._core and self._core.runner:
            try:
                self._core.runner.stop_all()
            except Exception as e:
                logger.warning("Runner stop_all failed: %s", e)
        if self._core and self._core.db:
            try:
                self._core.db.close()
            except Exception as e:
                logger.warning("DB close failed: %s", e)
        self._initialized = False


# ── Runtime Factory (per-tenant, shared singleton map for CLI & API) ─

_RUNTIMES: dict[str, AgentRuntime] = {}
_RUNTIME_LOCK = threading.Lock()


def get_runtime(tenant_id: str = "default") -> AgentRuntime:
    """Get or create a per-tenant AgentRuntime instance.

    Each tenant gets its own lazy-initialized runtime.  The ``"default"``
    tenant is used by the CLI and API routes that do not pass an explicit
    tenant ID.  API routes that receive an ``X-Tenant-ID`` header can call
    ``get_runtime(tenant_id=header_value)`` for future per-tenant isolation.

    Args:
        tenant_id: Tenant namespace (default ``"default"``).

    Returns:
        The AgentRuntime for the given tenant.
    """
    global _RUNTIMES
    with _RUNTIME_LOCK:
        if tenant_id not in _RUNTIMES:
            _RUNTIMES[tenant_id] = AgentRuntime()
        return _RUNTIMES[tenant_id]


def reset_runtime(tenant_id: Optional[str] = None) -> None:
    """Reset runtime(s). Used in tests.

    Args:
        tenant_id: If set, reset only that tenant's runtime.
            If ``None`` (default), reset all runtimes.
    """
    global _RUNTIMES
    with _RUNTIME_LOCK:
        if tenant_id is not None:
            rt = _RUNTIMES.pop(tenant_id, None)
            if rt is not None:
                try:
                    rt.close()
                except Exception as e:
                    logger.warning("Runtime close during reset failed: %s", e)
        else:
            for tid, rt in _RUNTIMES.items():
                try:
                    rt.close()
                except Exception as e:
                    logger.warning(
                        "Runtime close for '%s' during reset failed: %s", tid, e
                    )
            _RUNTIMES.clear()


# ── Legacy test support ────────────────────────────────────────────


def set_runtime(runtime: AgentRuntime, tenant_id: str = "default") -> None:
    """Override a per-tenant runtime instance (for test injection).

    Deprecated: use ``reset_runtime()`` in teardown instead.
    """
    global _RUNTIMES
    with _RUNTIME_LOCK:
        old = _RUNTIMES.get(tenant_id)
        if old is not None and old is not runtime:
            try:
                old.close()
            except Exception as e:
                logger.warning(
                    "Runtime close during set_runtime for '%s' failed: %s",
                    tenant_id, e,
                )
        _RUNTIMES[tenant_id] = runtime
