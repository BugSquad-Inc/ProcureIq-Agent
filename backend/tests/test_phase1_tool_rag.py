"""
test_phase1_tool_rag.py — Phase 1 (Sprint 0 + Sprint 1) Verification Suite.

Validates:
  1. Unit tests: OR-tsquery builder, dimension alignment, RRF fusion, reranker fallback
  2. Integration tests (PostgreSQL + pgvector):
     - Seeded 50-tool catalog across 5 domains
     - CRUD endpoints (/api/tools, /api/tools/{name}, /health)
     - Semantic Tool RAG retrieval accuracy on PayPal & Procurement queries
     - Scale test (50 -> 150 tools): top-5 retrieval stays accurate & bounded
"""
from __future__ import annotations

import math
import uuid
from typing import Dict, List

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

from app.core.embedding.base import align_embedding_dimension
from app.core.embedding.hash_provider import HashEmbeddingProvider
from app.core.hybrid_search import HybridSearchService, SearchCandidate, build_or_tsquery
from app.core.reranking import CrossEncoderReranker
from app.infrastructure.database.models import Tool
from app.infrastructure.database.session import AsyncSessionLocal
from app.main import app
from app.tools.registry import upsert_tools_batch

# ── Benchmark Queries (Datazoic PayPal + ProcureIQ scenarios) ────────────────
BENCHMARK_CASES: List[Dict[str, object]] = [
    {
        "query": "Send an invoice for $50 to client@example.com",
        "expected_any": {"send_invoice", "create_invoice"},
    },
    {
        "query": "What was my total sales volume last month?",
        "expected_any": {"get_sales_report", "get_revenue_breakdown"},
    },
    {
        "query": "Is there a dispute open from user_123?",
        "expected_any": {"get_dispute", "list_disputes"},
    },
    {
        "query": "Create a purchase order for server hardware from Acme Corp",
        "expected_any": {"create_purchase_order"},
    },
    {
        "query": "Issue a full or partial refund for a customer payment",
        "expected_any": {"refund_payment"},
    },
    {
        "query": "Check current available PayPal account balance",
        "expected_any": {"get_balance"},
    },
    {
        "query": "Send batch payouts to multiple vendors and contractors",
        "expected_any": {"create_payout_batch"},
    },
    {
        "query": "Flag price mismatch between vendor invoice and purchase order",
        "expected_any": {"flag_invoice_discrepancy"},
    },
]


@pytest_asyncio.fixture
async def api_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ── 1. Unit Tests ─────────────────────────────────────────────────────────────

def test_build_or_tsquery_strips_stopwords_and_punct():
    q = "What was my total sales volume last month?"
    ts = build_or_tsquery(q)
    tokens = ts.split(" | ")
    assert "total" in tokens
    assert "sales" in tokens
    assert "volume" in tokens
    assert "what" not in tokens
    assert "was" not in tokens
    assert "?" not in ts


def test_align_embedding_dimension_preserves_unit_norm():
    raw = [0.6, 0.8]
    aligned = align_embedding_dimension(raw, 2560)
    assert len(aligned) == 2560
    norm = math.sqrt(sum(v * v for v in aligned))
    assert math.isclose(norm, 1.0, rel_tol=1e-5)


@pytest.mark.asyncio
async def test_hash_provider_morphological_similarity():
    provider = HashEmbeddingProvider(dimension=384)
    q_vec = await provider.embed_query("send invoice to vendor")
    pos_vec = await provider.embed_query("send invoice (invoicing): Send a draft invoice to the recipient via email.")
    neg_vec = await provider.embed_query("escalate dispute (disputes): Escalate an open dispute to PayPal for mediation.")

    pos_sim = sum(a * b for a, b in zip(q_vec, pos_vec))
    neg_sim = sum(a * b for a, b in zip(q_vec, neg_vec))
    assert pos_sim > neg_sim


def test_rrf_prioritizes_dual_hits():
    id_both = uuid.uuid4()
    id_dense_only = uuid.uuid4()
    id_bm25_only = uuid.uuid4()

    dense = [
        SearchCandidate(chunk_id=id_dense_only, text="dense only", cosine_sim=0.9),
        SearchCandidate(chunk_id=id_both, text="both", cosine_sim=0.85),
    ]
    bm25 = [
        SearchCandidate(chunk_id=id_bm25_only, text="bm25 only", bm25_score=1.5),
        SearchCandidate(chunk_id=id_both, text="both", bm25_score=1.2),
    ]
    merged = HybridSearchService.reciprocal_rank_fusion(dense, bm25, top_k=3)
    assert merged[0].chunk_id == id_both


