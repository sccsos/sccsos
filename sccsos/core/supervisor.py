"""LocalSupervisor — in-process AgentProcess monitoring with heartbeat + auto-restart.

Each AgentProcess calls ``heartbeat()`` on every iteration of its
run loop.  The supervisor runs a background monitor thread that
detects:

- **Dead processes**: thread exited unexpectedly → auto-restart
  (up to ``max_restarts`` times, then permanent failure).
- **Unresponsive processes**: no heartbeat within ``heartbeat_timeout``
  → logged as warning, flagged in status.
- **Paused processes**: tracked but not restarted.

Usage::

    from sccsos.core.supervisor import LocalSupervisor
    supervisor = LocalSupervisor(max_restarts=3, heartbeat_timeout=30.0)
    supervisor.register("architect", agent_process)
    supervisor.start()       # starts monitor thread
    ...
    supervisor.stop()        # stops monitor thread (on shutdown)
    status = supervisor.get_status("architect")
"""
from __future__ import annotations

import logging
import time
import threading
from typing import TYPE_CHECKING, Optional

from sccsos.core.supervisor_base import SupervisorABC, ProcessStatus

if TYPE_CHECKING:
    from sccsos.core.agent_runner import AgentProcess

logger = logging.getLogger("sccsos.supervisor")


class LocalSupervisor(SupervisorABC):
    """Monitors AgentProcess instances with heartbeat + auto-restart.

    Thread-safe: all mutable state is accessed under ``_lock``.
    The monitor loop runs in a single daemon thread.
    """

    def __init__(
        self,
        max_restarts: int = 3,
        heartbeat_timeout: float = 30.0,
        check_interval: float = 5.0,
    ):
        self._max_restarts = max_restarts
        self._heartbeat_timeout = heartbeat_timeout
        self._check_interval = check_interval

        self._lock = threading.Lock()
        self._processes: dict[str, AgentProcess] = {}
        self._heartbeats: dict[str, float] = {}       # name → time.monotonic()
        self._start_times: dict[str, float] = {}       # name → time.monotonic()
        self._restart_counts: dict[str, int] = {}

        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None

    # ── Public API ───────────────────────────────────────────────

    def register(self, name: str, process: AgentProcess) -> None:
        """Start supervising an AgentProcess.

        Args:
            name: Agent name (used as identifier).
            process: The AgentProcess instance.
        """
        with self._lock:
            self._processes[name] = process
            now = time.monotonic()
            self._heartbeats[name] = now
            self._start_times[name] = now
            if name not in self._restart_counts:
                self._restart_counts[name] = 0

    def unregister(self, name: str) -> None:
        """Stop supervising a process."""
        with self._lock:
            self._processes.pop(name, None)
            self._heartbeats.pop(name, None)
            self._start_times.pop(name, None)
            self._restart_counts.pop(name, None)

    def heartbeat(self, name: str) -> None:
        """Record a heartbeat for a supervised process.

        Called by AgentProcess on each iteration of its run loop.
        """
        with self._lock:
            if name in self._heartbeats:
                self._heartbeats[name] = time.monotonic()

    def start(self) -> None:
        """Start the background monitor thread."""
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="supervisor",
            daemon=True,
        )
        self._monitor_thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        """Stop the background monitor thread.

        Args:
            timeout: Max seconds to wait for the thread to join.
        """
        self._stop_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=timeout)

    def get_status(self, name: str) -> Optional[ProcessStatus]:
        """Get health status for a single process.

        Args:
            name: Agent name.

        Returns:
            ProcessStatus, or None if the process is not supervised.
        """
        with self._lock:
            proc = self._processes.get(name)
            if proc is None:
                return None
            now = time.monotonic()
            last_hb = self._heartbeats.get(name, 0.0)
            start = self._start_times.get(name, now)
            return ProcessStatus(
                name=name,
                alive=proc.is_alive,
                responsive=(now - last_hb) < self._heartbeat_timeout,
                restart_count=self._restart_counts.get(name, 0),
                paused=proc.is_paused,
                uptime_seconds=now - start,
            )

    def list_status(self) -> list[ProcessStatus]:
        """Get health status for all supervised processes."""
        with self._lock:
            return [
                s for n in list(self._processes.keys())
                if (s := self._get_status_locked(n)) is not None
            ]

    @property
    def is_running(self) -> bool:
        """Whether the monitor thread is active."""
        return self._monitor_thread is not None and self._monitor_thread.is_alive()

    # ── Internal ─────────────────────────────────────────────────

    def _get_status_locked(self, name: str) -> Optional[ProcessStatus]:
        """Get status (caller must hold ``_lock``)."""
        proc = self._processes.get(name)
        if proc is None:
            return None
        now = time.monotonic()
        last_hb = self._heartbeats.get(name, 0.0)
        start = self._start_times.get(name, now)
        return ProcessStatus(
            name=name,
            alive=proc.is_alive,
            responsive=(now - last_hb) < self._heartbeat_timeout,
            restart_count=self._restart_counts.get(name, 0),
            paused=proc.is_paused,
            uptime_seconds=now - start,
        )

    def _monitor_loop(self) -> None:
        """Background loop: check health, restart dead processes."""
        logger.info(
            "Supervisor started (max_restarts=%d, heartbeat_timeout=%.1fs, check=%.1fs)",
            self._max_restarts, self._heartbeat_timeout, self._check_interval,
        )

        while not self._stop_event.is_set():
            now = time.monotonic()
            names_to_check: list[str] = []

            with self._lock:
                names_to_check = list(self._processes.keys())

            for name in names_to_check:
                with self._lock:
                    if name not in self._processes:
                        continue
                    proc = self._processes[name]
                    alive = proc.is_alive
                    paused = proc.is_paused
                    last_hb = self._heartbeats.get(name, 0.0)

                # ── Dead process → auto-restart ──────────────
                if not alive and not paused:
                    count = self._restart_counts.get(name, 0)
                    if count < self._max_restarts:
                        logger.warning(
                            "Agent '%s' died (%d/%d restarts). Restarting...",
                            name, count + 1, self._max_restarts,
                        )
                        proc.start()
                        with self._lock:
                            self._restart_counts[name] = count + 1
                            self._start_times[name] = time.monotonic()
                    else:
                        logger.error(
                            "Agent '%s' exceeded max restarts (%d). Giving up.",
                            name, self._max_restarts,
                        )

                # ── Unresponsive process → warn ─────────────
                elif alive and not paused:
                    if (now - last_hb) > self._heartbeat_timeout:
                        logger.warning(
                            "Agent '%s' unresponsive (no heartbeat for %.1fs)",
                            name, now - last_hb,
                        )

            self._stop_event.wait(self._check_interval)

        logger.info("Supervisor stopped.")


# ── Backward-compatible alias ─────────────────────────────────────
Supervisor = LocalSupervisor
