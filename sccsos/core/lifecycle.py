"""Lifecycle Manager — Agent state machine.

States:
  CREATED    — Agent spec registered, not yet started
  RUNNING    — Agent has an active session
  PAUSED     — Agent paused, context frozen
  FAILED     — Agent encountered an error, needs intervention
  TERMINATED — Agent stopped, resources released

Transitions:
  CREATED    → start()    → RUNNING
  RUNNING    → pause()    → PAUSED
  RUNNING    → fail()     → FAILED
  RUNNING    → stop()     → TERMINATED
  PAUSED     → resume()   → RUNNING
  PAUSED     → stop()     → TERMINATED
  FAILED     → restart()  → RUNNING
  FAILED     → stop()     → TERMINATED
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Optional

from sccsos.core.database import Database
from sccsos.core.registry import AgentSpec, AgentRegistry


class AgentStatus(str, Enum):
    """Agent lifecycle states."""
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    TERMINATED = "terminated"


# ── Transition Matrix ──────────────────────────────────────────────
# (from_state, event) → to_state

TRANSITIONS: dict[tuple[AgentStatus, str], AgentStatus] = {
    (AgentStatus.CREATED, "start"):    AgentStatus.RUNNING,
    (AgentStatus.RUNNING, "pause"):    AgentStatus.PAUSED,
    (AgentStatus.RUNNING, "fail"):     AgentStatus.FAILED,
    (AgentStatus.RUNNING, "stop"):     AgentStatus.TERMINATED,
    (AgentStatus.PAUSED,  "resume"):   AgentStatus.RUNNING,
    (AgentStatus.PAUSED,  "stop"):     AgentStatus.TERMINATED,
    (AgentStatus.FAILED,  "restart"):  AgentStatus.RUNNING,
    (AgentStatus.FAILED,  "stop"):     AgentStatus.TERMINATED,
}


class TransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


class AgentInstance:
    """Runtime representation of an agent."""

    def __init__(self, agent_id: str, spec: AgentSpec, db: Database):
        self.id = agent_id
        self.spec = spec
        self._db = db
        self._status = AgentStatus.CREATED

    @property
    def status(self) -> AgentStatus:
        return self._status

    def set_status(self, value: AgentStatus) -> None:
        """Set status with validation — only accepts AgentStatus enum values.

        Use ``_transition()`` for lifecycle-valid transitions
        (e.g., CREATED → RUNNING). This setter is for internal
        use (e.g., restore from DB) and controlled test scenarios.
        """
        if not isinstance(value, AgentStatus):
            raise TypeError(
                f"Invalid status type: {type(value).__name__}. "
                f"Use AgentStatus enum values."
            )
        self._status = value

    def __repr__(self) -> str:
        return f"<AgentInstance {self.id}: {self.spec.name} [{self.status.value}]>"


class LifecycleManager:
    """Manages agent lifecycle with a strict state machine."""

    def __init__(self, db: Database, registry: AgentRegistry):
        self._db = db
        self._registry = registry
        self._instances: dict[str, AgentInstance] = {}

    def _transition(self, instance: AgentInstance, event: str) -> AgentStatus:
        """Validate and apply a state transition."""
        key = (instance.status, event)
        if key not in TRANSITIONS:
            raise TransitionError(
                f"Invalid transition: '{instance.status.value}' → '{event}' "
                f"(agent: {instance.spec.name})"
            )
        new_status = TRANSITIONS[key]
        old_status = instance.status
        instance.set_status(new_status)
        detail = f"{old_status.value} → {new_status.value} via {event}"
        self._db.add_event(instance.id, new_status.value, detail)

        return new_status

    # ── Public API ──────────────────────────────────────────────

    def create(self, spec: AgentSpec) -> AgentInstance:
        """Register a new agent instance in CREATED state."""
        agent_id = f"agent_{uuid.uuid4().hex[:12]}"
        instance = AgentInstance(agent_id, spec, self._db)

        # Persist
        import json
        self._db.insert_agent(
            agent_id=agent_id,
            name=spec.name,
            spec_json=json.dumps(spec.to_dict(), ensure_ascii=False),
            spec_version=spec.version,
            hermes_profile=spec.profile,
            tenant_id=spec.tenant_id,
        )
        self._db.add_event(agent_id, "created", f"Agent '{spec.name}' created")

        self._instances[agent_id] = instance
        return instance

    def start(self, agent_id: str, session_id: Optional[str] = None) -> AgentInstance:
        """Start an agent: CREATED → RUNNING."""
        instance = self._get_instance(agent_id)
        new_status = self._transition(instance, "start")

        sid = session_id or f"ses_{uuid.uuid4().hex[:12]}"
        self._db.update_agent_status(agent_id, new_status.value, session_id=sid)
        return instance

    def pause(self, agent_id: str) -> AgentInstance:
        """Pause an agent: RUNNING → PAUSED."""
        instance = self._get_instance(agent_id)
        new_status = self._transition(instance, "pause")
        self._db.update_agent_status(agent_id, new_status.value)
        return instance

    def resume(self, agent_id: str, session_id: Optional[str] = None) -> AgentInstance:
        """Resume an agent: PAUSED → RUNNING."""
        instance = self._get_instance(agent_id)
        new_status = self._transition(instance, "resume")
        sid = session_id or f"ses_{uuid.uuid4().hex[:12]}"
        self._db.update_agent_status(agent_id, new_status.value, session_id=sid)
        return instance

    def stop(self, agent_id: str) -> AgentInstance:
        """Stop an agent: RUNNING|PAUSED|FAILED → TERMINATED."""
        instance = self._get_instance(agent_id)
        new_status = self._transition(instance, "stop")
        self._db.update_agent_status(agent_id, new_status.value)
        return instance

    def fail(self, agent_id: str, error: str = "") -> AgentInstance:
        """Mark an agent as failed: RUNNING → FAILED."""
        instance = self._get_instance(agent_id)
        new_status = self._transition(instance, "fail")
        self._db.update_agent_status(agent_id, new_status.value, error=error)
        return instance

    def restart(self, agent_id: str, session_id: Optional[str] = None) -> AgentInstance:
        """Restart a failed agent: FAILED → RUNNING."""
        instance = self._get_instance(agent_id)
        new_status = self._transition(instance, "restart")
        sid = session_id or f"ses_{uuid.uuid4().hex[:12]}"
        self._db.update_agent_status(agent_id, new_status.value, session_id=sid)
        return instance

    # ── Queries ─────────────────────────────────────────────────

    def get_instance(self, agent_id: str) -> Optional[AgentInstance]:
        """Get instance by ID."""
        return self._instances.get(agent_id)

    def get_status(self, agent_id: str) -> Optional[AgentStatus]:
        """Get status of an instance."""
        inst = self._instances.get(agent_id)
        return inst.status if inst else None

    def list_instances(self, status: Optional[AgentStatus] = None) -> list[AgentInstance]:
        """List all instances, optionally filtered by status."""
        instances = list(self._instances.values())
        if status:
            return [i for i in instances if i.status == status]
        return instances

    def _get_instance(self, agent_id: str) -> AgentInstance:
        """Get instance or raise."""
        inst = self._instances.get(agent_id)
        if inst is None:
            raise KeyError(f"Instance '{agent_id}' not found")
        return inst

    def _restore_instance(self, agent_id: str, spec: AgentSpec,
                          status: str) -> AgentInstance:
        """Restore an instance from database (internal use)."""
        inst = AgentInstance(agent_id, spec, self._db)
        inst.set_status(AgentStatus(status))
        self._instances[agent_id] = inst
        return inst