@pytest.mark.asyncio
async def test_reranker_graceful_fallback():
    reranker = CrossEncoderReranker()
    c1 = SearchCandidate(chunk_id=uuid.uuid4(), text="send invoice: Send a draft invoice to the recipient via email")
    c2 = SearchCandidate(chunk_id=uuid.uuid4(), text="verify webhook signature: Verify webhook authenticity")
    results = await reranker.rerank("send invoice to client", [c2, c1], top_k=2)
    assert len(results) == 2
    assert results[0].candidate.chunk_id == c1.chunk_id


# ── 2. Integration Tests (Real PostgreSQL + pgvector) ────────────────────────

@pytest.mark.asyncio
async def test_health_and_tool_catalog_endpoints(api_client: AsyncClient):
    health_resp = await api_client.get("/health")
    assert health_resp.status_code == 200
    health = health_resp.json()
    assert health["status"] == "ok"
    assert health["database"] == "connected"
    assert health["active_tools"] >= 50

    list_resp = await api_client.get("/api/tools")
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["total"] >= 50
    assert {"payments", "invoicing", "analytics", "disputes", "procurement"}.issubset(body["domains"].keys())

    inv_resp = await api_client.get("/api/tools", params={"domain": "invoicing"})
    assert inv_resp.status_code == 200
    assert all(t["domain"] == "invoicing" for t in inv_resp.json()["tools"])

    one_resp = await api_client.get("/api/tools/create_invoice")
    assert one_resp.status_code == 200
    assert one_resp.json()["name"] == "create_invoice"


@pytest.mark.asyncio
async def test_register_duplicate_and_deactivate_tool_lifecycle(api_client: AsyncClient):
    temp_name = f"temp_test_tool_{uuid.uuid4().hex[:8]}"
    payload = {
        "name": temp_name,
        "domain": "procurement",
        "description": "Temporary integration test tool for supplier SLA audit.",
        "schema": {"supplier_id": "string"},
        "endpoint": "/v1/test/sla",
    }

    try:
        create_resp = await api_client.post("/api/tools", json=payload)
        assert create_resp.status_code == 201
        assert create_resp.json()["name"] == temp_name

        dup_resp = await api_client.post("/api/tools", json=payload)
        assert dup_resp.status_code == 409

        del_resp = await api_client.delete(f"/api/tools/{temp_name}")
        assert del_resp.status_code == 200
        assert del_resp.json()["is_active"] is False
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(Tool).where(Tool.name == temp_name))
            await session.commit()


@pytest.mark.asyncio
async def test_semantic_tool_retrieval_accuracy_50_tools(api_client: AsyncClient):
    hits = 0
    for case in BENCHMARK_CASES:
        resp = await api_client.post(
            "/api/tools/retrieve",
            json={"query": case["query"], "top_k": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tools_retrieved"] == 5
        assert data["total_active_tools"] >= 50
        assert data["latency_ms"] >= 0

        retrieved_names = {t["name"] for t in data["tools"]}
        if retrieved_names & set(case["expected_any"]):
            hits += 1

        # Verify explainability fields are populated on every tool
        first = data["tools"][0]
        assert {"cosine_sim", "bm25_score", "rrf_score", "rerank_score", "final_score"}.issubset(first.keys())

    recall_at_5 = hits / len(BENCHMARK_CASES)
    assert recall_at_5 >= 0.875, f"Expected >= 7/8 recall@5, got {hits}/{len(BENCHMARK_CASES)}"


@pytest.mark.asyncio
async def test_scale_stability_150_tools(api_client: AsyncClient):
    """
    Core Thesis Validation:
      Adding 100 synthetic distractor tools (scaling 50 -> 150) must NOT degrade
      top-5 tool retrieval accuracy, and LLM context still receives only 5 tools.
    """
    prefix = f"synth_{uuid.uuid4().hex[:6]}_"
    synthetic_tools = [
        {
            "name": f"{prefix}service_op_{i}",
            "domain": ["crm", "hr", "logistics", "marketing", "support"][i % 5],
            "description": f"Synthetic enterprise microservice operation number {i} for catalog sync and batch metadata tagging.",
            "schema": {"record_id": "string"},
            "endpoint": f"/v1/synthetic/op/{i}",
        }
        for i in range(100)
    ]

    try:
        async with AsyncSessionLocal() as session:
            counts = await upsert_tools_batch(session, synthetic_tools, overwrite_existing=False)
            assert counts["created"] == 100

        hits = 0
        for case in BENCHMARK_CASES:
            resp = await api_client.post(
                "/api/tools/retrieve",
                json={"query": case["query"], "top_k": 5},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["tools_retrieved"] == 5
            assert data["total_active_tools"] >= 150

            retrieved_names = {t["name"] for t in data["tools"]}
            if retrieved_names & set(case["expected_any"]):
                hits += 1

        recall_at_5 = hits / len(BENCHMARK_CASES)
        assert recall_at_5 >= 0.875, f"Scaled 150-tool recall@5 dropped to {hits}/{len(BENCHMARK_CASES)}"
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(Tool).where(Tool.name.like(f"{prefix}%")))
            await session.commit()

