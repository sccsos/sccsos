"""SCCS OS — Maintenance scheduler for periodic cleanup tasks.

Provides a lightweight background scheduler that runs cleanup
tasks (skill pruning, verification) on a configurable interval.
Can also be triggered manually via CLI or API.

Usage:
    from sccsos.core.maintenance import MaintenanceScheduler

    scheduler = MaintenanceScheduler(db)
    scheduler.start(interval_hours=24)  # Background thread
    scheduler.run_once()                # Immediate run
    scheduler.stop()                  # Stop background thread
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("sccsos.maintenance")


class MaintenanceScheduler:
    """Periodic maintenance runner for SCCS OS.

    Args:
        db: Database instance for skill market access.
    """

    def __init__(self, db):
        self._db = db
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ── Maintenance tasks ─────────────────────────────────────────

    def run_once(self) -> dict:
        """Run a single maintenance pass.

        Returns:
            Dict with results from each task.
        """
        results = {}

        # 1. Prune stale skills (draft/rejected > 90 days)
        from sccsos.skill_market import SkillMarket
        market = SkillMarket(self._db)
        pruned = market.prune_stale(days=90)
        results["prune_stale"] = pruned

        # 2. Prune orphaned (broken YAML)
        orphaned = market.prune_orphaned()
        results["prune_orphaned"] = orphaned

        # 3. Verify published skills
        verified = market.verify_all()
        results["verify"] = {
            "total": verified["total"],
            "valid": verified["valid"],
            "invalid": verified["invalid"],
            "issue_count": len(verified["issues"]),
        }

        total = sum(pruned.values()) + orphaned
        logger.info(
            "Maintenance complete: pruned %d stale, %d orphaned, "
            "verified %d/%d valid",
            sum(pruned.values()), orphaned,
            verified["valid"], verified["total"],
        )
        results["_meta"] = {
            "total_removed": total,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return results

    # ── Background scheduler ──────────────────────────────────────

    def start(self, interval_hours: int = 24) -> None:
        """Start the background maintenance scheduler.

        Args:
            interval_hours: Hours between maintenance runs (default 24).
        """
        if self._thread and self._thread.is_alive():
            logger.warning("Maintenance scheduler already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(interval_hours,),
            daemon=True,
            name="sccsos-maintenance",
        )
        self._thread.start()
        logger.info(
            "Maintenance scheduler started (interval=%dh)", interval_hours,
        )

    def stop(self) -> None:
        """Stop the background scheduler."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Maintenance scheduler stopped")

    def _run_loop(self, interval_hours: int) -> None:
        """Background loop: run maintenance every N hours."""
        interval_seconds = interval_hours * 3600
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("Maintenance run failed")
            self._stop_event.wait(interval_seconds)
