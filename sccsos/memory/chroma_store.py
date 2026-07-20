"""ChromaDB vector store backend for SCCS OS.

Implements ``VectorStoreABC`` using ChromaDB — a lightweight,
embedding-native vector database. Supports persistent storage
and various embedding functions.

Requires ``sccsos[chroma]`` extras::

    pip install sccsos[chroma]

Usage::

    from sccsos.memory.chroma_store import ChromaVectorStore

    store = ChromaVectorStore(
        collection_name="sccsos_kb",
        persist_directory="./data/chroma",
    )
    store.add_document("doc1", "SCCS OS agent lifecycle states")
    results = store.search("agent lifecycle", top_k=5)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sccsos.memory.base import VectorStoreABC

logger = logging.getLogger("sccsos.memory.chroma")


class ChromaVectorStore(VectorStoreABC):
    """ChromaDB vector store with configurable embedding.

    Args:
        collection_name: Chroma collection name (default ``"sccsos_kb"``).
        persist_directory: Directory for persistent storage. When ``None``,
            runs in-memory only (lost on restart).
        embedding_function: Chroma embedding function. When ``None``, uses
            Chroma's default ONNX-based embedding (no download needed).
        distance: Distance metric (default ``"cosine"``).
    """

    def __init__(
        self,
        collection_name: str = "sccsos_kb",
        persist_directory: Optional[str] = None,
        embedding_function: Optional[Any] = None,
        distance: str = "cosine",
    ):
        self._collection_name = collection_name
        self._persist_directory = persist_directory
        self._distance = distance
        self._collection: Any = None
        self._client: Any = None

        # Lazy-init embedding function
        if embedding_function is None:
            try:
                from chromadb.utils import embedding_functions

                # Use default ONNX embedding (lightweight, no model download)
                self._embedding_fn = (
                    embedding_functions.DefaultEmbeddingFunction()
                )
                logger.info(
                    "ChromaVectorStore: using DefaultEmbeddingFunction (ONNX)"
                )
            except Exception as e:
                logger.warning(
                    "DefaultEmbeddingFunction unavailable (%s), "
                    "using no-op embedding — pass explicit embedding_function",
                    e,
                )
                self._embedding_fn = None
        else:
            self._embedding_fn = embedding_function

    # ── Lazy client and collection ─────────────────────────────

    @property
    def client(self) -> Any:
        """Get or create the Chroma client."""
        if self._client is None:
            import chromadb

            if self._persist_directory:
                self._client = chromadb.PersistentClient(
                    path=self._persist_directory
                )
                logger.info(
                    "ChromaVectorStore: persistent client at '%s'",
                    self._persist_directory,
                )
            else:
                self._client = chromadb.EphemeralClient()
                logger.info("ChromaVectorStore: ephemeral (in-memory) client")
        return self._client

    @property
    def collection(self) -> Any:
        """Get or create the Chroma collection."""
        if self._collection is None:
            kwargs: dict[str, Any] = {
                "name": self._collection_name,
                "metadata": {"hnsw:space": self._distance},
            }
            if self._embedding_fn is not None:
                kwargs["embedding_function"] = self._embedding_fn

            # Get or create
            try:
                self._collection = self.client.get_collection(
                    name=self._collection_name
                )
                logger.debug(
                    "ChromaVectorStore: using existing collection '%s'",
                    self._collection_name,
                )
            except Exception:
                self._collection = self.client.create_collection(**kwargs)
                logger.info(
                    "ChromaVectorStore: created collection '%s'",
                    self._collection_name,
                )
        return self._collection

    # ── Document management ────────────────────────────────────

    def add_document(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[dict] = None,
    ) -> str:
        """Add or update a document in Chroma.

        If a document with the same ``doc_id`` already exists, it is
        upserted (replaced).
        """
        coll = self.collection
        meta = {k: str(v) for k, v in (metadata or {}).items()}
        try:
            # Upsert: update if exists, insert if not
            coll.upsert(
                ids=[doc_id],
                documents=[text],
                metadatas=[meta] if meta else None,
            )
            logger.debug("ChromaVectorStore: upserted document '%s'", doc_id)
        except Exception as e:
            logger.error(
                "ChromaVectorStore: failed to upsert '%s': %s", doc_id, e
            )
            raise
        return doc_id

    def remove_document(self, doc_id: str) -> None:
        """Remove a document by its ID."""
        try:
            self.collection.delete(ids=[doc_id])
            logger.debug("ChromaVectorStore: deleted document '%s'", doc_id)
        except Exception as e:
            logger.warning(
                "ChromaVectorStore: failed to delete '%s': %s", doc_id, e
            )

    def get_document(self, doc_id: str) -> Optional[dict]:
        """Retrieve a document entry by ID.

        Returns:
            A dict with keys ``id``, ``document``, ``metadata``,
            or ``None`` if not found.
        """
        try:
            result = self.collection.get(ids=[doc_id])
            if result and result["ids"]:
                return {
                    "id": result["ids"][0],
                    "document": result["documents"][0] if result.get("documents") else "",
                    "metadata": result["metadatas"][0] if result.get("metadatas") else {},
                }
        except Exception:
            pass
        return None

    def count(self) -> int:
        """Return the number of documents in the collection."""
        try:
            return self.collection.count()
        except Exception:
            return 0

    def clear(self) -> None:
        """Remove all documents from the collection."""
        try:
            # Get all IDs then delete
            all_items = self.collection.get()
            if all_items and all_items["ids"]:
                self.collection.delete(ids=all_items["ids"])
            logger.info("ChromaVectorStore: cleared collection '%s'", self._collection_name)
        except Exception as e:
            logger.warning("ChromaVectorStore: failed to clear: %s", e)

    # ── Search ─────────────────────────────────────────────────

    def search(
        self, query: str, top_k: int = 5
    ) -> list[tuple[str, float]]:
        """Search documents by semantic similarity.

        Returns:
            List of ``(doc_id, score)`` tuples, sorted by score descending.

        Note:
            Chroma returns distance (not similarity) when using cosine.
            We invert the score so higher = more relevant, matching the
            ``VectorStoreABC`` contract.
        """
        if not query.strip():
            return []

        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=min(top_k, self.count() or top_k),
            )
            if not results or not results["ids"] or not results["ids"][0]:
                return []

            ids = results["ids"][0]
            distances = results["distances"][0] if results.get("distances") else []

            # Invert: Chroma cosine distance (0=identical, 2=opposite)
            # Convert to similarity: sim = 1 - (dist / 2)
            scored = []
            for i, doc_id in enumerate(ids):
                if i < len(distances):
                    sim = 1.0 - (distances[i] / 2.0)
                else:
                    sim = 0.0
                scored.append((doc_id, round(sim, 4)))

            return scored

        except Exception as e:
            logger.error("ChromaVectorStore: search failed: %s", e)
            return []

    def search_with_snippets(
        self, query: str, top_k: int = 5
    ) -> list[tuple[str, float, str]]:
        """Search and return ``(doc_id, score, snippet)`` tuples."""
        if not query.strip():
            return []

        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=min(top_k, self.count() or top_k),
                include=["documents", "distances", "metadatas"],
            )
            if not results or not results.get("ids") or not results["ids"]:
                return []

            ids = results["ids"][0]
            docs = results["documents"][0] if results.get("documents") else []
            distances = results["distances"][0] if results.get("distances") else []

            snippets = []
            for i, doc_id in enumerate(ids):
                sim = 1.0 - (distances[i] / 2.0) if i < len(distances) else 0.0
                text = docs[i] if i < len(docs) else ""
                snippet = (text[:200] + "...") if len(text) > 200 else text
                snippets.append((doc_id, round(sim, 4), snippet))

            return snippets

        except Exception as e:
            logger.error("ChromaVectorStore: search_with_snippets failed: %s", e)
            return []


# ── Factory helper ────────────────────────────────────────────────


def create_vector_store(
    backend: str = "tfidf",
    **kwargs: Any,
) -> VectorStoreABC:
    """Create a vector store backend.

    Args:
        backend: ``"tfidf"`` (default), ``"chroma"``, or ``"chroma-persistent"``.
        **kwargs: Passed to the backend constructor.

    Returns:
        A ``VectorStoreABC`` instance.

    Examples::

        # TF-IDF (default, no external deps)
        store = create_vector_store("tfidf")

        # Chroma ephemeral (in-memory)
        store = create_vector_store("chroma", collection_name="dev")

        # Chroma persistent
        store = create_vector_store(
            "chroma-persistent",
            collection_name="prod",
            persist_directory="./data/chroma",
        )
    """
    if backend == "chroma":
        from sccsos.memory.chroma_store import ChromaVectorStore

        return ChromaVectorStore(**kwargs)

    if backend == "chroma-persistent":
        from sccsos.memory.chroma_store import ChromaVectorStore

        kwargs.setdefault("persist_directory", "./data/chroma")
        return ChromaVectorStore(**kwargs)

    # Default: TF-IDF
    from sccsos.memory.vector_store import TFIDFVectorStore

    return TFIDFVectorStore(**kwargs)
