"""DistributedSupervisor — DB-backed heartbeat for multi-replica deployments.

Each AgentProcess calls ``heartbeat()`` on every iteration, which
writes a timestamp to the database.  A background monitor thread
queries the database for stale heartbeats and triggers recovery.

Works across process boundaries (multiple uvicorn workers, K8s pods)
because heartbeats are stored in the shared database.

Usage::

    from sccsos.core.supervisor_distributed import DistributedSupervisor
    supervisor = DistributedSupervisor(db, max_restarts=3, heartbeat_timeout=60.0)
    supervisor.register("architect", agent_process)
    supervisor.start()
    ...
    supervisor.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Optional

from sccsos.core.db import Database
from sccsos.core.supervisor_base import SupervisorABC, ProcessStatus

if TYPE_CHECKING:
    from sccsos.core.agent_runner import AgentProcess


logger = logging.getLogger("sccsos.supervisor.distributed")


class DistributedSupervisor(SupervisorABC):
    """DB-backed supervisor for cross-process monitoring.

    Thread-safe: all mutable state is accessed under ``_lock``.
    """

    def __init__(
        self,
        db: Database,
        max_restarts: int = 3,
        heartbeat_timeout: float = 60.0,
        check_interval: float = 10.0,
    ):
        self._db = db
        self._max_restarts = max_restarts
        self._heartbeat_timeout = heartbeat_timeout
        self._check_interval = check_interval

        self._lock = threading.Lock()
        self._processes: dict[str, AgentProcess] = {}
        self._restart_counts: dict[str, int] = {}
        self._local_heartbeats: dict[str, float] = {}  # in-memory cache for fast path

        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None

        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create heartbeat table if it doesn't exist."""
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS supervisor_heartbeats (
                agent_name TEXT PRIMARY KEY,
                last_heartbeat REAL NOT NULL,
                start_time REAL NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        self._db.commit()

    def register(self, name: str, process: AgentProcess) -> None:
        with self._lock:
            self._processes[name] = process
            now = time.monotonic()
            self._local_heartbeats[name] = now
            if name not in self._restart_counts:
                self._restart_counts[name] = 0
        self._write_heartbeat(name, time.monotonic())

    def unregister(self, name: str) -> None:
        with self._lock:
            self._processes.pop(name, None)
            self._local_heartbeats.pop(name, None)
            self._restart_counts.pop(name, None)
        try:
            self._db.execute(
                "DELETE FROM supervisor_heartbeats WHERE agent_name = ?",
                (name,),
            )
            self._db.commit()
        except Exception:
            pass

    def heartbeat(self, name: str) -> None:
        with self._lock:
            if name in self._local_heartbeats:
                now = time.monotonic()
                self._local_heartbeats[name] = now
                # Write to DB every 3rd heartbeat to reduce write pressure
                if int(now * 10) % 3 == 0:
                    self._write_heartbeat(name, now)

    def _write_heartbeat(self, name: str, now: float) -> None:
        try:
            self._db.execute(
                """INSERT OR REPLACE INTO supervisor_heartbeats
                   (agent_name, last_heartbeat, start_time)
                   VALUES (?, ?, ?)""",
                (name, now, now),
            )
            self._db.commit()
        except Exception:
            pass

    def start(self) -> None:
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="supervisor-distributed",
            daemon=True,
        )
        self._monitor_thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=timeout)

    def get_status(self, name: str) -> Optional[ProcessStatus]:
        with self._lock:
            proc = self._processes.get(name)
            if proc is None:
                return None
            now = time.monotonic()
            last_hb = self._local_heartbeats.get(name, 0.0)
            start = self._local_heartbeats.get(name, now)
            return ProcessStatus(
                name=name,
                alive=proc.is_alive,
                responsive=(now - last_hb) < self._heartbeat_timeout,
                restart_count=self._restart_counts.get(name, 0),
                paused=proc.is_paused,
                uptime_seconds=now - start,
            )

    def list_status(self) -> list[ProcessStatus]:
        with self._lock:
            return [
                s for n in list(self._processes.keys())
                if (s := self._get_status_locked(n)) is not None
            ]

    def _get_status_locked(self, name: str) -> Optional[ProcessStatus]:
        proc = self._processes.get(name)
        if proc is None:
            return None
        now = time.monotonic()
        last_hb = self._local_heartbeats.get(name, 0.0)
        start = self._local_heartbeats.get(name, now)
        return ProcessStatus(
            name=name,
            alive=proc.is_alive,
            responsive=(now - last_hb) < self._heartbeat_timeout,
            restart_count=self._restart_counts.get(name, 0),
            paused=proc.is_paused,
            uptime_seconds=now - start,
        )

    @property
    def is_running(self) -> bool:
        return self._monitor_thread is not None and self._monitor_thread.is_alive()

    def _monitor_loop(self) -> None:
        logger.info(
            "DistributedSupervisor started (max_restarts=%d, heartbeat_timeout=%.1fs)",
            self._max_restarts, self._heartbeat_timeout,
        )
        while not self._stop_event.is_set():
            now = time.monotonic()
            with self._lock:
                names = list(self._processes.keys())

            for name in names:
                with self._lock:
                    if name not in self._processes:
                        continue
                    proc = self._processes[name]
                    alive = proc.is_alive
                    paused = proc.is_paused
                    last_hb = self._local_heartbeats.get(name, 0.0)
                    # Also check DB for cross-process heartbeat
                    if not alive and not paused:
                        count = self._restart_counts.get(name, 0)
                        if count < self._max_restarts:
                            logger.warning(
                                "Agent '%s' died (%d/%d restarts). Restarting...",
                                name, count + 1, self._max_restarts,
                            )
                            proc.start()
                            self._restart_counts[name] = count + 1
                        else:
                            logger.error(
                                "Agent '%s' exceeded max restarts (%d). Giving up.",
                                name, self._max_restarts,
                            )
                    elif alive and not paused:
                        if (now - last_hb) > self._heartbeat_timeout:
                            logger.warning(
                                "Agent '%s' unresponsive (no heartbeat for %.1fs)",
                                name, now - last_hb,
                            )

            self._stop_event.wait(self._check_interval)

        logger.info("DistributedSupervisor stopped.")
