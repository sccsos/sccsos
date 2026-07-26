"""RemoteKnowledgeBase — HTTP client for the wiki microservice.

When ``knowledge.mode = remote``, KnowledgeBase delegates all queries
to a standalone wiki service over HTTP. This allows the wiki to be
deployed as an independent, horizontally scalable microservice.

Usage:
    kb = RemoteKnowledgeBase("http://wiki-service:8750")
    results = kb.query("agent lifecycle")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib import request as urllib_request
from urllib.error import URLError

from sccsos.memory.knowledge_base import KnowledgeEntry

logger = logging.getLogger("sccsos.memory.remote_kb")


@dataclass
class RemoteKnowledgeBase:
    """HTTP client for the wiki microservice.

    Implements the same query interface as ``KnowledgeBase`` but sends
    requests to a remote wiki service. All SCCS OS instances share the
    same remote service, giving them a consistent, clustered wiki index.

    Args:
        base_url: Wiki service URL (e.g. ``http://wiki-service:8750``).
        api_key: Optional API key for authentication.
        timeout: HTTP request timeout in seconds.
    """

    base_url: str = "http://localhost:8750"
    api_key: str = ""
    timeout: int = 10

    # ── Public API (mirrors KnowledgeBase) ─────────────────────────

    def query(self, query: str, top_k: int = 5) -> list[KnowledgeEntry]:
        """Search the remote knowledge base.

        Returns:
            List of KnowledgeEntry sorted by relevance (descending).
            Empty list on error.
        """
        payload = json.dumps({"query": query, "top_k": top_k}).encode()
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            req = urllib_request.Request(
                f"{self.base_url.rstrip('/')}/query",
                data=payload,
                headers=headers,
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
                return [KnowledgeEntry(**item) for item in data.get("results", [])]
        except (URLError, json.JSONDecodeError, OSError) as e:
            logger.error("RemoteKnowledgeBase: query failed: %s", e)
            return []

    def get_context_for(self, topic: str) -> str:
        """Get consolidated context string for a topic."""
        payload = json.dumps({"query": topic, "top_k": 3}).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            req = urllib_request.Request(
                f"{self.base_url.rstrip('/')}/context",
                data=payload,
                headers=headers,
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
                return data.get("context", "")
        except (URLError, json.JSONDecodeError, OSError) as e:
            logger.error("RemoteKnowledgeBase: get_context_for failed: %s", e)
            return ""

    def health(self) -> dict:
        """Check the wiki service health."""
        try:
            req = urllib_request.Request(
                f"{self.base_url.rstrip('/')}/health",
                method="GET",
            )
            with urllib_request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except (URLError, json.JSONDecodeError, OSError) as e:
            return {"status": "unreachable", "error": str(e)}

    def list_sources(self) -> list[str]:
        """List available knowledge sources from remote service."""
        try:
            req = urllib_request.Request(
                f"{self.base_url.rstrip('/')}/sources",
                method="GET",
            )
            with urllib_request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
                return data.get("sources", [])
        except (URLError, json.JSONDecodeError, OSError) as e:
            logger.error("RemoteKnowledgeBase: list_sources failed: %s", e)
            return []

    def reload(self) -> bool:
        """Trigger a full reload of the remote knowledge base."""
        try:
            req = urllib_request.Request(
                f"{self.base_url.rstrip('/')}/reload",
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
                return data.get("status") == "ok"
        except (URLError, json.JSONDecodeError, OSError) as e:
            logger.error("RemoteKnowledgeBase: reload failed: %s", e)
            return False
