"""Abstract base class for vector store backends.

All vector store implementations must implement the ``VectorStoreABC``
interface.  This allows SCCS OS to switch between lightweight in-process
storage (TF-IDF) and external vector databases (Chroma, Milvus, Qdrant)
without changing consumer code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class VectorStoreABC(ABC):
    """Abstract vector store interface for document retrieval.

    Every method is optional at the store's discretion — a read-only
    remote backend may raise ``NotImplementedError`` for mutation
    methods — but the ABC documents the contract.
    """

    @abstractmethod
    def add_document(self, doc_id: str, text: str,
                     metadata: Optional[dict] = None) -> str:
        """Add or replace a document.

        Returns:
            The document ID (may be normalised).
        """
        ...

    @abstractmethod
    def remove_document(self, doc_id: str) -> None:
        """Remove a document by its ID."""
        ...

    def get_document(self, doc_id: str) -> Optional[object]:
        """Retrieve a document entry by ID.

        Returns:
            The implementation-specific entry object, or ``None``.
        """
        return None

    def count(self) -> int:
        """Return the number of stored documents."""
        return 0

    @abstractmethod
    def clear(self) -> None:
        """Remove all documents."""
        ...

    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        """Search documents and return ``(doc_id, score)`` tuples.

        Results must be sorted by score descending (highest first).
        """
        ...

    def search_with_snippets(self, query: str, top_k: int = 5
                             ) -> list[tuple[str, float, str]]:
        """Search and return ``(doc_id, score, snippet)`` tuples.

        Base implementation delegates to ``search()`` — override for
        more efficient snippet generation.
        """
        results = self.search(query, top_k=top_k)
        snippets = []
        for doc_id, score in results:
            entry = self.get_document(doc_id)
            text = getattr(entry, "text", str(entry or ""))
            snippet = (text[:200] + "...") if len(text) > 200 else text
            snippets.append((doc_id, score, snippet))
        return snippets
