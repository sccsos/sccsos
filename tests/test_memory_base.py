"""Tests for VectorStoreABC abstract base class.

Covers concrete methods (get_document, count, search_with_snippets)
and verifies that abstract methods raise TypeError when instantiated
directly.
"""
from __future__ import annotations

import pytest

from sccsos.memory.base import VectorStoreABC


def test_cannot_instantiate_abc():
    """VectorStoreABC cannot be instantiated directly (has abstract methods)."""
    with pytest.raises(TypeError):
        VectorStoreABC()  # type: ignore[abstract]


class TestVectorStoreABCConcreteDefaults:
    """Verify that concrete default methods on VectorStoreABC work correctly."""

    @pytest.fixture
    def store(self):
        """A minimal concrete implementation for testing default methods."""
        class MinimalStore(VectorStoreABC):
            def add_document(self, doc_id, text, metadata=None):
                if not hasattr(self, '_docs'):
                    self._docs = {}
                self._docs[doc_id] = {"text": text, "metadata": metadata or {}}
                return doc_id

            def remove_document(self, doc_id):
                docs = getattr(self, '_docs', {})
                docs.pop(doc_id, None)

            def clear(self):
                self._docs = {}

            def search(self, query, top_k=5):
                docs = getattr(self, '_docs', {})
                return [(did, 1.0) for did in list(docs.keys())[:top_k]]

            def get_document(self, doc_id):
                docs = getattr(self, '_docs', {})
                entry = docs.get(doc_id)
                if entry is None:
                    return None
                return type("Doc", (), {"text": entry["text"]})()

            def count(self):
                return len(self._docs)

        return MinimalStore()

    def test_get_document_none_by_default(self):
        """Default get_document returns None for unknown ID."""
        class BareMinimum(VectorStoreABC):
            def add_document(self, doc_id, text, metadata=None): return doc_id
            def remove_document(self, doc_id): pass
            def clear(self): pass
            def search(self, query, top_k=5): return []

        bm = BareMinimum()
        bm.add_document("d1", "some text")
        # Default get_document returns None regardless
        assert bm.get_document("d1") is None

    def test_count_zero_by_default(self):
        """Default count returns 0."""
        class BareMinimum(VectorStoreABC):
            def add_document(self, doc_id, text, metadata=None): return doc_id
            def remove_document(self, doc_id): pass
            def clear(self): pass
            def search(self, query, top_k=5): return []

        bm = BareMinimum()
        assert bm.count() == 0

    def test_search_with_snippets_default_implementation(self, store):
        """Default search_with_snippets delegates to search() + get_document()."""
        store.add_document("d1", "The quick brown fox")
        store.add_document("d2", "Jumping over the lazy dog")

        results = store.search_with_snippets("fox", top_k=2)
        assert len(results) == 2
        for doc_id, score, snippet in results:
            assert isinstance(doc_id, str)
            assert isinstance(score, float)
            assert isinstance(snippet, str)
            assert len(snippet) > 0

    def test_search_with_snippets_empty_store(self, store):
        """Empty store returns empty list."""
        assert store.search_with_snippets("anything") == []

    def test_search_with_snippets_truncates_long_text(self, store):
        """Snippets longer than 200 chars are truncated."""
        long_text = "A" * 500
        store.add_document("long", long_text)
        results = store.search_with_snippets("A", top_k=1)
        assert len(results) == 1
        _, _, snippet = results[0]
        assert len(snippet) <= 203  # 200 + "..."

    def test_get_document_returns_after_search(self, store):
        """get_document retrieves what was added."""
        store.add_document("test", "content", {"key": "val"})
        doc = store.get_document("test")
        assert doc is not None
        assert hasattr(doc, "text")
        # Default get_document in our minimal store returns the text
        assert doc.text == "content"

    def test_remove_document(self, store):
        """Removed documents no longer appear in search results."""
        store.add_document("d1", "first")
        store.add_document("d2", "second")
        assert len(store.search("second")) == 2
        store.remove_document("d2")
        results = store.search("second")
        assert len(results) == 1
        assert results[0][0] == "d1"

    def test_clear_removes_all(self, store):
        """Cleared store returns empty search results."""
        store.add_document("d1", "first")
        store.add_document("d2", "second")
        store.clear()
        assert store.count() == 0
        assert store.search("anything") == []

    def test_add_document_returns_id(self, store):
        """add_document returns the document ID."""
        doc_id = store.add_document("my_doc", "hello world")
        assert doc_id == "my_doc"
