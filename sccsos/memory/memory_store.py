"""Memory Store — cross-session persistent key-value memory for agents.

Provides per-tenant, per-agent persistent storage for user preferences,
session data, and learned facts. Unlike KnowledgeBase (read-only wiki),
MemoryStore supports read-write operations.

Usage:
    store = MemoryStore(db)
    store.save("architect", "preferred_language", "Python", tenant_id="t1")
    val = store.get("architect", "preferred_language", tenant_id="t1")
    all_keys = store.list_keys("architect", tenant_id="t1")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sccsos.core.database import Database


class MemoryStore:
    """Persistent key-value memory store per tenant/agent.

    Data is stored in the ``memory_store`` SQLite table with
    UNIQUE constraint on (tenant_id, agent_name, key).
    """

    def __init__(self, db: Database):
        self._db = db

    # ── Public API ───────────────────────────────────────────────

    def save(self, agent_name: str, key: str, value: str,
             tenant_id: str = "default") -> None:
        """Save or update a memory entry.

        Uses INSERT OR REPLACE to handle both create and update.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._db.get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO memory_store
               (tenant_id, agent_name, key, value, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (tenant_id, agent_name, key, value, now),
        )
        conn.commit()

    def get(self, agent_name: str, key: str,
            tenant_id: str = "default") -> Optional[str]:
        """Retrieve a memory entry by key. Returns None if not found."""
        conn = self._db.get_conn()
        row = conn.execute(
            """SELECT value FROM memory_store
               WHERE tenant_id = ? AND agent_name = ? AND key = ?
               ORDER BY updated_at DESC LIMIT 1""",
            (tenant_id, agent_name, key),
        ).fetchone()
        return row[0] if row else None

    def delete(self, agent_name: str, key: str,
               tenant_id: str = "default") -> bool:
        """Delete a memory entry. Returns True if deleted."""
        conn = self._db.get_conn()
        cursor = conn.execute(
            """DELETE FROM memory_store
               WHERE tenant_id = ? AND agent_name = ? AND key = ?""",
            (tenant_id, agent_name, key),
        )
        conn.commit()
        return cursor.rowcount > 0

    def list_keys(self, agent_name: str,
                  tenant_id: str = "default") -> list[str]:
        """List all keys for an agent in a tenant."""
        conn = self._db.get_conn()
        rows = conn.execute(
            """SELECT key FROM memory_store
               WHERE tenant_id = ? AND agent_name = ?
               ORDER BY updated_at DESC""",
            (tenant_id, agent_name),
        ).fetchall()
        return [r[0] for r in rows]

    def get_all(self, agent_name: str,
                tenant_id: str = "default") -> dict[str, str]:
        """Retrieve all memory entries for an agent as a dict."""
        conn = self._db.get_conn()
        rows = conn.execute(
            """SELECT key, value FROM memory_store
               WHERE tenant_id = ? AND agent_name = ?
               ORDER BY key""",
            (tenant_id, agent_name),
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def clear_agent(self, agent_name: str,
                    tenant_id: str = "default") -> int:
        """Clear all memory for an agent. Returns count of deleted entries."""
        conn = self._db.get_conn()
        cursor = conn.execute(
            """DELETE FROM memory_store
               WHERE tenant_id = ? AND agent_name = ?""",
            (tenant_id, agent_name),
        )
        conn.commit()
        return cursor.rowcount

    def clear_tenant(self, tenant_id: str = "default") -> int:
        """Clear all memory for a tenant. Use with caution."""
        conn = self._db.get_conn()
        cursor = conn.execute(
            "DELETE FROM memory_store WHERE tenant_id = ?",
            (tenant_id,),
        )
        conn.commit()
        return cursor.rowcount
