"""Webhook Notifier — zero-dependency HTTP callback dispatcher.

Fires workflow lifecycle events to configured webhook endpoints
using Python's built-in urllib. Designed as a best-effort notifier:
failures are logged but never propagated to the caller.

Usage:
    notifier = WebhookNotifier(config)
    notifier.fire("completed", run_id="wf_abc", workflow_name="my-wf")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib import request as urllib_request
from urllib.error import URLError

from sccsos.core.config import WebhooksConfig


logger = logging.getLogger("sccsos.webhook")


@dataclass
class WebhookPayload:
    """Payload sent to webhook endpoints."""
    event: str
    run_id: str
    workflow_name: str
    status: str
    timestamp: str = ""
    error: Optional[str] = None
    steps: list[dict] = field(default_factory=list)


class WebhookNotifier:
    """Best-effort webhook dispatcher.

    Fires events to all configured endpoints that subscribe to the
    given event type. Failures are logged but never raise exceptions.
    """

    def __init__(self, config: Optional[WebhooksConfig] = None):
        self._config = config or WebhooksConfig()
        self._log = logging.getLogger("sccsos.webhook")

    @property
    def enabled(self) -> bool:
        return self._config.enabled and len(self._config.endpoints) > 0

    def fire(self, event: str, run_id: str = "",
             workflow_name: str = "", status: str = "",
             error: Optional[str] = None,
             steps: Optional[list[dict]] = None) -> None:
        """Fire a webhook event to all subscribed endpoints.

        Args:
            event: Event type (``\"completed\"``, ``\"failed\"``, ``\"started\"``).
            run_id: Workflow run ID.
            workflow_name: Workflow name.
            status: Run status.
            error: Optional error message.
            steps: Optional list of step status dicts.
        """
        if not self.enabled:
            return

        payload = WebhookPayload(
            event=event,
            run_id=run_id,
            workflow_name=workflow_name,
            status=status,
            timestamp=datetime.now(timezone.utc).isoformat(),
            error=error,
            steps=steps or [],
        )
        body = json.dumps({
            "event": payload.event,
            "run_id": payload.run_id,
            "workflow_name": payload.workflow_name,
            "status": payload.status,
            "timestamp": payload.timestamp,
            "error": payload.error,
            "steps": payload.steps,
        }, ensure_ascii=False, default=str).encode("utf-8")

        for endpoint in self._config.endpoints:
            if event not in endpoint.events:
                continue
            try:
                req = urllib_request.Request(
                    endpoint.url,
                    data=body,
                    headers={
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    method="POST",
                )
                if endpoint.secret:
                    req.add_header("X-Webhook-Secret", endpoint.secret)

                resp = urllib_request.urlopen(req, timeout=10)
                self._log.info(
                    "Webhook sent: event=%s url=%s status=%s",
                    event, endpoint.url, resp.status,
                )
            except (URLError, TimeoutError, OSError) as e:
                self._log.warning(
                    "Webhook failed: event=%s url=%s error=%s",
                    event, endpoint.url, str(e),
                )
