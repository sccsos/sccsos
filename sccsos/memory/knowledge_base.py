"""Knowledge Base — cold memory bridge to Hermes wiki, skills, and memory.

Provides an Agent-accessible query layer over:
  - Hermes wiki (`.md` files at a configured path)
  - Hermes skills (SKILL.md files)
  - Persistent memory entries

Usage:
    kb = KnowledgeBase(wiki_path="/path/to/wiki")
    results = kb.query("database schema")
    context = kb.get_context_for("Agent lifecycle states")
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


from sccsos.memory.vector_store import VectorStore


# ── Data models ────────────────────────────────────────────────────


@dataclass
class KnowledgeEntry:
    """A single knowledge item from the knowledge base."""
    source: str       # e.g. "wiki", "skill", "memory"
    title: str
    path: str         # file path or identifier
    content: str      # full text
    snippet: str = ""  # excerpt (first 200 chars or match context)
    tags: list[str] = field(default_factory=list)
    relevance: float = 0.0


# ── Knowledge Base ─────────────────────────────────────────────────


class KnowledgeBase:
    """Read-only knowledge base over Hermes wiki, skills, and memory.

    Walks configured directories on construction and caches
    file contents. Supports basic keyword search (substring/word
    matching). TTL-based cache refresh.

    Args:
        wiki_path: Directory containing wiki `.md` files.
        skill_path: Directory containing skill files.
        ttl_seconds: How long to cache file contents (default 120s).
    """

    def __init__(self, wiki_path: Optional[str | Path] = None,
                 skill_path: Optional[str | Path] = None,
                 ttl_seconds: int = 120,
                 use_vector: bool = False):
        self._wiki_path = Path(wiki_path) if wiki_path else None
        self._skill_path = Path(skill_path) if skill_path else None
        self._ttl = ttl_seconds
        self._use_vector = use_vector
        self._entries: list[KnowledgeEntry] = []
        self._vector_store: VectorStore | None = None
        self._loaded_at: float = 0.0

    # ── Public API ───────────────────────────────────────────────

    def query(self, query: str, top_k: int = 5) -> list[KnowledgeEntry]:
        """Search the knowledge base for relevant entries.

        If vector search is enabled (``use_vector=True``), uses
        TF-IDF cosine similarity for semantic ranking. Otherwise
        uses keyword substring matching.

        Args:
            query: Search string (e.g. "Agent lifecycle states").
            top_k: Maximum number of results (default 5).

        Returns:
            List of KnowledgeEntry sorted by relevance (descending).
        """
        self._refresh_if_stale()
        if not self._entries:
            return []

        # ── Vector search path ──────────────────────────────────
        if self._use_vector and self._vector_store:
            doc_map = {e.path: e for e in self._entries}
            results = self._vector_store.search_with_snippets(
                query, top_k=top_k
            )
            matched = []
            for doc_id, score, _ in results:
                entry = doc_map.get(doc_id)
                if entry:
                    entry.relevance = score
                    matched.append(entry)
            return matched

        # ── Keyword search path (fallback) ──────────────────────
        terms = [t.strip().lower() for t in re.split(r"[\s,]+", query)
                 if t.strip()]

        scored: list[tuple[float, KnowledgeEntry]] = []
        for entry in self._entries:
            score = self._score_entry(entry, terms)
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    def get_context_for(self, topic: str) -> str:
        """Get a consolidated context string for a topic.

        Useful for injecting relevant knowledge into agent prompts.
        """
        results = self.query(topic, top_k=3)
        if not results:
            return ""

        parts = []
        for r in results:
            source_tag = f"[{r.source}: {r.title}]"
            parts.append(f"{source_tag}\n{r.snippet}")
        return "\n\n".join(parts)

    def list_sources(self) -> list[str]:
        """List all available knowledge sources (wiki/skill/memory)."""
        self._refresh_if_stale()
        sources = set()
        for e in self._entries:
            sources.add(e.source)
        return sorted(sources)

    def reload(self) -> None:
        """Force-reload all entries from disk."""
        self._entries = []
        self._load_entries()
        self._loaded_at = time.monotonic()

    # ── Internal ─────────────────────────────────────────────────

    def _refresh_if_stale(self) -> None:
        if not self._entries:
            self.reload()
        elif time.monotonic() - self._loaded_at > self._ttl:
            self.reload()

    def _load_entries(self) -> None:
        """Load entries from all configured sources."""
        if self._wiki_path and self._wiki_path.exists():
            self._load_from_dir(self._wiki_path, "wiki", "*.md")
        if self._skill_path and self._skill_path.exists():
            self._load_from_dir(self._skill_path, "skill", "SKILL.md")
        # Build vector index if enabled
        if self._use_vector:
            self._vector_store = VectorStore()
            for entry in self._entries:
                self._vector_store.add_document(
                    entry.path, entry.content,
                    metadata={"source": entry.source, "title": entry.title},
                )

    def _load_from_dir(self, directory: Path, source: str,
                       glob_pattern: str) -> None:
        """Load knowledge entries from a directory."""
        for fpath in directory.rglob(glob_pattern):
            if fpath.name.startswith("."):
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                title = self._extract_title(content, fpath)
                snippet = content[:500].strip()
                # Extract tags from YAML frontmatter
                tags = self._extract_tags(content)

                self._entries.append(KnowledgeEntry(
                    source=source,
                    title=title,
                    path=str(fpath.relative_to(directory.parent)
                             if directory.parent else fpath),
                    content=content,
                    snippet=snippet,
                    tags=tags,
                ))
            except Exception:
                pass  # Skip unreadable files

    def _extract_title(self, content: str, fpath: Path) -> str:
        """Extract title from frontmatter or first heading."""
        # Try YAML frontmatter title
        m = re.match(r"^---\s*\n(?:.*\n)*?title:\s*(.+?)\s*\n(?:.*\n)*?---", content)
        if m:
            return m.group(1).strip()

        # Try first Markdown heading
        m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if m:
            return m.group(1).strip()

        # Fall back to filename
        return fpath.stem

    def _extract_tags(self, content: str) -> list[str]:
        """Extract tags from YAML frontmatter."""
        m = re.search(r"^---\s*\n(?:.*\n)*?tags:\s*\[(.+?)\]", content)
        if m:
            return [t.strip().strip("'\"") for t in m.group(1).split(",")]
        return []

    def _score_entry(self, entry: KnowledgeEntry,
                     terms: list[str]) -> float:
        """Score an entry by number of matching terms.

        Title matches score higher than body matches.
        """
        title_lower = entry.title.lower()
        content_lower = entry.content.lower()
        tag_lower = " ".join(entry.tags).lower()

        score = 0.0
        for term in terms:
            if term in title_lower:
                score += 3.0
            if term in tag_lower:
                score += 2.0
            if term in content_lower:
                score += 1.0
        return score
