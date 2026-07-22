"""精准覆盖补充 — knowledge_base 和 memory_store 最后缺口。"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

from sccsos.core.db import Database
from sccsos.memory.knowledge_base import KnowledgeBase
from sccsos.memory.memory_store import MemoryStore


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def db():
    tmp = tempfile.mktemp(suffix=".db")
    database = Database(db_path=tmp)
    database.initialize()
    yield database
    database.close()
    os.unlink(tmp)


@pytest.fixture
def store(db):
    return MemoryStore(db)


def create_md_file(d: Path, name: str, content: str) -> Path:
    f = d / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f


# ═══════════════════════════════════════════════════════════════════
# KnowledgeBase 行 194-201 _ensure_loaded stale + change
# ═══════════════════════════════════════════════════════════════════


class TestKnowledgeBaseStaleRefresh:
    """覆盖 knowledge_base.py:194-201 — stale TTL with file changes."""

    def test_stale_refresh_reloads_on_change(self, tmp_path):
        """TTL expired + file changed → _load_entries(changed_only=True)."""
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        create_md_file(wiki_dir, "hello.md", "# Hello World")
        kb = KnowledgeBase(wiki_path=wiki_dir, ttl_seconds=0, use_vector=False)
        # Force initial load
        entries = kb.query("Hello")
        assert len(entries) >= 1
        # Add a new file
        time.sleep(0.02)
        create_md_file(wiki_dir, "new.md", "# New Content")
        # Query again — TTL=0 triggers stale refresh
        entries2 = kb.query("New")
        # Should find the new file content
        found = [e for e in entries2 if "New Content" in e.content]
        assert len(found) >= 1

    def test_stale_refresh_no_change_just_refreshes_manifest(self, tmp_path):
        """TTL expired + no file changes → just refresh manifest + save cache."""
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        create_md_file(wiki_dir, "stable.md", "# Stable Document")
        kb = KnowledgeBase(wiki_path=wiki_dir, ttl_seconds=0, use_vector=False)
        # First load
        kb.query("Stable")
        # Second query — TTL=0, no changes, should refresh manifest
        entries = kb.query("Stable")
        assert len(entries) == 1


# ═══════════════════════════════════════════════════════════════════
# MemoryStore 行 136-137, 155-160
# ═══════════════════════════════════════════════════════════════════


class TestMemoryStoreFinalCov:
    """覆盖 memory_store.py:136-137 list_keys TTL edge, 155-160 clear."""

    def test_list_keys_ttl_zero_edge(self, store):
        """TTL=0 entries survive TTL check in list_keys (edge case)."""
        from datetime import datetime, timezone
        past = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        store.save("agent-a", "edge-key", "value", ttl_seconds=0)
        store._db.execute(
            "UPDATE memory_store SET updated_at = ? WHERE key = ?",
            (past, "edge-key"),
        )
        store._db.commit()
        keys = store.list_keys("agent-a")
        assert "edge-key" in keys  # TTL=0 means no expiry regardless of age

    def test_clear_tenant_default_tenant(self, store):
        """clear_tenant with default tenant_id deletes entries."""
        store.save("agent-a", "k1", "v1")
        count = store.clear_tenant()
        assert count >= 1
        assert store.list_keys("agent-a") == []

    def test_clear_agent_specific_tenant(self, db):
        """clear_agent with custom tenant_id works."""
        store = MemoryStore(db)
        store.save("agent-a", "k1", "v1", tenant_id="custom")
        count = store.clear_agent("agent-a", tenant_id="custom")
        assert count >= 1
        assert store.list_keys("agent-a", tenant_id="custom") == []
