"""
test_phase3_resilience_and_scale.py — Sprint 4 (Circuit Breaker, Trace/Observability, 500-Tool Scale) Tests.
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.embedding.hash_provider import HashEmbeddingProvider
from app.core.resilience import CircuitBreaker, CircuitBreakerRegistry, CircuitOpenError
from app.infrastructure.database.models import AuditLog, Session as DBSession, Tool
from app.infrastructure.database.session import AsyncSessionLocal
from app.main import app
from app.tools.registry import upsert_tools_batch


@pytest_asyncio.fixture
async def api_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def test_circuit_breaker_state_transitions():
    cb = CircuitBreaker(service="test_svc", failure_threshold=2, recovery_timeout_sec=0.05)
    assert cb.state == "closed"

    cb.allow_request()
    cb.record_failure()
    assert cb.state == "closed"

    cb.record_failure()
    assert cb.state == "open"

    with pytest.raises(CircuitOpenError):
        cb.allow_request()

    # Wait past recovery timeout -> transitions to half_open on allow_request -> closed on success
    import time
    time.sleep(0.08)
    cb.allow_request()
    assert cb.state == "half_open"
    cb.record_success()
    assert cb.state == "closed"
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_error_recovery_circuit_breaker_and_trace_endpoint(api_client: AsyncClient):
    sid = f"test-cb-{uuid.uuid4().hex[:8]}"
    CircuitBreakerRegistry.reset_all()
    try:
        # Simulate downstream PayPal API outage (503) for 3 requests to trip breaker
        with patch(
            "app.agents.nodes.executor.execute_paypal_tool",
            new=AsyncMock(side_effect=RuntimeError("PayPal 503 Service Unavailable")),
        ):
            for _ in range(3):
                resp = await api_client.post(
                    "/api/chat",
                    json={"session_id": sid, "message": "What was my total sales volume last month?"},
                )
                assert resp.status_code == 200
                assert "issue running" in resp.json()["response"].lower()

        # Verify circuit breaker for paypal_api is now OPEN via observability API
        obs_resp = await api_client.get("/api/system/observability")
        assert obs_resp.status_code == 200
        obs = obs_resp.json()
        assert obs["circuit_breakers"]["paypal_api"]["state"] == "open"

        # 4th call fails fast without even hitting adapter because circuit is OPEN
        fast_fail = await api_client.post(
            "/api/chat",
            json={"session_id": sid, "message": "Check current available account balance"},
        )
        assert fast_fail.status_code == 200
        assert "circuit breaker is open" in fast_fail.json()["response"].lower()

        # Verify session trace captured all events + candidate explainability + circuit_open flag
        trace_resp = await api_client.get(f"/api/sessions/{sid}/trace")
        assert trace_resp.status_code == 200
        trace_data = trace_resp.json()
        assert trace_data["total_events"] == 4
        assert trace_data["traces"][-1]["circuit_open"] is True
        assert len(trace_data["traces"][0]["candidates_considered"]) >= 1

        # Reset circuit breakers and verify recovery works
        reset_resp = await api_client.post("/api/system/circuit-breakers/reset")
        assert reset_resp.status_code == 200
        assert reset_resp.json()["circuit_breakers"]["paypal_api"]["state"] == "closed"
    finally:
        CircuitBreakerRegistry.reset_all()
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.session_id == sid))
            await db.execute(delete(DBSession).where(DBSession.id == sid))
            await db.commit()


@pytest.mark.asyncio
async def test_500_tool_scale_benchmark_recall_and_latency(api_client: AsyncClient):
    """
    Scale the database from 50 tools -> 500 tools (450 multi-service connectors)
    and prove top-5 retrieval precision remains >= 87.5% with low DB latency.
    """
    benchmark_cases = [
        {"query": "Send an invoice for $50 to client@example.com", "expected_any": {"send_invoice", "create_invoice"}},
        {"query": "What was my total sales volume last month?", "expected_any": {"get_sales_report", "get_revenue_breakdown"}},
        {"query": "Is there a dispute open from user_123?", "expected_any": {"get_dispute", "list_disputes"}},
        {"query": "Create a purchase order for server hardware from Acme Corp", "expected_any": {"create_purchase_order"}},
        {"query": "Issue a full or partial refund for a customer payment", "expected_any": {"refund_payment"}},
        {"query": "Check current available PayPal account balance", "expected_any": {"get_balance"}},
        {"query": "Send batch payouts to multiple vendors and contractors", "expected_any": {"create_payout_batch"}},
        {"query": "Flag price mismatch between vendor invoice and purchase order", "expected_any": {"flag_invoice_discrepancy"}},
    ]

    prefix = f"scale500_{uuid.uuid4().hex[:6]}_"
    platforms = [
        ("crm", "Salesforce", ["contact", "deal", "lead", "account", "opportunity"]),
        ("devops", "Kubernetes", ["cluster", "deployment", "bucket", "lambda", "pod"]),
        ("hr", "Workday", ["employee", "payroll", "leave_balance", "onboarding", "timesheet"]),
        ("support", "Zendesk", ["ticket", "sprint", "queue", "macro", "knowledge_article"]),
        ("logistics", "FedEx", ["waybill", "warehouse_bin", "freight_quote", "customs", "carrier"]),
    ]
    verbs = ["sync", "archive", "tag", "assign", "export", "preview", "audit", "clone", "notify", "merge", "validate", "schedule", "close", "reopen", "link", "unlink", "snapshot", "restore"]
    synthetic_450 = []
    for i in range(450):
        dom, plat, nouns = platforms[i % len(platforms)]
        noun = nouns[(i // len(platforms)) % len(nouns)]
        verb = verbs[(i // (len(platforms) * len(nouns))) % len(verbs)]
        synthetic_450.append(
            {
                "name": f"{prefix}{dom}_{verb}_{noun}_{i:03d}",
                "domain": dom,
                "description": f"{verb.title()} {noun.replace('_', ' ')} records in {plat} connector #{i:03d}.",
                "schema": {"record_id": "string"},
                "endpoint": f"/v1/{dom}/{noun}/{verb}",
            }
        )

    try:
        # Benchmark PostgreSQL pgvector HNSW + BM25 scaling locally without hitting external LLM rate limits
        offline_provider = HashEmbeddingProvider()
        with patch(
            "app.core.embedding.factory.EmbeddingProviderFactory.get_provider",
            return_value=offline_provider,
        ):
            async with AsyncSessionLocal() as db:
                counts = await upsert_tools_batch(db, synthetic_450, overwrite_existing=False)
                assert counts["created"] == 450

            hits = 0
            latencies = []
            for case in benchmark_cases:
                resp = await api_client.post(
                    "/api/tools/retrieve",
                    json={"query": case["query"], "top_k": 5},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["tools_retrieved"] == 5
                assert data["total_active_tools"] >= 500
                latencies.append(data["latency_ms"])
                retrieved_names = {t["name"] for t in data["tools"]}
                if retrieved_names & set(case["expected_any"]):
                    hits += 1

            recall_at_5 = hits / len(benchmark_cases)
            avg_latency = sum(latencies) / len(latencies)
            assert recall_at_5 >= 0.875, f"500-tool Recall@5 dropped to {hits}/{len(benchmark_cases)}"
            assert avg_latency < 200.0, f"500-tool mean latency too high: {avg_latency} ms"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Tool).where(Tool.name.like(f"{prefix}%")))
            await db.commit()
