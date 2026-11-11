"""
retriever.py — Semantic Tool Retrieval ("Tool RAG") Engine.

Core Thesis:
  Tools are to an Agentic System what Documents are to RAG.
  Instead of stuffing 50-500+ tool schemas into the LLM prompt, we index tool
  descriptions in PostgreSQL (pgvector HALFVEC + GIN full-text index) and
  retrieve only the top-k most relevant tools per query:
    1. Dense Vector Search (pgvector cosine similarity)
    2. Sparse Lexical BM25 Search (PostgreSQL OR-tsquery ts_rank_cd)
    3. Reciprocal Rank Fusion (RRF)
    4. Cross-Encoder / Lexical Alignment Reranking
    5. Explainable score breakdown per candidate
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.embedding.base import align_embedding_dimension
from app.core.embedding.factory import EmbeddingProviderFactory
from app.core.hybrid_search import SearchCandidate, build_or_tsquery, normalize_query_text
from app.core.reranking import CrossEncoderReranker, compute_intent_multiplier, get_cross_encoder_reranker
from app.infrastructure.database.models import Tool

try:
    from langsmith import traceable
except ImportError:  # pragma: no cover
    def traceable(*args, **kwargs):
        def _decorator(fn):
            return fn
        return _decorator

logger = structlog.get_logger("procureiq.tools.retriever")


@dataclass
class RetrievedTool:
    name: str
    domain: str
    description: str
    schema: Dict[str, Any] = field(default_factory=dict)
    endpoint: Optional[str] = None
    cosine_sim: float = 0.0
    bm25_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: float = 0.0
    final_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ToolRetrievalResult:
    query: str
    domain_filter: Optional[str]
    top_k: int
    total_active_tools: int
    latency_ms: float
    embedding_provider: str
    embedding_model: str
    reranker_mode: str
    tools: List[RetrievedTool]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "domain_filter": self.domain_filter,
            "top_k": self.top_k,
            "tools_retrieved": len(self.tools),
            "total_active_tools": self.total_active_tools,
            "latency_ms": self.latency_ms,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "reranker_mode": self.reranker_mode,
            "tools": [t.to_dict() for t in self.tools],
        }


class ToolRetriever:
    """
    Hybrid Dense + BM25 + RRF + Reranker retrieval engine over the `tools` table.
    """

    def __init__(
        self,
        session: AsyncSession,
        reranker: Optional[CrossEncoderReranker] = None,
    ):
        self.session = session
        self.reranker = reranker or get_cross_encoder_reranker()

    @traceable(name="procureiq.tool_rag.retrieve", run_type="retriever")
    async def retrieve(
        self,
        query_text: str,
        domain: Optional[str] = None,
        top_k: int = 5,
    ) -> ToolRetrievalResult:
        started = time.perf_counter()
        settings = get_settings()
        provider = EmbeddingProviderFactory.get_provider()
        normalized_query = normalize_query_text(query_text)

        active_domain = domain if (domain and domain != "general") else None
        candidate_pool = max(top_k * 4, 20)

        total_active = await self._count_active_tools()

        dense_rows = await self._search_dense(
            query_text=normalized_query,
            provider=provider,
            target_dim=settings.embedding_dimension,
            domain=active_domain,
            limit=candidate_pool,
        )
        bm25_rows = await self._search_bm25(
            query_text=normalized_query,
            domain=active_domain,
            limit=candidate_pool,
        )

        # If a strict domain filter yielded nothing, widen across all active tools.
        if active_domain and not dense_rows and not bm25_rows:
            logger.info("domain_filter_empty_widening_search", domain=active_domain)
            active_domain = None
            dense_rows = await self._search_dense(
                query_text=normalized_query,
                provider=provider,
                target_dim=settings.embedding_dimension,
                domain=None,
                limit=candidate_pool,
            )
            bm25_rows = await self._search_bm25(
                query_text=normalized_query,
                domain=None,
                limit=candidate_pool,
            )

        fused = self._fuse_and_rerank_candidates(
            query_text=normalized_query,
            dense_rows=dense_rows,
            bm25_rows=bm25_rows,
            top_k=top_k,
        )
        tools = await fused

        if not tools and total_active > 0:
            tools = await self._fallback_active_tools(top_k)

        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        reranker_mode = "lexical_alignment" if self.reranker._get_model() is False else self.reranker.model_name

        logger.info(
            "tool_rag_completed",
            query_preview=query_text[:60],
            domain_filter=active_domain,
            retrieved=len(tools),
            total_active=total_active,
            latency_ms=elapsed_ms,
        )

        return ToolRetrievalResult(
            query=query_text,
            domain_filter=active_domain,
            top_k=top_k,
            total_active_tools=total_active,
            latency_ms=elapsed_ms,
            embedding_provider=settings.embedding_provider,
            embedding_model=provider.model_name,
            reranker_mode=reranker_mode,
            tools=tools,
        )

    async def _count_active_tools(self) -> int:
        res = await self.session.execute(
            select(func.count(Tool.id)).where(Tool.is_active == True)  # noqa: E712
        )
        return int(res.scalar() or 0)

    async def _search_dense(
        self,
        query_text: str,
        provider: Any,
        target_dim: int,
        domain: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        try:
            raw_vec = await provider.embed_query(query_text)
            aligned_vec = align_embedding_dimension(raw_vec, target_dim)
            vec_str = f"[{','.join(str(x) for x in aligned_vec)}]"

            if target_dim > 2000:
                dist_expr = f"(embedding <=> CAST(:qv AS halfvec({target_dim})))"
            else:
                dist_expr = (
                    f"(CAST(CAST(embedding AS text) AS vector({target_dim})) "
                    f"<=> CAST(:qv AS vector({target_dim})))"
                )

            domain_clause = "AND domain = :domain" if domain else ""
            sql = text(f"""
                SELECT id, name, domain, description, schema, endpoint,
                       1.0 - {dist_expr} AS cosine_sim
                FROM tools
                WHERE is_active = TRUE
                  {domain_clause}
                  AND embedding IS NOT NULL
                ORDER BY {dist_expr} ASC
                LIMIT :limit
            """)
            params: Dict[str, Any] = {"qv": vec_str, "limit": limit}
            if domain:
                params["domain"] = domain
            res = await self.session.execute(sql, params)
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "domain": r.domain,
                    "description": r.description,
                    "schema": r.schema or {},
                    "endpoint": r.endpoint,
                    "cosine_sim": round(max(0.0, float(r.cosine_sim)), 4),
                }
                for r in res.fetchall()
            ]
        except Exception as exc:
            logger.warning("tool_dense_search_failed", error=str(exc))
            return []

    async def _search_bm25(
        self,
        query_text: str,
        domain: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        ts_expr = build_or_tsquery(query_text)
        if not ts_expr:
            return []
        try:
            domain_clause = "AND domain = :domain" if domain else ""
            doc_vector = "to_tsvector('english', replace(name, '_', ' ') || ' ' || domain || ' ' || description)"
            sql = text(f"""
                SELECT id, name, domain, description, schema, endpoint,
                       ts_rank_cd({doc_vector}, to_tsquery('english', :q)) AS bm25_score
                FROM tools
                WHERE is_active = TRUE
                  {domain_clause}
                  AND {doc_vector} @@ to_tsquery('english', :q)
                ORDER BY bm25_score DESC
                LIMIT :limit
            """)
            params: Dict[str, Any] = {"q": ts_expr, "limit": limit}
            if domain:
                params["domain"] = domain
            res = await self.session.execute(sql, params)
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "domain": r.domain,
                    "description": r.description,
                    "schema": r.schema or {},
                    "endpoint": r.endpoint,
                    "bm25_score": round(float(r.bm25_score), 4),
                }
                for r in res.fetchall()
            ]
        except Exception as exc:
            logger.warning("tool_bm25_search_failed", error=str(exc))
            return []

    async def _fuse_and_rerank_candidates(
        self,
        query_text: str,
        dense_rows: List[Dict[str, Any]],
        bm25_rows: List[Dict[str, Any]],
        top_k: int,
        k: int = 60,
    ) -> List[RetrievedTool]:
        if not dense_rows and not bm25_rows:
            return []

        merged_map: Dict[Any, RetrievedTool] = {}
        rrf_scores: Dict[Any, float] = {}

        for rank, row in enumerate(dense_rows):
            tid = row["id"]
            rrf_scores[tid] = rrf_scores.get(tid, 0.0) + 1.0 / (k + rank + 1)
            merged_map[tid] = RetrievedTool(
                name=row["name"],
                domain=row["domain"],
                description=row["description"],
                schema=row["schema"],
                endpoint=row["endpoint"],
                cosine_sim=row["cosine_sim"],
            )

        for rank, row in enumerate(bm25_rows):
            tid = row["id"]
            rrf_scores[tid] = rrf_scores.get(tid, 0.0) + 1.0 / (k + rank + 1)
            if tid in merged_map:
                merged_map[tid].bm25_score = row["bm25_score"]
            else:
                merged_map[tid] = RetrievedTool(
                    name=row["name"],
                    domain=row["domain"],
                    description=row["description"],
                    schema=row["schema"],
                    endpoint=row["endpoint"],
                    bm25_score=row["bm25_score"],
                )

        # Keep top candidate pool from RRF before reranking
        pre_rerank_ids = sorted(rrf_scores, key=lambda tid: rrf_scores[tid], reverse=True)[: max(top_k * 3, 15)]
        max_rrf = max((rrf_scores[tid] for tid in pre_rerank_ids), default=1.0) or 1.0

        search_cands: List[SearchCandidate] = []
        id_by_cand_uuid: Dict[Any, Any] = {}
        for tid in pre_rerank_ids:
            tool = merged_map[tid]
            tool.rrf_score = round(rrf_scores[tid], 6)
            readable_text = f"{tool.name.replace('_', ' ')} ({tool.domain}): {tool.description}"
            cand = SearchCandidate(
                chunk_id=tid,
                document_name=tool.name,
                text=readable_text,
                cosine_sim=tool.cosine_sim,
                bm25_score=tool.bm25_score,
                rrf_score=tool.rrf_score,
            )
            search_cands.append(cand)
            id_by_cand_uuid[tid] = tool

        reranked = await self.reranker.rerank(
            query_text=query_text,
            candidates=search_cands,
            top_k=len(search_cands),
        )

        # Combine normalized RRF, cosine, and rerank scores into an explainable final score
        output: List[RetrievedTool] = []
        for rr in reranked:
            tool = id_by_cand_uuid[rr.candidate.chunk_id]
            tool.rerank_score = rr.reranker_score
            norm_rrf = tool.rrf_score / max_rrf
            raw_final = 0.45 * norm_rrf + 0.35 * tool.rerank_score + 0.20 * tool.cosine_sim
            raw_final *= compute_intent_multiplier(query_text, rr.candidate.text)
            tool.final_score = round(raw_final, 4)
            output.append(tool)

        output.sort(key=lambda t: (t.final_score, t.rrf_score, t.cosine_sim), reverse=True)
        return output[:top_k]

    async def _fallback_active_tools(self, top_k: int) -> List[RetrievedTool]:
        res = await self.session.execute(
            select(Tool).where(Tool.is_active == True).limit(top_k)  # noqa: E712
        )
        return [
            RetrievedTool(
                name=t.name,
                domain=t.domain,
                description=t.description,
                schema=t.schema or {},
                endpoint=t.endpoint,
            )
            for t in res.scalars().all()
        ]

