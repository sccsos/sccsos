"""OpenTelemetry integration — optional trace export to OTLP endpoints.

Usage (in sccsos.yaml)::

    tracing:
      enabled: true
      otlp_endpoint: http://jaeger:4318/v1/traces
      otlp_headers:
        - "Authorization=Bearer my-token"

Install: ``pip install sccsos[otel]``

Architecture::

    StepExecutor / WorkflowEngine
        │
        ▼
    Tracer (sccsos core)
        │
        ├── SQLite + JSON export  (always on)
        └── OTelTracerBridge      (optional, when configured)
                │
                ▼
        OpenTelemetry SDK
                │
                ▼
        OTLP exporter → Jaeger / Grafana / SigNoz
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("sccsos.otel")


# ── OTel Bridge ────────────────────────────────────────────────────


class OTelTracerBridge:
    """Bridges sccsos's native Tracer to OpenTelemetry.

    Mirrors span start/end/event calls to OpenTelemetry when OTel
    SDK is available and configured.  Gracefully degrades to no-op
    when OTel dependencies are missing.
    """

    def __init__(self, otlp_endpoint: str = "",
                 otlp_headers: Optional[list[str]] = None,
                 service_name: str = "sccsos"):
        self._enabled = False
        self._tracer_provider = None
        self._tracer = None
        self._span_map: dict[str, Any] = {}  # sccsos span_id → OTel span

        if not otlp_endpoint:
            return  # No OTel configured

        try:
            self._setup(otlp_endpoint, otlp_headers or [], service_name)
            self._enabled = True
            logger.info(
                "OpenTelemetry enabled — exporting traces to %s",
                otlp_endpoint,
            )
        except Exception as e:
            logger.warning(
                "Failed to initialize OpenTelemetry: %s. "
                "Falling back to SQLite-only tracing.",
                e,
            )

    def _setup(self, endpoint: str, headers: list[str],
               service_name: str) -> None:
        """Initialize OpenTelemetry SDK (lazy imports, optional deps)."""
        from opentelemetry import trace as otel_trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)

        # Parse headers from config format ["Key=Value"] → dict
        parsed_headers = {}
        for h in headers:
            if "=" in h:
                k, v = h.split("=", 1)
                parsed_headers[k.strip()] = v.strip()

        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            headers=parsed_headers,
        )
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)

        otel_trace.set_tracer_provider(provider)
        self._tracer_provider = provider
        self._tracer = otel_trace.get_tracer(service_name)

    # ── Public API (mirrors sccsos Tracer) ───────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start_span(self, name: str, trace_id: str = "",
                   parent_span_id: str = "",
                   attributes: Optional[dict] = None) -> str:
        """Start an OTel span. Returns the OTel span_id.

        Args:
            name: Span name (e.g. ``"step:requirements"``).
            trace_id: sccsos trace_id (set as OTel attribute).
            parent_span_id: sccsos parent span_id for parent lookup.
            attributes: Optional attributes.

        Returns:
            OTel span_id hex string, or empty string if OTel is off.
        """
        if not self._enabled or self._tracer is None:
            return ""

        from opentelemetry import trace as otel_trace

        # Look up parent from span map
        parent = self._span_map.get(parent_span_id) if parent_span_id else None
        context = None
        if parent:
            ctx = otel_trace.set_span_in_context(parent)
        else:
            ctx = None

        attrs = dict(attributes or {})
        if trace_id:
            attrs["sccsos.trace_id"] = trace_id

        span = self._tracer.start_span(
            name,
            context=ctx,
            attributes=attrs or None,
        )
        span_id = format(span.get_span_context().span_id, "016x")
        self._span_map[span_id] = span
        return span_id

    def end_span(self, otel_span_id: str, status: str = "ok",
                 description: str = "") -> None:
        """End an OTel span.

        Args:
            otel_span_id: OTel span_id (returned by ``start_span``).
            status: ``"ok"`` or ``"error"``.
            description: Error description (only used when status is error).
        """
        if not self._enabled:
            return

        span = self._span_map.pop(otel_span_id, None)
        if span is None:
            return

        from opentelemetry import trace as otel_trace

        if status == "error":
            span.set_status(otel_trace.Status(
                otel_trace.StatusCode.ERROR,
                description=description or "",
            ))
        else:
            span.set_status(otel_trace.Status(otel_trace.StatusCode.OK))

        span.end()

    def add_event(self, otel_span_id: str, name: str,
                  attributes: Optional[dict] = None) -> None:
        """Add an event to an active OTel span."""
        if not self._enabled:
            return
        span = self._span_map.get(otel_span_id)
        if span is not None:
            span.add_event(name, attributes or {})

    def shutdown(self) -> None:
        """Flush and shutdown the OTel provider."""
        if self._enabled and self._tracer_provider is not None:
            try:
                self._tracer_provider.shutdown()
            except Exception as e:
                logger.warning("OTel shutdown error: %s", e)
