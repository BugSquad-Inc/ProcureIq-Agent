"""
rag_tool.py — RAG (Retrieval-Augmented Generation) Tool.

Wraps `HybridSearchService` from `app.core.hybrid_search` to provide
knowledge base Q&A with cited sources over `kb_chunks`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import structlog

from app.core.hybrid_search import HybridSearchService
from app.core.llm_client import call_gemini, parse_json_response
from app.infrastructure.database.session import AsyncSessionLocal

logger = structlog.get_logger("procureiq.rag_tool")


async def execute_rag_query(
    query: str,
    top_k: int = 5,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """Execute a tenant-scoped hybrid RAG query against `kb_chunks`, with optional Gemini reranking."""
    pool_limit = max(top_k * 2, 10)
    async with AsyncSessionLocal() as session:
        service = HybridSearchService(session=session)
        candidates = await service.search_hybrid(
            query_text=query, limit=pool_limit, tenant_id=tenant_id
        )

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
            "rerank_method": "none",
        }

    ranked_chunks, rerank_method = await _rerank_chunks_with_gemini(query, chunks, top_k)
    answer = await _synthesize_answer(query, ranked_chunks)
    sources = [
        {
            "document": c.get("document_name", "Unknown"),
            "section": c.get("section_title"),
            "page": c.get("page"),
            "excerpt": c.get("text", "")[:200],
            "rrf_score": c.get("rrf_score", 0.0),
            **({"llm_score": c["llm_score"]} if "llm_score" in c else {}),
        }
        for c in ranked_chunks
    ]

    return {
        "answer": answer,
        "sources": sources,
        "chunks_retrieved": len(ranked_chunks),
        "rerank_method": rerank_method,
    }


async def _rerank_chunks_with_gemini(
    query: str,
    chunks: List[Dict[str, Any]],
    top_k: int,
) -> Tuple[List[Dict[str, Any]], str]:
    """Rerank hybrid search chunks via Gemini LLM when configured; fallback to RRF order."""
    if len(chunks) <= 1:
        return chunks[:top_k], "hybrid_rrf"

    chunk_lines = "\n\n".join(
        f"[{i+1}] Doc: {c['document_name']} | Section: {c.get('section_title') or 'Body'}\n"
        f"{c['text'][:450]}"
        for i, c in enumerate(chunks)
    )
    prompt = (
        f"Score each candidate document chunk from 0 to 10 based on how directly it answers the query.\n"
        f"Query: {query}\n\n"
        f"Chunks:\n{chunk_lines[:4500]}\n\n"
        f'Return ONLY JSON sorted from most to least relevant: '
        f'{{"ranked": [{{"index": <1-based integer>, "score": <0-10>}}]}}'
    )
    raw = await call_gemini(prompt, temperature=0.0, timeout=8.0)
    parsed = parse_json_response(raw)
    ranked_items = parsed.get("ranked") if isinstance(parsed, dict) else None
    if not isinstance(ranked_items, list):
        return chunks[:top_k], "hybrid_rrf"

    seen: set[int] = set()
    reranked: List[Dict[str, Any]] = []
    sorted_items = sorted(
        (
            item
            for item in ranked_items
            if isinstance(item, dict) and isinstance(item.get("index"), int)
        ),
        key=lambda item: float(item.get("score", 0)),
        reverse=True,
    )
    for item in sorted_items:
        idx = item["index"] - 1
        score = float(item.get("score", 0))
        if 0 <= idx < len(chunks) and idx not in seen and score > 0:
            seen.add(idx)
            chunk_copy = dict(chunks[idx])
            chunk_copy["llm_score"] = score
            reranked.append(chunk_copy)
            if len(reranked) >= top_k:
                break

    if not reranked:
        return chunks[:top_k], "hybrid_rrf"

    return reranked, "gemini_rerank"


async def _synthesize_answer(query: str, chunks: List[Dict[str, Any]]) -> str:
    """Generate a cited answer using shared Gemini client (extractive fallback if unconfigured)."""
    context = "\n\n---\n\n".join(
        f"[{c['document_name']} | {c.get('section_title', 'Section')} | p.{c.get('page', '?')}]\n{c['text']}"
        for c in chunks
    )
    prompt = (
        f"Answer the following question using ONLY the context below. "
        f"Preserve exact policy phrases, figures, and percentages (e.g. '2% penalty') from the source text, "
        f"and cite which document and section your answer comes from.\n\n"
        f"Question: {query}\n\n"
        f"Context:\n{context[:4000]}\n\n"
        f"Answer (cite sources):"
    )
    answer = await call_gemini(prompt, temperature=0.1, timeout=15.0)
    return answer or chunks[0]["text"][:500]
