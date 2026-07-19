"""Alert Manager — threshold-based monitoring and webhook alert dispatch.

Evaluates system metrics (error rates, budget consumption, failure counts)
against configured thresholds and fires webhook alerts when exceeded.

Usage:
    alerts = AlertManager(db, config, webhook)
    alerts.evaluate_after_run(run_id="wf_xxx", tenant_id="default")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sccsos.core.database import Database
from sccsos.core.config import AgentOSConfig
from sccsos.observability.webhook import WebhookNotifier


logger = logging.getLogger("sccsos.alerts")


@dataclass
class AlertThreshold:
    """Threshold configuration for a single alert rule."""
    metric: str          # 'error_rate', 'budget_usage', 'failure_count'
    warning: float = 0.0  # Threshold for WARNING level
    critical: float = 0.0  # Threshold for CRITICAL level
    window_minutes: int = 60  # Evaluation window


@dataclass
class AlertResult:
    """Result of an alert evaluation."""
    triggered: bool = False
    level: str = ""       # 'WARNING' or 'CRITICAL'
    metric: str = ""
    value: float = 0.0
    threshold: float = 0.0
    message: str = ""


class AlertManager:
    """Evaluates system metrics against thresholds and fires webhook alerts.

    Integrates with WebhookNotifier for alert dispatch. Alerts are
    best-effort — failures are logged but never propagated.
    """

    def __init__(self, db: Database, config: Optional[AgentOSConfig] = None,
                 webhook: Optional[WebhookNotifier] = None):
        self._db = db
        self._config = config
        self._webhook = webhook or WebhookNotifier()
        self._log = logging.getLogger("sccsos.alerts")

        # Default thresholds (can be overridden via config)
        self._thresholds: dict[str, AlertThreshold] = {
            "error_rate": AlertThreshold(
                metric="error_rate", warning=0.1, critical=0.3,
                window_minutes=60,
            ),
            "failure_count": AlertThreshold(
                metric="failure_count", warning=5, critical=20,
                window_minutes=60,
            ),
        }

    # ── Public API ───────────────────────────────────────────────

    def evaluate_after_run(self, run_id: str = "",
                           tenant_id: str = "default") -> list[AlertResult]:
        """Evaluate all thresholds after a workflow run.

        Args:
            run_id: Workflow run ID (for alert context).
            tenant_id: Tenant to evaluate alerts for.

        Returns:
            List of triggered AlertResult (empty if all clear).
        """
        results: list[AlertResult] = []

        for name, threshold in self._thresholds.items():
            result = self._evaluate_threshold(threshold, tenant_id)
            if result.triggered:
                results.append(result)
                self._fire_alert(result, run_id, tenant_id)

        if not results:
            self._log.info(
                "No alerts triggered (tenant=%s run=%s)", tenant_id, run_id,
            )

        return results

    def evaluate_global(self, tenant_id: str = "default") -> list[AlertResult]:
        """Evaluate all thresholds for periodic health checks."""
        return self.evaluate_after_run(run_id="healthcheck", tenant_id=tenant_id)

    # ── Internal ─────────────────────────────────────────────────

    def _evaluate_threshold(self, threshold: AlertThreshold,
                            tenant_id: str) -> AlertResult:
        """Evaluate a single threshold and return alert if triggered."""
        since = (datetime.now(timezone.utc) -
                 timedelta(minutes=threshold.window_minutes)).isoformat()

        if threshold.metric == "error_rate":
            # Count total and failed calls in the window
            total = self._db.execute(
                """SELECT COUNT(*) FROM audit_log
                   WHERE timestamp >= ? AND tenant_id = ?""",
                (since, tenant_id),
            ).fetchone()[0]

            if total == 0:
                return AlertResult()

            failed = self._db.execute(
                """SELECT COUNT(*) FROM audit_log
                   WHERE timestamp >= ? AND tenant_id = ? AND success = 0""",
                (since, tenant_id),
            ).fetchone()[0]

            rate = failed / total
            level = self._get_level(rate, threshold)
            if level:
                return AlertResult(
                    triggered=True,
                    level=level,
                    metric="error_rate",
                    value=rate,
                    threshold=(threshold.critical if level == "CRITICAL"
                               else threshold.warning),
                    message=(
                        f"Error rate {rate:.1%} {'≥' if level == 'CRITICAL' else '≥'} "
                        f"{threshold.warning:.0%} threshold "
                        f"({failed}/{total} calls failed in "
                        f"{threshold.window_minutes}m)"
                    ),
                )

        elif threshold.metric == "failure_count":
            failed = self._db.execute(
                """SELECT COUNT(*) FROM audit_log
                   WHERE timestamp >= ? AND tenant_id = ? AND success = 0""",
                (since, tenant_id),
            ).fetchone()[0]

            level = self._get_level(failed, threshold)
            if level:
                return AlertResult(
                    triggered=True,
                    level=level,
                    metric="failure_count",
                    value=float(failed),
                    threshold=(threshold.critical if level == "CRITICAL"
                               else threshold.warning),
                    message=(
                        f"Failure count {failed} {'≥' if level == 'CRITICAL' else '≥'} "
                        f"{threshold.warning:.0f} threshold "
                        f"(in {threshold.window_minutes}m)"
                    ),
                )

        return AlertResult()

    def _get_level(self, value: float, threshold: AlertThreshold) -> str:
        """Determine alert level based on value vs thresholds."""
        if threshold.critical > 0 and value >= threshold.critical:
            return "CRITICAL"
        if threshold.warning > 0 and value >= threshold.warning:
            return "WARNING"
        return ""

    def _fire_alert(self, alert: AlertResult, run_id: str,
                    tenant_id: str) -> None:
        """Dispatch alert via webhook."""
        if not self._webhook or not self._webhook.enabled:
            self._log.warning(
                "[%s] %s (tenant=%s run=%s)",
                alert.level, alert.message, tenant_id, run_id,
            )
            return

        self._webhook.fire(
            event="alert",
            run_id=run_id,
            workflow_name=f"alert:{alert.metric}",
            status=alert.level.lower(),
            error=alert.message,
        )
        self._log.info(
            "Alert sent: level=%s metric=%s value=%.2f (tenant=%s)",
            alert.level, alert.metric, alert.value, tenant_id,
        )
