"""SupervisorABC — abstract interface for agent process monitoring.

Two implementations:

- ``LocalSupervisor`` — in-process thread monitoring (the original Supervisor)
- ``DistributedSupervisor`` — DB-backed heartbeat for multi-replica deployments

Usage::

    supervisor = LocalSupervisor(max_restarts=3, heartbeat_timeout=30.0)
    supervisor.register("architect", agent_process)
    supervisor.start()
    ...
    supervisor.stop()
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sccsos.core.agent_runner import AgentProcess


@dataclass
class ProcessStatus:
    """Snapshot of a supervised process's health."""

    name: str
    alive: bool               # Thread is running
    responsive: bool          # Heartbeat received recently
    restart_count: int        # Number of restarts attempted
    paused: bool = False
    uptime_seconds: float = 0.0


class SupervisorABC(ABC):
    """Abstract interface for agent process supervision."""

    @abstractmethod
    def register(self, name: str, process: AgentProcess) -> None:
        """Start supervising an AgentProcess."""

    @abstractmethod
    def unregister(self, name: str) -> None:
        """Stop supervising a process."""

    @abstractmethod
    def heartbeat(self, name: str) -> None:
        """Record a heartbeat for a supervised process.
        Called by AgentProcess on each iteration of its run loop.
        """

    @abstractmethod
    def start(self) -> None:
        """Start the background monitor thread."""

    @abstractmethod
    def stop(self, timeout: float = 3.0) -> None:
        """Stop the background monitor thread."""

    @abstractmethod
    def get_status(self, name: str) -> Optional[ProcessStatus]:
        """Get health status for a single process."""

    @abstractmethod
    def list_status(self) -> list[ProcessStatus]:
        """Get health status for all supervised processes."""

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Whether the monitor thread is active."""
