"""Knowledge Base — cold memory bridge to Hermes wiki, skills, and memory.

Provides an Agent-accessible query layer over:
  - Hermes wiki (`.md` files at a configured path)
  - Hermes skills (SKILL.md files)
  - Persistent memory entries

Features:
- **Lazy loading**: files are scanned on first query, not construction
- **Incremental refresh**: only reloads files whose mtime has changed
- **Persistent cache**: serialized index survives process restarts
  (avoids full re-index on startup when files are unchanged)
- **TTL-based refresh**: periodic full rescan when cache expires

Usage:
    kb = KnowledgeBase(wiki_path="/path/to/wiki")
    results = kb.query("database schema")
    context = kb.get_context_for("Agent lifecycle states")
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict
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

    Lazy-loads file contents on first query.  Uses file modification
    timestamps to detect changes and only re-index changed files.
    A persistent cache file (JSON) avoids full re-indexing across
    process restarts when no files have changed.

    Args:
        wiki_path: Directory containing wiki ``.md`` files.
        skill_path: Directory containing skill files.
        ttl_seconds: How long before a full rescan (default 300s).
        cache_path: Where to store the persistent index cache
            (default ``~/.cache/sccsos/knowledge_cache.json``).
    """

    def __init__(self, wiki_path: Optional[str | Path] = None,
                 skill_path: Optional[str | Path] = None,
                 ttl_seconds: int = 300,
                 cache_path: Optional[str | Path] = None,
                 use_vector: bool = False):
        self._wiki_path = Path(wiki_path) if wiki_path else None
        self._skill_path = Path(skill_path) if skill_path else None
        self._ttl = ttl_seconds
        self._use_vector = use_vector
        self._entries: list[KnowledgeEntry] = []
        self._vector_store: VectorStore | None = None
        self._loaded_at: float = 0.0

        # File manifest: relative_path → mtime_ns  (for incremental refresh)
        self._manifest: dict[str, int] = {}

        # Persistent cache path (default: ~/.cache/sccsos/knowledge_cache.json)
        if cache_path:
            self._cache_path = Path(cache_path)
        else:
            self._cache_path = Path.home() / ".cache" / "sccsos" / "knowledge_cache.json"
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)

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
        self._ensure_loaded()
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
        self._ensure_loaded()
        sources = set()
        for e in self._entries:
            sources.add(e.source)
        return sorted(sources)

    def reload(self) -> None:
        """Force-reload all entries from disk.

        Clears the persistent cache to ensure a full rebuild.
        """
        self._manifest = {}
        self._entries = []
        self._load_entries()
        self._loaded_at = time.monotonic()
        self._save_cache()

    # ── Internal — Lazy / Incremental / Cached ──────────────────

    def _ensure_loaded(self) -> None:
        """Lazy load: populate entries on first call, or refresh if stale.

        Uses three strategies, in priority order:

        1. **Persistent cache** — if no files changed since last run,
           restore from JSON cache (instant, no disk I/O for content).
        2. **Incremental refresh** — if only some files changed,
           only load/re-index the changed ones.
        3. **Full load** — on first run or after TTL expiry.
        """
        if not self._entries:
            # First call: try persistent cache, fall back to full load
            if not self._try_restore_cache():
                self._load_entries()
            self._loaded_at = time.monotonic()
            return

        # Stale: check for changes
        if time.monotonic() - self._loaded_at > self._ttl:
            changed = self._scan_changed_files()
            if changed:
                self._load_entries(changed_only=True, changed_paths=changed)
                self._save_cache()
            else:
                self._refresh_manifest()  # Update mtimes even if content unchanged
                self._save_cache()
            self._loaded_at = time.monotonic()

    def _try_restore_cache(self) -> bool:
        """Try to restore entries from persistent cache.

        Returns:
            True if cache was loaded successfully and is up to date.
        """
        if not self._cache_path.exists():
            return False
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            cache_manifest = data.get("manifest", {})
            entries_data = data.get("entries", [])

            # Verify no files have changed since cache was built
            current_manifest = self._build_file_manifest()
            if cache_manifest != current_manifest:
                return False  # Stale cache

            # Restore entries
            self._manifest = current_manifest
            for ed in entries_data:
                self._entries.append(KnowledgeEntry(**ed))
            self._loaded_at = time.monotonic()

            # Rebuild vector index if needed
            if self._use_vector:
                self._vector_store = VectorStore()
                for entry in self._entries:
                    self._vector_store.add_document(
                        entry.path, entry.content,
                        metadata={"source": entry.source, "title": entry.title},
                    )
            return True
        except Exception:
            return False

    def _save_cache(self) -> None:
        """Persist current entries and manifest to JSON cache."""
        try:
            data = {
                "manifest": self._manifest,
                "entries": [
                    {k: v for k, v in asdict(e).items() if k != "relevance"}
                    for e in self._entries
                ],
            }
            self._cache_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass  # Cache is best-effort

    def _build_file_manifest(self) -> dict[str, int]:
        """Build a dict of relative_path → mtime_ns for all source files.

        This is the fingerprint used to detect changes across restarts.
        """
        manifest: dict[str, int] = {}
        if self._wiki_path and self._wiki_path.exists():
            for fpath in self._wiki_path.rglob("*.md"):
                if fpath.name.startswith("."):
                    continue
                rel = str(fpath.relative_to(self._wiki_path.parent)
                          if self._wiki_path.parent else fpath)
                manifest[rel] = fpath.stat().st_mtime_ns
        if self._skill_path and self._skill_path.exists():
            for fpath in self._skill_path.rglob("SKILL.md"):
                if fpath.name.startswith("."):
                    continue
                rel = str(fpath.relative_to(self._skill_path.parent)
                          if self._skill_path.parent else fpath)
                manifest[rel] = fpath.stat().st_mtime_ns
        return manifest

    def _refresh_manifest(self) -> None:
        """Update the manifest without reloading content."""
        self._manifest = self._build_file_manifest()

    def _scan_changed_files(self) -> list[Path]:
        """Check which files have changed since last load.

        Returns:
            List of file paths that are new or modified.
        """
        current = self._build_file_manifest()
        changed: list[Path] = []

        for rel_path, mtime in current.items():
            old_mtime = self._manifest.get(rel_path)
            if old_mtime != mtime:
                # Resolve the file path
                for base, source in [
                    (self._wiki_path, "wiki"),
                    (self._skill_path, "skill"),
                ]:
                    if base and base.parent:
                        full = base.parent / rel_path
                        if full.exists():
                            changed.append(full)
                            break

        # Deleted files: remove from entries
        removed = [k for k in self._manifest if k not in current]
        if removed:
            self._entries = [e for e in self._entries if e.path not in removed]

        self._manifest = current
        return changed

    def _load_entries(self, changed_only: bool = False,
                      changed_paths: Optional[list[Path]] = None) -> None:
        """Load entries from all configured sources.

        Args:
            changed_only: If True, only load files in *changed_paths*.
            changed_paths: List of file paths that have changed.
        """
        if not changed_only:
            self._entries = []
            self._manifest = self._build_file_manifest()

        if self._wiki_path and self._wiki_path.exists():
            files = changed_paths if changed_only else None
            self._load_from_dir(
                self._wiki_path, "wiki", "*.md",
                filter_files=files,
            )
        if self._skill_path and self._skill_path.exists():
            files = changed_paths if changed_only else None
            self._load_from_dir(
                self._skill_path, "skill", "SKILL.md",
                filter_files=files,
            )

        # Rebuild vector index if enabled (always full rebuild for simplicity)
        if self._use_vector:
            self._vector_store = VectorStore()
            for entry in self._entries:
                self._vector_store.add_document(
                    entry.path, entry.content,
                    metadata={"source": entry.source, "title": entry.title},
                )

        # Save persistent cache
        if not changed_only:
            self._save_cache()

    def _load_from_dir(self, directory: Path, source: str,
                       glob_pattern: str,
                       filter_files: Optional[list[Path]] = None) -> None:
        """Load knowledge entries from a directory.

        Args:
            directory: Base directory to scan.
            source: Source label ("wiki" or "skill").
            glob_pattern: File glob pattern (e.g. ``*.md``).
            filter_files: Optional list of files to load (load all if None).
        """
        for fpath in directory.rglob(glob_pattern):
            if fpath.name.startswith("."):
                continue
            if filter_files is not None and fpath not in filter_files:
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
