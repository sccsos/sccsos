"""Tests for KnowledgeBase _scan_changed_files — file change detection."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sccsos.memory.knowledge_base import KnowledgeBase


@pytest.fixture
def wiki_dir(tmp_path: Path) -> Path:
    d = tmp_path / "wiki"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_wiki_file(wiki_dir: Path, name: str, content: str) -> Path:
    fpath = wiki_dir / name
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text(content, encoding="utf-8")
    return fpath


class TestKnowledgeBaseScanChanged:
    """Coverage for _scan_changed_files — new, modified, deleted files."""

    def test_scan_detects_new_file(self, wiki_dir):
        """A file added after initial load should appear as changed."""
        create_wiki_file(wiki_dir, "existing.md", "# Existing")
        kb = KnowledgeBase(wiki_path=wiki_dir, use_vector=False)
        kb._ensure_loaded()

        # Add a new file
        create_wiki_file(wiki_dir, "new.md", "# New content")
        changed = kb._scan_changed_files()
        assert len(changed) >= 1
        assert any("new.md" in str(p) for p in changed)

    def test_scan_detects_modified_file(self, wiki_dir):
        """A file whose mtime changed after initial load should appear as changed."""
        fpath = create_wiki_file(wiki_dir, "modify.md", "# Original")
        kb = KnowledgeBase(wiki_path=wiki_dir, use_vector=False)
        kb._ensure_loaded()

        # Modify the file
        time.sleep(0.02)  # Ensure mtime changes
        fpath.write_text("# Modified")
        changed = kb._scan_changed_files()
        assert len(changed) >= 1
        assert any("modify.md" in str(p) for p in changed)

    def test_scan_handles_deleted_file(self, wiki_dir):
        """A file deleted after initial load should be removed from entries."""
        fpath = create_wiki_file(wiki_dir, "deleteme.md", "# To be deleted")
        kb = KnowledgeBase(wiki_path=wiki_dir, use_vector=False)
        kb._ensure_loaded()

        # Record initial entry count
        initial_count = len(kb._entries)

        # Delete the file
        fpath.unlink()
        changed = kb._scan_changed_files()

        # Entries should have been cleaned up
        assert len(kb._entries) < initial_count
        assert not any("deleteme.md" in str(e.path) for e in kb._entries)

    def test_scan_no_changes_returns_empty(self, wiki_dir):
        """When no files changed, _scan_changed_files should return []."""
        create_wiki_file(wiki_dir, "stable.md", "# Stable")
        kb = KnowledgeBase(wiki_path=wiki_dir, use_vector=False)
        kb._ensure_loaded()
        changed = kb._scan_changed_files()
        assert len(changed) == 0
