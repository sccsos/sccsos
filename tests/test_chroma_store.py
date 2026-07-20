"""Tests for ChromaDB vector store backend.

Tests use mocking to avoid requiring a real ChromaDB installation.
Integration tests (``test_chroma_integration``) are gated on
``sccsos[chroma]`` being installed.
"""

from __future__ import annotations

import sys
from unittest import mock

import pytest
from sccsos.memory.base import VectorStoreABC
from sccsos.memory.chroma_store import (
    ChromaVectorStore,
    create_vector_store,
)


class TestChromaVectorStoreUnit:
    """Unit tests with mocked ChromaDB client."""

    @pytest.fixture
    def mock_chromadb(self):
        """Mock the entire chromadb module."""
        mock_module = mock.MagicMock()

        # Mock collection
        mock_collection = mock.MagicMock()
        mock_collection.count.return_value = 3
        mock_collection.get.return_value = {
            "ids": ["doc1", "doc2"],
            "documents": ["text a", "text b"],
            "metadatas": [{"k": "v1"}, {"k": "v2"}],
        }
        mock_collection.query.return_value = {
            "ids": [["doc3", "doc1"]],
            "documents": [["result text", "another doc"]],
            "distances": [[0.1, 0.3]],
            "metadatas": [[{"s": "t"}, {"u": "v"}]],
        }

        # Mock client — get_collection raises so create_collection is called
        mock_client = mock.MagicMock()
        mock_client.get_collection.side_effect = ValueError("not found")
        mock_client.create_collection.return_value = mock_collection

        # Mock PersistentClient and EphemeralClient
        mock_module.PersistentClient.return_value = mock_client
        mock_module.EphemeralClient.return_value = mock_client

        # Mock embedding functions
        mock_ef = mock.MagicMock()
        mock_module.utils = mock.MagicMock()
        mock_module.utils.embedding_functions = mock.MagicMock()
        mock_module.utils.embedding_functions.DefaultEmbeddingFunction.return_value = (
            mock_ef
        )

        with mock.patch.dict(
            sys.modules,
            {
                "chromadb": mock_module,
                "chromadb.utils": mock_module.utils,
                "chromadb.utils.embedding_functions": mock_module.utils.embedding_functions,
            },
        ):
            yield mock_module, mock_client, mock_collection

    def test_init_ephemeral(self, mock_chromadb):
        """Default init creates ephemeral client."""
        mock_module, mock_client, _ = mock_chromadb
        store = ChromaVectorStore(collection_name="test_coll")

        # Access collection to trigger lazy init
        _ = store.collection

        mock_module.EphemeralClient.assert_called_once()
        mock_client.create_collection.assert_called_once()

    def test_init_persistent(self, mock_chromadb):
        """Persistent directory uses PersistentClient."""
        mock_module, mock_client, _ = mock_chromadb
        store = ChromaVectorStore(
            collection_name="prod", persist_directory="/tmp/chroma"
        )

        _ = store.collection

        mock_module.PersistentClient.assert_called_once_with(
            path="/tmp/chroma"
        )

    def test_add_document(self, mock_chromadb):
        """add_document delegates to collection.upsert."""
        _, _, mock_collection = mock_chromadb
        store = ChromaVectorStore()

        store.add_document("doc_x", "Some content", metadata={"lang": "en"})

        mock_collection.upsert.assert_called_once()
        args, kwargs = mock_collection.upsert.call_args
        assert kwargs["ids"] == ["doc_x"]
        assert kwargs["documents"] == ["Some content"]

    def test_remove_document(self, mock_chromadb):
        """remove_document delegates to collection.delete."""
        _, _, mock_collection = mock_chromadb
        store = ChromaVectorStore()

        store.remove_document("doc_x")

        mock_collection.delete.assert_called_once_with(ids=["doc_x"])

    def test_get_document(self, mock_chromadb):
        """get_document returns a dict with id/doc/metadata."""
        _, _, mock_collection = mock_chromadb
        store = ChromaVectorStore()

        result = store.get_document("doc1")

        assert result is not None
        assert result["id"] == "doc1"
        assert result["document"] == "text a"
        assert result["metadata"] == {"k": "v1"}
        mock_collection.get.assert_called_once_with(ids=["doc1"])

    def test_get_document_missing(self, mock_chromadb):
        """get_document returns None for unknown ID."""
        _, _, mock_collection = mock_chromadb
        mock_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        store = ChromaVectorStore()

        result = store.get_document("nonexistent")

        assert result is None

    def test_count(self, mock_chromadb):
        """count returns collection.count()."""
        _, _, mock_collection = mock_chromadb
        store = ChromaVectorStore()

        assert store.count() == 3

    def test_clear(self, mock_chromadb):
        """clear gets all IDs then deletes them."""
        _, _, mock_collection = mock_chromadb
        store = ChromaVectorStore()

        store.clear()

        mock_collection.get.assert_called_once()
        mock_collection.delete.assert_called_once_with(ids=["doc1", "doc2"])

    def test_search(self, mock_chromadb):
        """search returns (doc_id, score) sorted by score desc."""
        _, _, mock_collection = mock_chromadb
        store = ChromaVectorStore()

        results = store.search("find something", top_k=2)

        # scores: 1 - (0.1/2) = 0.95, 1 - (0.3/2) = 0.85
        assert len(results) == 2
        assert results[0][0] == "doc3"
        assert results[0][1] > results[1][1]

    def test_implements_abc(self):
        """ChromaVectorStore implements VectorStoreABC."""
        assert issubclass(ChromaVectorStore, VectorStoreABC)


class TestCreateVectorStore:
    """Test the create_vector_store factory."""

    def test_default_is_tfidf(self):
        """Default backend creates TFIDFVectorStore."""
        from sccsos.memory.vector_store import TFIDFVectorStore

        store = create_vector_store()
        assert isinstance(store, TFIDFVectorStore)

    def test_chroma_backend(self):
        """chroma backend creates ChromaVectorStore."""
        store = create_vector_store("chroma", collection_name="test")
        assert isinstance(store, ChromaVectorStore)

    def test_chroma_persistent_backend(self):
        """chroma-persistent sets default persist_directory."""
        store = create_vector_store("chroma-persistent")
        assert isinstance(store, ChromaVectorStore)
        assert store._persist_directory == "./data/chroma"

    def test_tfidf_with_params(self):
        """tfidf backend passes kwargs."""
        from sccsos.memory.vector_store import TFIDFVectorStore

        store = create_vector_store("tfidf", min_token_length=3)
        assert isinstance(store, TFIDFVectorStore)
        assert store._min_token == 3
