"""
hybrid_search.py — Reusable Hybrid Search utilities (Dense pgvector + Sparse BM25 + RRF).

Extracted and adapted from RAG-Entreprise core for ProcureIQ:
  - Provides shared `SearchCandidate`, `build_or_tsquery`, and `reciprocal_rank_fusion`.
  - Queries `kb_chunks` cleanly with `halfvec(2560)` support for Qwen3-Embedding-4B.
"""
import re
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.embedding.base import align_embedding_dimension
from app.core.embedding.factory import EmbeddingProviderFactory

logger = structlog.get_logger("procureiq.hybrid_search")

_TS_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "to", "for",
    "of", "in", "on", "at", "by", "with", "from", "and", "or", "my", "our",
    "me", "i", "you", "there", "this", "that", "what", "which", "who",
    "how", "can", "do", "does", "did", "please", "tell", "give",
}


def build_or_tsquery(query_text: str) -> str:
    """
    Convert natural language text into a safe PostgreSQL OR-joined tsquery string.
    Unlike plainto_tsquery (which AND-joins every word and yields 0 matches if a
    single conversational word like 'last' or 'please' is missing), OR-joining
    meaningful tokens lets ts_rank_cd score partial matches accurately.
    """
    raw_tokens = re.findall(r"[a-zA-Z0-9]+", query_text.lower())
    filtered = [t for t in raw_tokens if len(t) > 1 and t not in _TS_STOPWORDS]
    tokens = filtered or [t for t in raw_tokens if t]
    # Deduplicate while preserving order
    seen = set()
    unique_tokens: List[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique_tokens.append(t)
    return " | ".join(unique_tokens[:20])


@dataclass
class SearchCandidate:
    chunk_id: uuid.UUID
    text: str
    document_name: str = ""
    section_title: Optional[str] = None
    section_path: List[str] = field(default_factory=list)
    page: int = 1
    cosine_sim: float = 0.0
    bm25_score: float = 0.0
    rrf_score: float = 0.0


class HybridSearchService:
    """
    Hybrid Search combining dense vector retrieval (pgvector HNSW halfvec) and
    sparse full-text search (PostgreSQL BM25 tsvector) via Reciprocal Rank Fusion (RRF).
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def search_dense(
        self,
        query_vector: List[float],
        dimension: int,
        limit: int = 20,
    ) -> List[SearchCandidate]:
        """Dense semantic search over kb_chunks using pgvector cosine distance."""
        aligned = align_embedding_dimension(query_vector, dimension)
        vector_str = f"[{','.join(str(x) for x in aligned)}]"

        if dimension > 2000:
            dist_expr = f"(embedding <=> CAST(:query_vec AS halfvec({dimension})))"
        else:
            dist_expr = f"(CAST(CAST(embedding AS text) AS vector({dimension})) <=> CAST(:query_vec AS vector({dimension})))"

        sql = text(f"""
            SELECT
                id AS chunk_id,
                document_name,
                section_title,
                text,
                page,
                1.0 - {dist_expr} AS cosine_sim
            FROM kb_chunks
            WHERE embedding IS NOT NULL
            ORDER BY {dist_expr} ASC
            LIMIT :limit
        """)

        res = await self.session.execute(sql, {"query_vec": vector_str, "limit": limit})
        return [
            SearchCandidate(
                chunk_id=r.chunk_id,
                document_name=r.document_name or "",
                section_title=r.section_title,
                text=r.text,
                page=r.page or 1,
                cosine_sim=max(0.0, float(r.cosine_sim)),
            )
            for r in res.fetchall()
        ]

    async def search_bm25(
        self,
        query_text: str,
        limit: int = 20,
    ) -> List[SearchCandidate]:
        """Lexical full-text search over kb_chunks using OR-joined to_tsquery."""
        ts_expr = build_or_tsquery(query_text)
        if not ts_expr:
            return []

        sql = text("""
            SELECT
                id AS chunk_id,
                document_name,
                section_title,
                text,
                page,
                ts_rank_cd(to_tsvector('english', text), to_tsquery('english', :q)) AS bm25_score
            FROM kb_chunks
            WHERE to_tsvector('english', text) @@ to_tsquery('english', :q)
            ORDER BY bm25_score DESC
            LIMIT :limit
        """)

        res = await self.session.execute(sql, {"q": ts_expr, "limit": limit})
        return [
            SearchCandidate(
                chunk_id=r.chunk_id,
                document_name=r.document_name or "",
                section_title=r.section_title,
                text=r.text,
                page=r.page or 1,
                bm25_score=float(r.bm25_score),
            )
            for r in res.fetchall()
        ]

    @staticmethod
    def reciprocal_rank_fusion(
        dense_results: List[SearchCandidate],
        bm25_results: List[SearchCandidate],
        k: int = 60,
        top_k: int = 10,
    ) -> List[SearchCandidate]:
        """Merge dense and BM25 rankings using RRF(d) = sum(1 / (k + rank_i))."""
        candidates_by_id: Dict[uuid.UUID, SearchCandidate] = {}
        rrf_scores: Dict[uuid.UUID, float] = {}

        for rank, cand in enumerate(dense_results):
            rrf_scores[cand.chunk_id] = rrf_scores.get(cand.chunk_id, 0.0) + (1.0 / (k + rank + 1))
            candidates_by_id[cand.chunk_id] = cand

        for rank, cand in enumerate(bm25_results):
            rrf_scores[cand.chunk_id] = rrf_scores.get(cand.chunk_id, 0.0) + (1.0 / (k + rank + 1))
            if cand.chunk_id in candidates_by_id:
                candidates_by_id[cand.chunk_id].bm25_score = cand.bm25_score
            else:
                candidates_by_id[cand.chunk_id] = cand

        merged: List[SearchCandidate] = []
        for cid, score in rrf_scores.items():
            cand = candidates_by_id[cid]
            cand.rrf_score = round(score, 6)
            merged.append(cand)

        merged.sort(key=lambda c: c.rrf_score, reverse=True)
        return merged[:top_k]

    async def search_hybrid(self, query_text: str, limit: int = 10) -> List[SearchCandidate]:
        """Run dense + BM25 search over kb_chunks and fuse with RRF."""
        settings = get_settings()
        provider = EmbeddingProviderFactory.get_provider()
        query_vector = await provider.embed_query(query_text)
        target_dim = settings.embedding_dimension

        dense_cands = await self.search_dense(query_vector, dimension=target_dim, limit=limit * 2)
        bm25_cands = await self.search_bm25(query_text, limit=limit * 2)
        return self.reciprocal_rank_fusion(dense_cands, bm25_cands, top_k=limit)
