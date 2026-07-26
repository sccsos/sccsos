"""KnowledgeBase factory — creates the right backend from config.

Usage:
    from sccsos.memory.factory import create_knowledge_base

    # From config
    kb = create_knowledge_base(cfg.agents.knowledge, cfg.agents.wiki_path)

    # Or inline
    kb = create_knowledge_base({"mode": "remote", "remote": {"url": "http://wiki:8750"}})
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sccsos.core.config import KnowledgeConfig
from sccsos.memory.knowledge_base import KnowledgeBase
from sccsos.memory.remote_kb import RemoteKnowledgeBase

logger = logging.getLogger("sccsos.memory.factory")

# Type alias for duck-typing the query interface
KnowledgeBackend = KnowledgeBase | RemoteKnowledgeBase


def create_knowledge_base(
    cfg: KnowledgeConfig | dict[str, Any],
    wiki_path: Optional[str] = None,
) -> KnowledgeBackend:
    """Create a knowledge backend based on configuration.

    Three modes:

    - ``local`` (default): ``KnowledgeBase`` reads wiki/ from local filesystem.
      Use with shared NFS/EFS volume for multi-instance deployments.
      ``cfg.vector_backend`` selects TF-IDF (default) or Chroma.

    - ``chroma``: ``KnowledgeBase`` with shared ChromaDB. All instances query
      the same Chroma service. Index is shared and persistent.

    - ``remote``: ``RemoteKnowledgeBase`` HTTP client. Delegates all queries
      to a standalone wiki microservice (``sccsos.memory.wiki_service``).

    Returns:
        A ``KnowledgeBase`` (local/chroma mode) or ``RemoteKnowledgeBase`` (remote mode).

    Raises:
        ValueError: If ``cfg.mode`` is unknown.
    """
    # Normalize dict → dataclass
    if isinstance(cfg, dict):
        cfg_obj = _dict_to_knowledge_config(cfg)
    else:
        cfg_obj = cfg

    mode = cfg_obj.mode

    if mode == "local":
        kb = KnowledgeBase(
            wiki_path=wiki_path,
            use_vector=(cfg_obj.vector_backend == "chroma"),
            ttl_seconds=300,
        )
        logger.info(
            "KnowledgeBase: local mode, wiki=%s, vector=%s",
            wiki_path or "(none)", cfg_obj.vector_backend,
        )
        return kb

    if mode == "chroma":
        # Chroma mode: shared ChromaDB via local KnowledgeBase
        chroma_cfg = cfg_obj.chroma
        try:
            from sccsos.memory.chroma_store import ChromaVectorStore

            store = ChromaVectorStore(
                collection_name=chroma_cfg.collection,
                persist_directory=chroma_cfg.persist_dir,
            )
        except ImportError:
            logger.warning(
                "ChromaVectorStore not available (install sccsos[chroma]). "
                "Falling back to TF-IDF vector store."
            )
            store = None

        kb = KnowledgeBase(
            wiki_path=wiki_path,
            use_vector=True,
            ttl_seconds=300,
        )
        # Override the internal vector store with Chroma
        if store:
            kb._vector_store = store
            logger.info(
                "KnowledgeBase: chroma mode, collection=%s, host=%s:%s",
                chroma_cfg.collection,
                chroma_cfg.host,
                chroma_cfg.port,
            )
        return kb

    if mode == "remote":
        remote_cfg = cfg_obj.remote
        kb = RemoteKnowledgeBase(
            base_url=remote_cfg.url,
            api_key=remote_cfg.api_key,
            timeout=remote_cfg.timeout,
        )
        logger.info(
            "KnowledgeBase: remote mode, url=%s",
            remote_cfg.url,
        )
        return kb

    raise ValueError(f"Unknown knowledge.mode: {mode!r}")


def _dict_to_knowledge_config(data: dict) -> KnowledgeConfig:
    """Convert a dict to KnowledgeConfig (for inline usage)."""
    from sccsos.core.config import (
        KnowledgeConfig,
        KnowledgeChromaConfig,
        KnowledgeRemoteConfig,
    )

    mode = data.get("mode", "local")
    vector_backend = data.get("vector_backend", "tfidf")

    chroma_data = data.get("chroma", {})
    chroma = KnowledgeChromaConfig(
        host=chroma_data.get("host", "localhost"),
        port=chroma_data.get("port", 8000),
        collection=chroma_data.get("collection", "sccsos-wiki"),
        persist_dir=chroma_data.get("persist_dir", "./data/chroma"),
    )

    remote_data = data.get("remote", {})
    remote = KnowledgeRemoteConfig(
        url=remote_data.get("url", "http://localhost:8750"),
        api_key=remote_data.get("api_key", ""),
        timeout=remote_data.get("timeout", 10),
    )

    return KnowledgeConfig(
        mode=mode,
        vector_backend=vector_backend,
        chroma=chroma,
        remote=remote,
    )
