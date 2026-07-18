"""Vector store — lightweight embedding-free semantic search.

Uses TF-IDF weighting with cosine similarity for document retrieval.
Zero external dependencies — pure Python stdlib.

Can be used standalone or as a backend for KnowledgeBase.

Usage:
    vs = VectorStore()
    vs.add_document("doc1", "The quick brown fox")
    vs.add_document("doc2", "Jumping over the lazy dog")
    results = vs.search("fox jumping", top_k=2)
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VectorEntry:
    """A document in the vector store."""
    id: str
    text: str
    tokens: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class VectorStore:
    """Lightweight vector store using TF-IDF + cosine similarity.

    Args:
        min_token_length: Minimum character length for tokens (default 2).
        stop_words: Set of words to ignore (default: English + Chinese).
    """

    DEFAULT_STOP_WORDS: set[str] = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "shall", "can",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above",
        "below", "between", "and", "but", "or", "nor", "not", "so",
        "yet", "both", "either", "neither", "each", "every", "all",
        "no", "none", "some", "any", "this", "that", "these", "those",
        "it", "its", "they", "them", "their", "we", "us", "our",
        "you", "your", "he", "him", "his", "she", "her", "i", "me",
        "my", "who", "whom", "which", "what", "when", "where", "why",
        "how", "if", "then", "else", "than", "also", "very", "just",
        "about", "up", "out", "off", "over", "again", "further",
        "once", "here", "there", "the", "的", "是", "在", "了", "和",
        "有", "不", "就", "人", "都", "一", "一个", "上", "也", "很",
        "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
        "自己", "这", "他", "她", "它", "们", "什么", "那", "为",
    }

    def __init__(self, min_token_length: int = 2,
                 stop_words: Optional[set[str]] = None):
        self._entries: dict[str, VectorEntry] = {}
        self._min_token = min_token_length
        self._stop_words = stop_words or self.DEFAULT_STOP_WORDS

    # ── Document management ────────────────────────────────────

    def add_document(self, doc_id: str, text: str,
                     metadata: Optional[dict] = None) -> str:
        """Add or update a document."""
        tokens = self._tokenize(text)
        self._entries[doc_id] = VectorEntry(
            id=doc_id,
            text=text,
            tokens=tokens,
            metadata=metadata or {},
        )
        return doc_id

    def remove_document(self, doc_id: str) -> None:
        """Remove a document by ID."""
        self._entries.pop(doc_id, None)

    def get_document(self, doc_id: str) -> Optional[VectorEntry]:
        return self._entries.get(doc_id)

    def count(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()

    # ── Search ─────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        """Search documents by cosine similarity.

        Returns:
            List of (doc_id, score) tuples, sorted by score descending.
        """
        if not self._entries or not query:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        query_tf = Counter(query_tokens)
        scores: list[tuple[str, float]] = []

        for doc_id, entry in self._entries.items():
            # Only score if the document has tokens
            if not entry.tokens:
                continue

            doc_tf = Counter(entry.tokens)
            similarity = self._cosine_similarity(query_tf, doc_tf, doc_id)
            if similarity > 0:
                scores.append((doc_id, similarity))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def search_with_snippets(self, query: str, top_k: int = 5
                             ) -> list[tuple[str, float, str]]:
        """Search and return (doc_id, score, snippet) tuples."""
        results = self.search(query, top_k=top_k)
        snippets = []
        for doc_id, score in results:
            entry = self._entries.get(doc_id)
            snippet = (entry.text[:200] + "...") if entry and len(entry.text) > 200 else (entry.text if entry else "")
            snippets.append((doc_id, score, snippet))
        return snippets

    # ── Internal ───────────────────────────────────────────────

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into lowercase tokens, filtering stop words
        and short tokens.

        Handles both English (space-split) and Chinese (char-level
        n-gram with bigram + trigram for better semantic coverage).
        """
        if not text:
            return []

        # Normalise
        text = text.lower()

        # Split on non-alphanumeric boundaries (keeps CJK characters)
        # Use regex to find word-like sequences
        raw_tokens = re.findall(r"[a-z]+|\d+", text)

        # For Chinese: add character n-grams
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
        if len(cjk_chars) >= 2:
            # Add bigrams for Chinese text (character pairs)
            bigrams = [cjk_chars[i] + cjk_chars[i + 1]
                       for i in range(len(cjk_chars) - 1)]
            raw_tokens.extend(bigrams)
        if len(cjk_chars) >= 3:
            # Add trigrams for better semantic coverage
            trigrams = [cjk_chars[i] + cjk_chars[i + 1] + cjk_chars[i + 2]
                        for i in range(len(cjk_chars) - 2)]
            raw_tokens.extend(trigrams)

        # Filter
        tokens = []
        for t in raw_tokens:
            t = t.strip()
            if len(t) >= self._min_token and t not in self._stop_words:
                tokens.append(t)

        return tokens

    def _idf(self, term: str) -> float:
        """Compute inverse document frequency for a term."""
        n = len(self._entries)
        if n == 0:
            return 1.0
        doc_count = sum(1 for e in self._entries.values() if term in e.tokens)
        return math.log((n + 1) / (doc_count + 1)) + 1.0

    def _cosine_similarity(self, query_tf: Counter,
                           doc_tf: Counter,
                           doc_id: str) -> float:
        """Compute TF-IDF weighted cosine similarity."""
        # All unique terms from query
        all_terms = set(query_tf.keys()) | set(doc_tf.keys())
        if not all_terms:
            return 0.0

        dot_product = 0.0
        query_norm = 0.0
        doc_norm = 0.0

        for term in all_terms:
            idf = self._idf(term)

            # Query TF-IDF
            q_tf = query_tf.get(term, 0)
            q_tfidf = q_tf * idf

            # Doc TF-IDF
            d_tf = doc_tf.get(term, 0)
            d_tfidf = d_tf * idf

            dot_product += q_tfidf * d_tfidf
            query_norm += q_tfidf * q_tfidf
            doc_norm += d_tfidf * d_tfidf

        if query_norm == 0 or doc_norm == 0:
            return 0.0

        return dot_product / (math.sqrt(query_norm) * math.sqrt(doc_norm))
