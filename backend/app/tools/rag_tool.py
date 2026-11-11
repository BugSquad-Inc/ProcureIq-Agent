"""
rag_tool.py — RAG (Retrieval-Augmented Generation) Tool.

Wraps `HybridSearchService` from `app.core.hybrid_search` to provide
knowledge base Q&A with cited sources over `kb_chunks`.
"""
from __future__ import annotations

from typing import Any, Dict, List

import structlog

from app.core.hybrid_search import HybridSearchService
from app.core.llm_client import call_gemini
from app.infrastructure.database.session import AsyncSessionLocal

logger = structlog.get_logger("procureiq.rag_tool")


async def execute_rag_query(query: str, top_k: int = 5) -> Dict[str, Any]:
    """Execute a hybrid RAG query against the knowledge base (`kb_chunks`)."""
    async with AsyncSessionLocal() as session:
        service = HybridSearchService(session=session)
        candidates = await service.search_hybrid(query_text=query, limit=top_k)

    chunks = [
        {
            "document_name": c.document_name,
            "section_title": c.section_title,
            "text": c.text,
            "page": c.page,
            "rrf_score": c.rrf_score,
        }
        for c in candidates
    ]

    if not chunks:
        return {
            "answer": "No relevant documents found in the knowledge base. Please upload relevant documents first.",
            "sources": [],
            "chunks_retrieved": 0,
        }

    answer = await _synthesize_answer(query, chunks)
    sources = [
        {
            "document": c.get("document_name", "Unknown"),
            "section": c.get("section_title"),
            "page": c.get("page"),
            "excerpt": c.get("text", "")[:200],
            "rrf_score": c.get("rrf_score", 0.0),
        }
        for c in chunks
    ]

    return {
        "answer": answer,
        "sources": sources,
        "chunks_retrieved": len(chunks),
    }


async def _synthesize_answer(query: str, chunks: List[Dict[str, Any]]) -> str:
    """Generate a cited answer using shared Gemini client (extractive fallback if unconfigured)."""
    context = "\n\n---\n\n".join(
        f"[{c['document_name']} | {c.get('section_title', 'Section')} | p.{c.get('page', '?')}]\n{c['text']}"
        for c in chunks
    )
    prompt = (
        f"Answer the following question using ONLY the context below. "
        f"Always cite which document and section your answer comes from.\n\n"
        f"Question: {query}\n\n"
        f"Context:\n{context[:4000]}\n\n"
        f"Answer (cite sources):"
    )
    answer = await call_gemini(prompt, temperature=0.1, timeout=15.0)
    return answer or chunks[0]["text"][:500]
