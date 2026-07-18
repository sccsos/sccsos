"""Tracer — Span-based distributed tracing for sccsos.

Each workflow run or agent session produces a trace tree of spans.
Spans record timing, status, events, and parent-child relationships.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sccsos.core.database import Database


@dataclass
class SpanEvent:
    """A single event within a span (e.g. tool call, LLM call)."""
    name: str
    timestamp: str = ""
    attributes: dict = field(default_factory=dict)


@dataclass
class Span:
    """A single span in a trace tree."""

    trace_id: str
    span_id: str
    name: str
    parent_span_id: Optional[str] = None
    agent_name: str = ""
    start_time: str = ""
    end_time: str = ""
    duration_ms: int = 0
    status: str = "ok"
    events: list[SpanEvent] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class Tracer:
    """Creates and manages trace spans, persisted to the database.

    Optionally exports completed spans to JSON files on disk
    (configured via ``export_path`` in sccsos.yaml).

    Usage:
        tracer = Tracer(db)
        span = tracer.start_span("architecture-review", agent="architect")
        # ... do work ...
        tracer.end_span(span.span_id)
    """

    def __init__(self, db: Database, export_path: Optional[str | Path] = None):
        self._db = db
        self._export_path = Path(export_path) if export_path else None
        if self._export_path:
            self._export_path.mkdir(parents=True, exist_ok=True)
        self._active_spans: dict[str, Span] = {}

    def start_span(self, name: str,
                   agent: str = "",
                   parent_span_id: Optional[str] = None,
                   trace_id: Optional[str] = None) -> Span:
        """Start a new span. Returns the span object."""
        span_id = f"spn_{uuid.uuid4().hex[:12]}"
        tid = trace_id or f"trc_{uuid.uuid4().hex[:12]}"

        span = Span(
            trace_id=tid,
            span_id=span_id,
            name=name,
            parent_span_id=parent_span_id,
            agent_name=agent,
            start_time=datetime.now(timezone.utc).isoformat(),
            status="running",
        )
        self._active_spans[span_id] = span
        return span

    def end_span(self, span_id: str, status: str = "ok") -> Span:
        """End a span, recording duration and persisting to DB."""
        span = self._active_spans.get(span_id)
        if span is None:
            raise KeyError(f"Span '{span_id}' not found")

        end_time = datetime.now(timezone.utc)
        span.end_time = end_time.isoformat()
        span.status = status

        # Calculate duration
        if span.start_time:
            try:
                start = datetime.fromisoformat(span.start_time)
                span.duration_ms = int((end_time - start).total_seconds() * 1000)
            except (ValueError, TypeError):
                span.duration_ms = 0

        # Persist to DB
        self._persist_span(span)

        # Export to JSON file (if export_path configured)
        self._export_span_json(span)

        # Remove from active
        del self._active_spans[span_id]
        return span

    def add_event(self, span_id: str, name: str,
                  attributes: Optional[dict] = None) -> None:
        """Add an event to an active span."""
        span = self._active_spans.get(span_id)
        if span is None:
            raise KeyError(f"Span '{span_id}' not found")

        event = SpanEvent(
            name=name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            attributes=attributes or {},
        )
        span.events.append(event)

    def get_trace(self, trace_id: str) -> list[dict]:
        """Get all spans for a trace."""
        conn = self._db.get_conn()
        rows = conn.execute(
            "SELECT * FROM traces WHERE trace_id = ? ORDER BY id",
            (trace_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_traces(self, limit: int = 20) -> list[dict]:
        """List recent traces (one row per trace)."""
        conn = self._db.get_conn()
        rows = conn.execute(
            """SELECT trace_id, count(*) as span_count,
                      min(start_time) as first_span,
                      sum(duration_ms) as total_duration_ms
               FROM traces
               GROUP BY trace_id
               ORDER BY first_span DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _persist_span(self, span: Span) -> None:
        """Write a completed span to the database."""
        conn = self._db.get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO traces
               (trace_id, span_id, parent_span_id, name, agent_name,
                start_time, end_time, duration_ms, status, events)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                span.trace_id,
                span.span_id,
                span.parent_span_id,
                span.name,
                span.agent_name,
                span.start_time,
                span.end_time,
                span.duration_ms,
                span.status,
                json.dumps([asdict(e) for e in span.events], ensure_ascii=False),
            ),
        )
        conn.commit()

    def _export_span_json(self, span: Span) -> None:
        """Export a completed span to a JSON file (if ``export_path`` configured).

        Each span is written as ``{export_path}/{trace_id}/{span_id}.json``.
        This enables external tools (Grafana, log aggregators) to ingest
        trace data without direct DB access.
        """
        if self._export_path is None:
            return
        trace_dir = self._export_path / span.trace_id
        trace_dir.mkdir(parents=True, exist_ok=True)
        span_file = trace_dir / f"{span.span_id}.json"
        data = {
            "trace_id": span.trace_id,
            "span_id": span.span_id,
            "parent_span_id": span.parent_span_id,
            "name": span.name,
            "agent_name": span.agent_name,
            "start_time": span.start_time,
            "end_time": span.end_time,
            "duration_ms": span.duration_ms,
            "status": span.status,
            "events": [asdict(e) for e in span.events],
        }
        span_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
