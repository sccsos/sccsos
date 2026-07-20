"""Memory Store — cross-session persistent key-value memory for agents.

Provides per-tenant, per-agent persistent storage for user preferences,
session data, and learned facts. Unlike KnowledgeBase (read-only wiki),
MemoryStore supports read-write operations.

Supports optional TTL (time-to-live) expiration: entries older than
their ttl_seconds are treated as expired and auto-deleted on read.

Usage:
    store = MemoryStore(db)
    store.save("architect", "preferred_language", "Python", tenant_id="t1")
    val = store.get("architect", "preferred_language", tenant_id="t1")
    all_keys = store.list_keys("architect", tenant_id="t1")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sccsos.core.db import Database


class MemoryStore:
    """Persistent key-value memory store per tenant/agent.

    Data is stored in the ``memory_store`` SQLite table with
    UNIQUE constraint on (tenant_id, agent_name, key).

    Supports optional TTL: entries with ``ttl_seconds > 0``
    expire that many seconds after ``updated_at``.
    """

    def __init__(self, db: Database, default_ttl_seconds: int = 0):
        self._db = db
        self._default_ttl = default_ttl_seconds

    # ── Public API ───────────────────────────────────────────────

    def save(self, agent_name: str, key: str, value: str,
             tenant_id: str = "default",
             ttl_seconds: Optional[int] = None) -> None:
        """Save or update a memory entry.

        Uses INSERT OR REPLACE to handle both create and update.

        Args:
            agent_name: Agent name.
            key: Memory key.
            value: Memory value.
            tenant_id: Tenant ID (default: "default").
            ttl_seconds: Time-to-live in seconds. 0 = no expiry.
                Defaults to the store's ``default_ttl_seconds``.
        """
        now = datetime.now(timezone.utc).isoformat()
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        self._db.execute(
            """INSERT OR REPLACE INTO memory_store
               (tenant_id, agent_name, key, value, updated_at, ttl_seconds)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tenant_id, agent_name, key, value, now, ttl),
        )
        self._db.commit()

    def get(self, agent_name: str, key: str,
            tenant_id: str = "default") -> Optional[str]:
        """Retrieve a memory entry by key.

        Returns None if the key is not found or has expired (TTL check).

        Args:
            agent_name: Agent name.
            key: Memory key.
            tenant_id: Tenant ID (default: "default").

        Returns:
            The value string, or None if not found or expired.
        """
        row = self._db.fetchone(
            """SELECT value, updated_at, ttl_seconds FROM memory_store
               WHERE tenant_id = ? AND agent_name = ? AND key = ?
               ORDER BY updated_at DESC LIMIT 1""",
            (tenant_id, agent_name, key),
        )
        if not row:
            return None

        value, updated_at, ttl = row
        if ttl and ttl > 0 and updated_at:
            try:
                updated = datetime.fromisoformat(updated_at)
                age = (datetime.now(timezone.utc) - updated).total_seconds()
                if age > ttl:
                    # Entry expired — delete and return None
                    self._db.execute(
                        """DELETE FROM memory_store
                           WHERE tenant_id = ? AND agent_name = ? AND key = ?""",
                        (tenant_id, agent_name, key),
                    )
                    self._db.commit()
                    return None
            except (ValueError, TypeError):
                pass  # Can't parse timestamp — treat as still valid
        return value

    def delete(self, agent_name: str, key: str,
               tenant_id: str = "default") -> bool:
        """Delete a memory entry. Returns True if deleted."""
        cursor = self._db.execute(
            """DELETE FROM memory_store
               WHERE tenant_id = ? AND agent_name = ? AND key = ?""",
            (tenant_id, agent_name, key),
        )
        self._db.commit()
        return cursor.rowcount > 0

    def list_keys(self, agent_name: str,
                  tenant_id: str = "default") -> list[str]:
        """List all non-expired memory keys for an agent in a tenant."""
        rows = self._db.fetchall(
            """SELECT key, updated_at, ttl_seconds FROM memory_store
               WHERE tenant_id = ? AND agent_name = ?
               ORDER BY updated_at DESC""",
            (tenant_id, agent_name),
        )
        now = datetime.now(timezone.utc)
        valid_keys = []
        for r in rows:
            key, updated_at, ttl = r
            if ttl and ttl > 0 and updated_at:
                try:
                    updated = datetime.fromisoformat(updated_at)
                    if (now - updated).total_seconds() > ttl:
                        continue  # Skip expired
                except (ValueError, TypeError):
                    pass
            valid_keys.append(key)
        return valid_keys

    def get_all(self, agent_name: str,
                tenant_id: str = "default") -> dict[str, str]:
        """Retrieve all non-expired memory entries for an agent as a dict."""
        rows = self._db.fetchall(
            """SELECT key, value, updated_at, ttl_seconds FROM memory_store
               WHERE tenant_id = ? AND agent_name = ?
               ORDER BY key""",
            (tenant_id, agent_name),
        )
        now = datetime.now(timezone.utc)
        result = {}
        for r in rows:
            key, value, updated_at, ttl = r
            if ttl and ttl > 0 and updated_at:
                try:
                    updated = datetime.fromisoformat(updated_at)
                    if (now - updated).total_seconds() > ttl:
                        continue
                except (ValueError, TypeError):
                    pass
            result[key] = value
        return result

    def clear_agent(self, agent_name: str,
                    tenant_id: str = "default") -> int:
        """Clear all memory for an agent. Returns count of deleted entries."""
        cursor = self._db.execute(
            """DELETE FROM memory_store
               WHERE tenant_id = ? AND agent_name = ?""",
            (tenant_id, agent_name),
        )
        self._db.commit()
        return cursor.rowcount

    def clear_tenant(self, tenant_id: str = "default") -> int:
        """Clear all memory for a tenant. Use with caution."""
        cursor = self._db.execute(
            "DELETE FROM memory_store WHERE tenant_id = ?",
            (tenant_id,),
        )
        self._db.commit()
        return cursor.rowcount

    def purge_expired(self) -> int:
        """Delete all expired memory entries across all tenants.

        Removes entries where ``ttl_seconds > 0`` and the elapsed time
        since ``updated_at`` exceeds ``ttl_seconds``. Safe to call
        periodically — does not affect entries without TTL.

        Returns:
            Number of expired entries purged.
        """
        cursor = self._db.execute(
            """DELETE FROM memory_store
               WHERE ttl_seconds > 0
                 AND datetime(updated_at, '+' || ttl_seconds || ' seconds') < datetime('now')"""
        )
        self._db.commit()
        return cursor.rowcount
