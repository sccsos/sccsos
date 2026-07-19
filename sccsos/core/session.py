"""Session Manager — conversation history persistence for agent ask.

Provides agent_sessions and session_messages tables that store
the full dialogue history of ``agent ask`` interactions.

Architecture::

    AgentProcess._run_loop()
      └─ AgentSessionManager
            ├── get_or_create()        → active session or new
            ├── append_message()       → persist user/assistant turns
            ├── get_history(limit=N)   → last N messages for injection
            ├── close_session()        → mark session as closed
            └── update_summary()       → LLM-generated context summary

Design decisions:
- Session keys are (tenant_id, agent_name) — exactly one active session
  per agent per tenant at any time.
- History is injected as a text block prefixed to the prompt on each ask.
- PAUSED closes the session; RESUME creates a fresh one with the summary
  of the prior session injected as context.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sccsos.core.database import Database


@dataclass
class Message:
    """A single message in a conversation session."""

    id: int = 0
    session_id: str = ""
    role: str = ""  # 'user' | 'assistant'
    content: str = ""
    tokens: int = 0
    created_at: str = ""


@dataclass
class AgentSession:
    """A conversation session for one agent in one tenant."""

    id: str = ""
    agent_name: str = ""
    tenant_id: str = "default"
    status: str = "active"  # active | paused | closed
    created_at: str = ""
    updated_at: str = ""
    context_summary: str = ""


# ── Internal helpers ──────────────────────────────────────────────

_MAX_HISTORY_ROWS = 10  # default number of recent messages to inject
_MAX_HISTORY_TOKENS = 3000  # rough token budget for history injection


def _format_history(messages: list[Message]) -> str:
    """Format a list of messages into a text block for prompt injection.

    Args:
        messages: List of Message objects (newest first from DB, reversed).

    Returns:
        Formatted conversation history string.
    """
    if not messages:
        return ""
    lines = ["[Previous conversation]"]
    # Messages come from DB ordered by id DESC — reverse to chronological
    for msg in reversed(messages):
        prefix = "You said:" if msg.role == "user" else "Assistant:"
        # Truncate very long individual messages to avoid token blowup
        content = msg.content
        if len(content) > 1000:
            content = content[:997] + "..."
        lines.append(f"  {prefix} {content}")
    lines.append("[End of previous conversation]")
    return "\n".join(lines)


class AgentSessionManager:
    """Manages conversation sessions for agents.

    Each (tenant_id, agent_name) pair has exactly one active session
    at a time. New messages are appended, and the recent history can
    be injected into subsequent prompts.
    """

    def __init__(self, db: Database):
        self._db = db

    # ── Public API ───────────────────────────────────────────────

    def get_or_create(self, agent_name: str,
                      tenant_id: str = "default") -> AgentSession:
        """Get the active session for (tenant, agent), or create one.

        Args:
            agent_name: Agent name.
            tenant_id: Tenant ID (default: "default").

        Returns:
            AgentSession with status 'active'.
        """
        row = self._db.fetchone(
            """SELECT * FROM agent_sessions
               WHERE tenant_id = ? AND agent_name = ? AND status = 'active'
               ORDER BY updated_at DESC LIMIT 1""",
            (tenant_id, agent_name),
        )
        if row:
            r = dict(row)
            return AgentSession(
                id=r["id"],
                agent_name=r["agent_name"],
                tenant_id=r["tenant_id"],
                status=r["status"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                context_summary=r.get("context_summary", ""),
            )

        # No active session — create one
        return self._create(agent_name, tenant_id)

    def get_paused_session(self, agent_name: str,
                           tenant_id: str = "default") -> Optional[AgentSession]:
        """Get the most recently paused session for context recovery.

        Used during RESUME to inject the summary of the paused session.

        Args:
            agent_name: Agent name.
            tenant_id: Tenant ID.

        Returns:
            The most recent paused session, or None.
        """
        row = self._db.fetchone(
            """SELECT * FROM agent_sessions
               WHERE tenant_id = ? AND agent_name = ? AND status = 'paused'
               ORDER BY updated_at DESC LIMIT 1""",
            (tenant_id, agent_name),
        )
        if not row:
            return None
        r = dict(row)
        return AgentSession(
            id=r["id"],
            agent_name=r["agent_name"],
            tenant_id=r["tenant_id"],
            status=r["status"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            context_summary=r.get("context_summary", ""),
        )

    def append_message(self, session_id: str, role: str,
                       content: str, tokens: int = 0) -> int:
        """Append a message to a session.

        Args:
            session_id: Session ID.
            role: 'user' or 'assistant'.
            content: Message text.
            tokens: Estimated token count.

        Returns:
            The message ID.
        """
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._db.execute(
            """INSERT INTO session_messages
               (session_id, role, content, tokens, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, role, content, tokens, now),
        )
        # Also update the session's updated_at timestamp
        self._db.execute(
            "UPDATE agent_sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        return cursor.lastrowid

    def get_history(self, session_id: str,
                    limit: int = _MAX_HISTORY_ROWS) -> list[Message]:
        """Get the most recent messages from a session.

        Args:
            session_id: Session ID.
            limit: Max messages to return (default: 10).

        Returns:
            List of Message objects, oldest first.
        """
        rows = self._db.fetchall(
            """SELECT * FROM session_messages
               WHERE session_id = ?
               ORDER BY id DESC LIMIT ?""",
            (session_id, limit),
        )
        # Return in chronological order (oldest first)
        result = []
        for row in reversed(rows):
            result.append(Message(
                id=row["id"],
                session_id=row["session_id"],
                role=row["role"],
                content=row["content"],
                tokens=row["tokens"],
                created_at=row["created_at"],
            ))
        return result

    def get_history_block(self, session_id: str,
                          limit: int = _MAX_HISTORY_ROWS) -> str:
        """Get formatted history block for prompt injection.

        Args:
            session_id: Session ID.
            limit: Max messages to include.

        Returns:
            Formatted text block, or empty string if no history.
        """
        messages = self.get_history(session_id, limit=limit)
        return _format_history(messages) if messages else ""

    def close_session(self, session_id: str,
                      new_status: str = "closed") -> None:
        """Close or pause a session.

        Args:
            session_id: Session ID.
            new_status: 'closed' (stop) or 'paused' (pause).
        """
        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "UPDATE agent_sessions SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, session_id),
        )

    def update_summary(self, session_id: str, summary: str) -> None:
        """Update the context summary for a session.

        Args:
            session_id: Session ID.
            summary: Short summary text.
        """
        self._db.execute(
            "UPDATE agent_sessions SET context_summary = ? WHERE id = ?",
            (summary, session_id),
        )

    def list_sessions(self, agent_name: Optional[str] = None,
                      tenant_id: str = "default",
                      status: Optional[str] = None,
                      limit: int = 20) -> list[AgentSession]:
        """List sessions, optionally filtered.

        Args:
            agent_name: Optional agent name filter.
            tenant_id: Tenant ID.
            status: Optional status filter ('active', 'closed', 'paused').
            limit: Max results.

        Returns:
            List of AgentSession objects.
        """
        where_parts = ["tenant_id = ?"]
        params: list = [tenant_id]

        if agent_name:
            where_parts.append("agent_name = ?")
            params.append(agent_name)
        if status:
            where_parts.append("status = ?")
            params.append(status)

        where = " AND ".join(where_parts)
        rows = self._db.fetchall(
            f"SELECT * FROM agent_sessions WHERE {where} ORDER BY updated_at DESC LIMIT ?",
            (*params, limit),
        )
        rows_dicts = [dict(r) for r in rows]
        return [
            AgentSession(
                id=r["id"],
                agent_name=r["agent_name"],
                tenant_id=r["tenant_id"],
                status=r["status"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                context_summary=r.get("context_summary", ""),
            )
            for r in rows_dicts
        ]

    # ── Internal ─────────────────────────────────────────────────

    def _create(self, agent_name: str, tenant_id: str) -> AgentSession:
        """Create a new active session."""
        session_id = f"ses_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            """INSERT INTO agent_sessions
               (id, agent_name, tenant_id, status, created_at, updated_at)
               VALUES (?, ?, ?, 'active', ?, ?)""",
            (session_id, agent_name, tenant_id, now, now),
        )
        return AgentSession(
            id=session_id,
            agent_name=agent_name,
            tenant_id=tenant_id,
            status="active",
            created_at=now,
            updated_at=now,
        )
