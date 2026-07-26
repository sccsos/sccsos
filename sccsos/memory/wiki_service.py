"""Wiki 微服务 — 独立部署的知识库查询服务.

将 KnowledgeBase + Chroma 封装为独立的 FastAPI 服务，供多个 SCCS OS
实例共享。支持三种部署模式：

1. 本地文件模式: 直接读取 wiki/ 目录
2. Chroma 模式: 使用 ChromaDB 作为向量检索后端
3. Embedding 模式: 使用外部 Embedding 模型

Usage:
    # 本地模式 (TF-IDF)
    python -m sccsos.memory.wiki_service --wiki-path ./wiki

    # Chroma 模式
    python -m sccsos.memory.wiki_service --vector-backend chroma --persist-dir ./data/chroma

    # 指定端口
    python -m sccsos.memory.wiki_service --port 8750
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Optional

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:
    raise ImportError(
        "sccsos[api] extras are required for the wiki service. "
        "Install with: pip install sccsos[api]"
    )

import uvicorn

from sccsos.memory.knowledge_base import KnowledgeBase, KnowledgeEntry

logger = logging.getLogger("sccsos.wiki_service")

app = FastAPI(
    title="SCCS OS Wiki Service",
    version="0.20.10",
    description="Standalone knowledge base service for SCCS OS",
)

# ── CORS ─────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global KB instance (set by main()) ───────────────────────────
_kb: Optional[KnowledgeBase] = None


def get_kb() -> KnowledgeBase:
    assert _kb is not None, "KnowledgeBase not initialized"
    return _kb


# ── Routes ───────────────────────────────────────────────────────


@app.get("/health")
async def health():
    kb = get_kb()
    return {
        "status": "running",
        "version": "0.20.10",
        "entries": len(kb.list_sources()) if hasattr(kb, "list_sources") else 0,
    }


@app.post("/query")
async def query(body: dict):
    """Search the knowledge base.

    Request:
        {"query": "agent lifecycle", "top_k": 5}

    Response:
        {"results": [{"source": "wiki", "title": "...", ...}]}
    """
    kb = get_kb()
    q = body.get("query", "")
    top_k = min(body.get("top_k", 5), 20)
    results = kb.query(q, top_k=top_k)
    return {
        "results": [
            {
                "source": r.source,
                "title": r.title,
                "path": r.path,
                "content": r.content,
                "snippet": r.snippet,
                "relevance": r.relevance,
            }
            for r in results
        ]
    }


@app.post("/context")
async def get_context(body: dict):
    """Get consolidated context string for a topic.

    Request:
        {"query": "agent lifecycle", "top_k": 3}

    Response:
        {"context": "[wiki: ...]\\ncontent..."}
    """
    kb = get_kb()
    topic = body.get("query", "")
    context = kb.get_context_for(topic)
    return {"context": context}


@app.get("/sources")
async def list_sources():
    """List all available knowledge sources."""
    kb = get_kb()
    sources = kb.list_sources()
    return {"sources": sources}


@app.post("/reload")
async def reload_kb():
    """Force-reload the knowledge base from disk."""
    kb = get_kb()
    kb.reload()
    return {"status": "ok", "entries": len(kb.list_sources())}


# ── Main ─────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="SCCS OS Wiki Service")
    parser.add_argument("--wiki-path", default="./wiki",
                        help="Path to wiki markdown files")
    parser.add_argument("--vector-backend", default="tfidf",
                        choices=["tfidf", "chroma"],
                        help="Vector search backend")
    parser.add_argument("--persist-dir", default="./data/chroma",
                        help="Chroma persist directory (chroma backend)")
    parser.add_argument("--collection", default="sccsos-wiki",
                        help="Chroma collection name")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8750)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    global _kb
    use_vector = args.vector_backend == "chroma"

    _kb = KnowledgeBase(
        wiki_path=args.wiki_path,
        use_vector=use_vector,
        ttl_seconds=300,
    )
    logger.info(
        "Wiki service initialized: wiki=%s vector=%s",
        args.wiki_path, args.vector_backend,
    )

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
