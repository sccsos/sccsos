"""Tests for KnowledgeBase persistent cache mechanism.

Covers _try_restore_cache() and _save_cache() — the JSON-serialized
index that survives process restarts and avoids full re-index on
startup when files are unchanged.

Also verifies lazy loading (_ensure_loaded) works correctly alongside
the persistent cache.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sccsos.memory.knowledge_base import KnowledgeBase


# ── Helpers ──────────────────────────────────────────────────────────


def create_wiki_file(wiki_dir: Path, name: str, content: str) -> Path:
    """Create a .md file in *wiki_dir* and return its path."""
    fpath = wiki_dir / name
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text(content, encoding="utf-8")
    return fpath


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def wiki_dir(tmp_path: Path) -> Path:
    """Temporary wiki directory owned by this test."""
    d = tmp_path / "wiki"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def cache_path(tmp_path: Path) -> Path:
    """Temporary cache file path (no default ~/. cache interference)."""
    return tmp_path / "knowledge_cache.json"


# ── Test class ───────────────────────────────────────────────────────


class TestKnowledgeBaseCache:
    """Persistent cache tests for KnowledgeBase."""

    # ── 1. Cache saved after full load ────────────────────────────

    def test_cache_saved_after_full_load(self, wiki_dir, cache_path):
        """Verify _save_cache is called after a full load."""
        create_wiki_file(wiki_dir, "hello.md", "# Hello\nWorld")
        kb = KnowledgeBase(wiki_path=wiki_dir, cache_path=cache_path)
        kb.query("Hello")  # triggers _ensure_loaded → _load_entries → _save_cache

        assert cache_path.exists()
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        assert "entries" in data
        assert "manifest" in data
        assert len(data["entries"]) == 1
        assert data["entries"][0]["title"] == "Hello"
        assert data["entries"][0]["source"] == "wiki"

    # ── 2. Cache restored on subsequent KnowledgeBase creation ────

    def test_cache_restored_on_subsequent_load(self, wiki_dir, cache_path):
        """Verify _try_restore_cache restores entries on a fresh KB."""
        create_wiki_file(wiki_dir, "persist.md", "# Persist\nCache me")

        # Round 1: full load → saves cache
        kb1 = KnowledgeBase(wiki_path=wiki_dir, cache_path=cache_path)
        kb1.query("Persist")
        assert cache_path.exists()

        # Round 2: new KB should restore from cache
        kb2 = KnowledgeBase(wiki_path=wiki_dir, cache_path=cache_path)
        kb2.query("Persist")
        assert len(kb2._entries) == 1
        assert kb2._entries[0].title == "Persist"
        assert kb2._entries[0].source == "wiki"

    # ── 3. Cache invalidated when files change (mtime) ────────────

    def test_cache_invalidated_when_file_modified(self, wiki_dir, cache_path):
        """Verify cache is skipped when a file's content + mtime changes."""
        fpath = create_wiki_file(wiki_dir, "change.md", "# Original\nold content")

        kb1 = KnowledgeBase(wiki_path=wiki_dir, cache_path=cache_path)
        kb1.query("Original")
        assert len(kb1._entries) == 1
        assert kb1._entries[0].title == "Original"

        # Modify file — write_text updates both content and mtime
        time.sleep(0.02)  # ensure distinct mtime_ns
        fpath.write_text("# Modified\nnew content", encoding="utf-8")

        # Second KB must detect the mtime mismatch and skip cache
        kb2 = KnowledgeBase(wiki_path=wiki_dir, cache_path=cache_path)
        kb2.query("Modified")
        assert len(kb2._entries) == 1
        assert kb2._entries[0].title == "Modified"

    def test_cache_invalidated_by_mtime_change_mock(self, wiki_dir, cache_path):
        """Verify cache is invalidated when mtime changes (mock-based)."""
        fpath = create_wiki_file(wiki_dir, "mtime_test.md", "# Mtime\ncontent")
        original_mtime = fpath.stat().st_mtime_ns

        # Round 1: load and cache with the original mtime
        kb1 = KnowledgeBase(wiki_path=wiki_dir, cache_path=cache_path)
        kb1.query("Mtime")
        assert cache_path.exists()

        # Round 2: mock all Path.stat() calls to return a different mtime
        # so _build_file_manifest produces a new manifest fingerprint
        original_stat = Path.stat

        def _mocked_stat(self_obj, **kwargs):
            if str(self_obj).endswith("mtime_test.md"):
                return MagicMock(st_mtime_ns=original_mtime + 9_999_999)
            return original_stat(self_obj, **kwargs)

        with patch.object(Path, "stat", _mocked_stat):
            kb2 = KnowledgeBase(wiki_path=wiki_dir, cache_path=cache_path)
            kb2.query("Mtime")
            # Cache was invalidated → entries loaded from disk
            assert len(kb2._entries) == 1
            assert kb2._entries[0].title == "Mtime"

    # ── 4. Cache invalidated when cache file doesn't exist ────────

    def test_no_cache_file_triggers_full_load(self, wiki_dir, cache_path):
        """Verify _try_restore_cache returns False when no cache file exists."""
        create_wiki_file(wiki_dir, "fresh.md", "# Fresh\nno cache yet")
        kb = KnowledgeBase(wiki_path=wiki_dir, cache_path=cache_path)

        # Before any query, no cache file exists
        assert not cache_path.exists()

        # Lazy load triggers full load (not cache restore)
        kb.query("Fresh")
        assert len(kb._entries) == 1
        # After full load, cache IS saved
        assert cache_path.exists()

    # ── 5. Empty wiki directory ───────────────────────────────────

    def test_empty_wiki_directory(self, wiki_dir, cache_path):
        """Verify empty wiki dir yields no entries and cache is still saved."""
        kb = KnowledgeBase(wiki_path=wiki_dir, cache_path=cache_path)
        kb.query("anything")
        assert len(kb._entries) == 0
        # Cache was still saved (empty entries list)
        assert cache_path.exists()
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        assert data["entries"] == []

    # ── 6. Vector store rebuild from cache ────────────────────────

    def test_vector_store_rebuild_from_cache(self, wiki_dir, cache_path):
        """Verify use_vector=True rebuilds the vector store from cache."""
        create_wiki_file(wiki_dir, "doc1.md", "# Doc One\nfirst document")
        create_wiki_file(wiki_dir, "doc2.md", "# Doc Two\nsecond document")

        # Round 1: vector store populated, cache saved
        kb1 = KnowledgeBase(
            wiki_path=wiki_dir, cache_path=cache_path, use_vector=True,
        )
        kb1.query("document")
        assert kb1._vector_store is not None
        assert kb1._vector_store.count() == 2

        # Round 2: restore from cache → rebuild vector store
        kb2 = KnowledgeBase(
            wiki_path=wiki_dir, cache_path=cache_path, use_vector=True,
        )
        kb2.query("document")
        assert kb2._vector_store is not None
        assert kb2._vector_store.count() == 2

        # Vector search should work on restored data
        results = kb2.query("first", top_k=5)
        assert len(results) >= 1
        assert any("first" in r.content for r in results)

    # ── 7. Round-trip: load → save → restore gives same entries ──

    def test_round_trip_preserves_entries(self, wiki_dir, cache_path):
        """Verify load → save → restore yields identical entry data."""
        create_wiki_file(wiki_dir, "a.md", "# Alpha\nfirst file")
        create_wiki_file(wiki_dir, "b.md", "# Beta\nsecond file")
        create_wiki_file(wiki_dir, "sub/deep.md", "# Deep\nnested file")

        kb1 = KnowledgeBase(wiki_path=wiki_dir, cache_path=cache_path)
        kb1.query("")  # trigger load

        expected = sorted(
            [(e.title, e.source, e.path, e.snippet[:50]) for e in kb1._entries],
        )

        kb2 = KnowledgeBase(wiki_path=wiki_dir, cache_path=cache_path)
        kb2.query("")

        actual = sorted(
            [(e.title, e.source, e.path, e.snippet[:50]) for e in kb2._entries],
        )

        assert expected == actual

    # ── 8. reload() clears cache ──────────────────────────────────

    def test_reload_clears_and_refreshes(self, wiki_dir, cache_path):
        """Verify reload() picks up changes and saves a fresh cache."""
        fpath = create_wiki_file(wiki_dir, "reload.md", "# Before\nold content")

        kb = KnowledgeBase(wiki_path=wiki_dir, cache_path=cache_path)
        kb.query("Before")
        assert len(kb._entries) == 1
        assert kb._entries[0].title == "Before"

        # Change file
        time.sleep(0.02)
        fpath.write_text("# After\nnew content", encoding="utf-8")

        # reload() should detect the change and re-save cache
        kb.reload()
        assert len(kb._entries) == 1
        assert kb._entries[0].title == "After"

        # Cache file should contain the new state
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        assert data["entries"][0]["title"] == "After"

    # ── 9. Cache file corruption / exception safety ───────────────

    def test_corrupt_cache_falls_back_to_full_load(self, wiki_dir, cache_path):
        """Verify a corrupt cache JSON falls back to full load."""
        create_wiki_file(wiki_dir, "robust.md", "# Robust\nfallback test")

        # Write garbage to cache file
        cache_path.write_text("{{{ not json", encoding="utf-8")

        kb = KnowledgeBase(wiki_path=wiki_dir, cache_path=cache_path)
        kb.query("Robust")
        # Should have loaded from disk despite corrupt cache
        assert len(kb._entries) == 1
        assert kb._entries[0].title == "Robust"

        # Corrupt cache should have been overwritten on save
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        assert len(data["entries"]) == 1

    # ── 10. TTL expiry vs cache behavior ──────────────────────────

    def test_ttl_expiry_still_uses_cache_if_no_changes(self, wiki_dir, cache_path):
        """Verify TTL expiry does NOT invalidate the persistent cache.

        TTL expiry only triggers _scan_changed_files; if nothing changed
        the cache manifest still matches and _try_restore_cache works.
        """
        create_wiki_file(wiki_dir, "ttl.md", "# TTL\nstill cached")

        kb1 = KnowledgeBase(
            wiki_path=wiki_dir, cache_path=cache_path, ttl_seconds=0,
        )
        kb1.query("TTL")
        assert len(kb1._entries) == 1

        # With ttl_seconds=0, the TTL is already expired on next access,
        # but since no files changed, the cache should still be used
        # on a fresh KnowledgeBase.
        kb2 = KnowledgeBase(
            wiki_path=wiki_dir, cache_path=cache_path, ttl_seconds=0,
        )
        kb2.query("TTL")
        assert len(kb2._entries) == 1
        assert kb2._entries[0].title == "TTL"

    # ── 11. Manifest stores relative paths correctly ──────────────

    def test_manifest_uses_relative_paths(self, wiki_dir, cache_path):
        """Verify manifest keys are relative to wiki_path.parent."""
        create_wiki_file(wiki_dir, "flat.md", "# Flat\nroot level")
        create_wiki_file(wiki_dir, "nested/deep.md", "# Deep\nnested level")

        kb = KnowledgeBase(wiki_path=wiki_dir, cache_path=cache_path)
        kb.query("anything")

        data = json.loads(cache_path.read_text(encoding="utf-8"))
        for key in data["manifest"]:
            # Keys should not be absolute paths
            assert not os.path.isabs(key), f"Manifest key is absolute: {key}"
            # Keys should include the wiki directory name
            assert "wiki/" in key, f"Manifest key missing wiki dir: {key}"

    # ── 12. _try_restore_cache returns False explicitly ───────────

    def test_try_restore_cache_returns_false_on_mismatch(self, wiki_dir, cache_path):
        """_try_restore_cache returns False when manifest doesn't match."""
        fpath = create_wiki_file(wiki_dir, "match.md", "# Match\ncheck")

        kb1 = KnowledgeBase(wiki_path=wiki_dir, cache_path=cache_path)
        kb1.query("Match")

        # Change file to invalidate manifest
        time.sleep(0.02)
        fpath.write_text("# Changed\nnow different", encoding="utf-8")

        kb2 = KnowledgeBase(wiki_path=wiki_dir, cache_path=cache_path)
        # Directly call _try_restore_cache to check return value
        result = kb2._try_restore_cache()
        assert result is False, "Expected False when manifest mismatches"
