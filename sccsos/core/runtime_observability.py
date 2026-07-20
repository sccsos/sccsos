"""ObservabilityRuntime — tracing, auditing, pricing, alerts, webhooks.

Initialises Tracer, Auditor, PricingTable, AlertManager, WebhookNotifier,
and optional OpenTelemetry bridge.  Depends on Database and Config from
RuntimeCore.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from sccsos.core.db import Database
from sccsos.observability.tracer import Tracer
from sccsos.observability.auditor import Auditor
from sccsos.observability.pricing import PricingTable
from sccsos.observability.webhook import WebhookNotifier
from sccsos.observability.alert_manager import AlertManager

logger = logging.getLogger("sccsos.runtime_observability")


class ObservabilityRuntime:
    """Observability services: tracer, auditor, pricing, alerts, webhooks."""

    def __init__(self, db: Database, config):
        self._db = db
        self._cfg = config
        self._tracer: Optional[Tracer] = None
        self._auditor: Optional[Auditor] = None
        self._pricing: Optional[PricingTable] = None
        self._webhook: Optional[WebhookNotifier] = None
        self._alert_manager: Optional[AlertManager] = None

    @property
    def tracer(self) -> Tracer:
        return self._tracer

    @property
    def auditor(self) -> Auditor:
        return self._auditor

    @property
    def pricing(self) -> PricingTable:
        return self._pricing

    @property
    def webhook(self) -> WebhookNotifier:
        return self._webhook

    @property
    def alert_manager(self) -> AlertManager:
        return self._alert_manager

    def initialize(self) -> None:
        cfg = self._cfg

        # Optional OTel bridge
        otel_bridge = None
        otlp_endpoint = getattr(cfg.tracing, 'otlp_endpoint', '')
        if cfg.tracing.enabled and otlp_endpoint:
            try:
                from sccsos.observability.otel_tracer import OTelTracerBridge
                otel_headers = getattr(cfg.tracing, 'otlp_headers', [])
                otel_bridge = OTelTracerBridge(
                    otlp_endpoint=otlp_endpoint,
                    otlp_headers=otel_headers or [],
                )
            except Exception:
                pass

        self._tracer = Tracer(
            self._db,
            export_path=cfg.tracing.export_path if cfg.tracing.enabled else None,
            otel_bridge=otel_bridge,
        )

        # Pricing
        pricing_path = cfg.pricing.path or cfg.tracing.pricing_path
        if pricing_path:
            # Deprecation warning: old cfg.tracing.pricing_path is still supported
            if not cfg.pricing.path and cfg.tracing.pricing_path:
                logger.warning(
                    "Config field 'tracing.pricing_path' is deprecated. "
                    "Use 'pricing.path' instead.",
                )
            self._pricing = PricingTable(Path(pricing_path))
        else:
            self._pricing = PricingTable()

        self._auditor = Auditor(self._db, pricing=self._pricing)
        self._webhook = WebhookNotifier(getattr(cfg, 'webhooks', None))
        self._alert_manager = AlertManager(self._db, cfg, self._webhook)
