"""
test_phase4_gemini_and_steps.py — Gemini Tool Selection, RAG Reranking, KB Lookup & Pipeline Steps.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.agents.nodes.executor import _select_best_tool
from app.infrastructure.database.models import AuditLog, KBChunk, Session as DBSession
from app.infrastructure.database.session import AsyncSessionLocal
from app.main import app
from app.tools.rag_tool import _rerank_chunks_with_gemini


@pytest_asyncio.fixture
async def api_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _cleanup(session_id: str, doc_name: str | None = None) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AuditLog).where(AuditLog.session_id == session_id))
        await db.execute(delete(DBSession).where(DBSession.id == session_id))
        if doc_name:
            await db.execute(delete(KBChunk).where(KBChunk.document_name == doc_name))
        await db.commit()


@pytest.mark.asyncio
async def test_select_best_tool_with_gemini_and_fallback():
    candidates = [
        {
            "name": "create_invoice",
            "domain": "invoicing",
            "description": "Draft a new invoice.",
            "final_score": 0.91,
        },
        {
            "name": "send_invoice",
            "domain": "invoicing",
            "description": "Send an existing invoice by ID to a recipient email.",
            "final_score": 0.88,
        },
    ]

    mock_json = json.dumps(
        {
            "index": 2,
            "reason": "The user asked to email an existing invoice rather than create a new one.",
        }
    )
    with patch("app.agents.nodes.executor.call_gemini", new=AsyncMock(return_value=mock_json)):
        chosen, reason = await _select_best_tool("send invoice_001 to mike", candidates)
        assert chosen["name"] == "send_invoice"
        assert reason.startswith("Gemini LLM:")

    with patch("app.agents.nodes.executor.call_gemini", new=AsyncMock(return_value=None)):
        chosen, reason = await _select_best_tool("send invoice_001 to mike", candidates)
        assert chosen["name"] == "create_invoice"
        assert "Hybrid RRF rank #1" in reason


@pytest.mark.asyncio
async def test_rerank_chunks_with_gemini_and_fallback():
    chunks = [
        {"document_name": "notes.txt", "section_title": "Misc", "text": "Unrelated memo.", "rrf_score": 0.03},
        {
            "document_name": "SLA.pdf",
            "section_title": "4.2 Penalties",
            "text": "Late deliveries incur a 2% penalty per delayed business day.",
            "rrf_score": 0.02,
        },
    ]

    mock_json = json.dumps({"ranked": [{"index": 2, "score": 9.5}, {"index": 1, "score": 0}]})
    with patch("app.tools.rag_tool.call_gemini", new=AsyncMock(return_value=mock_json)):
        ranked, method = await _rerank_chunks_with_gemini("delivery penalty?", chunks, top_k=2)
        assert method == "gemini_rerank"
        assert len(ranked) == 1
        assert ranked[0]["document_name"] == "SLA.pdf"
        assert ranked[0]["llm_score"] == 9.5

    with patch("app.tools.rag_tool.call_gemini", new=AsyncMock(return_value=None)):
        ranked, method = await _rerank_chunks_with_gemini("delivery penalty?", chunks, top_k=2)
        assert method == "hybrid_rrf"
        assert len(ranked) == 2
        assert ranked[0]["document_name"] == "notes.txt"


@pytest.mark.asyncio
async def test_kb_enrichment_invoice_001_hitl_and_execution_steps(api_client: AsyncClient):
    sid = f"test-p4-steps-{uuid.uuid4().hex[:8]}"
    doc_name = f"test_invoice_001_{uuid.uuid4().hex[:6]}.txt"
    doc_bytes = (
        "Invoice ID: INVOICE_001\n"
        "Recipient: Mike Thompson <mike@acmecorp.com>\n"
        "Total Amount Due: $2,450.00\n"
        "Due Date: 2026-12-01\n"
    ).encode("utf-8")

    try:
        up = await api_client.post(
            "/api/kb/upload",
            files={"file": (doc_name, doc_bytes, "text/plain")},
        )
        assert up.status_code in (200, 201)
        assert up.json()["chunks_created"] >= 1

        docs_res = await api_client.get("/api/kb/documents")
        assert docs_res.status_code == 200
        assert any(d["document_name"] == doc_name for d in docs_res.json()["documents"])

        # Turn 1: send_invoice pauses at HITL after KB lookup
        r1 = await api_client.post(
            "/api/chat",
            json={"session_id": sid, "message": "send this invoice_001 invoice to mike"},
        )
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["domain"] == "invoicing"
        assert d1["tool_used"] in {"send_invoice", "create_invoice"}
        assert d1["requires_confirmation"] is True
        assert d1["extracted_params"].get("recipient") == "mike@acmecorp.com"
        assert d1["extracted_params"].get("amount") == "$2,450.00"

        step_nodes_1 = [s["node"] for s in d1["execution_steps"]]
        assert "intent_classifier" in step_nodes_1
        assert "tool_retriever" in step_nodes_1
        assert "kb_enrichment" in step_nodes_1
        assert "tool_selector" in step_nodes_1
        assert "hitl_gate" in step_nodes_1

        # Turn 2: approve HITL action
        r2 = await api_client.post(
            "/api/chat/confirm",
            json={"session_id": sid, "approved": True},
        )
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["requires_confirmation"] is False
        assert "mike@acmecorp.com" in d2["response"]

        step_nodes_2 = [s["node"] for s in d2["execution_steps"]]
        assert "executor" in step_nodes_2
        assert "synthesizer" in step_nodes_2

        # Trace endpoint must persist execution_steps inside audit trace
        trace_res = await api_client.get(f"/api/sessions/{sid}/trace")
        assert trace_res.status_code == 200
        traces = trace_res.json()["traces"]
        assert len(traces) == 1
        assert len(traces[0]["execution_steps"]) >= 4

        # Delete synthetic KB doc via API
        del_res = await api_client.delete(f"/api/kb/documents/{doc_name}")
        assert del_res.status_code == 200
        assert del_res.json()["chunks_deleted"] >= 1
    finally:
        await _cleanup(sid, doc_name)


@pytest.mark.asyncio
async def test_observability_reports_gemini_status(api_client: AsyncClient):
    res = await api_client.get("/api/system/observability")
    assert res.status_code == 200
    data = res.json()
    assert "gemini_llm" in data
    assert isinstance(data["gemini_llm"]["configured"], bool)
    assert data["gemini_llm"]["model"]
    assert data["gemini_llm"]["embedding_model"]
    assert "vectors_stored" in data["embedding"]
    assert data["embedding"]["vectors_stored"]["tools"] >= 50


@pytest.mark.asyncio
async def test_get_mike_already_sent_invoice_not_cancel(api_client: AsyncClient):
    """Ensure typo 'invoive' and 'already sent' retrieve the invoice cleanly (never cancel_invoice)."""
    sid = f"test-get-mike-{uuid.uuid4().hex[:8]}"
    doc_name = f"test_mike_sent_{uuid.uuid4().hex[:6]}.txt"
    doc_bytes = (
        "Invoice ID: INVOICE_001\n"
        "Recipient: Mike Thompson <mike@acmecorp.com>\n"
        "Total Amount Due: $2,450.00\n"
        "Due Date: 2026-12-01\n"
    ).encode("utf-8")

    try:
        up = await api_client.post(
            "/api/kb/upload",
            files={"file": (doc_name, doc_bytes, "text/plain")},
        )
        assert up.status_code in (200, 201)

        # Force offline Gemini fallback to verify deterministic retrieval & reranking fix too
        with (
            patch("app.agents.nodes.intent_classifier.call_gemini", new=AsyncMock(return_value=None)),
            patch("app.agents.nodes.executor.call_gemini_with_tools", new=AsyncMock(return_value=None)),
            patch("app.agents.nodes.executor.call_gemini", new=AsyncMock(return_value=None)),
            patch("app.agents.nodes.synthesizer.call_gemini", new=AsyncMock(return_value=None)),
        ):
            r = await api_client.post(
                "/api/chat",
                json={"session_id": sid, "message": "get me the mike invoive already sent"},
            )
        assert r.status_code == 200
        d = r.json()
        assert d["domain"] == "invoicing"
        assert d["tool_used"] in {"get_invoice", "list_invoices"}
        assert d["tool_used"] != "cancel_invoice"
        assert d["extracted_params"].get("recipient") == "mike@acmecorp.com"
        assert d["extracted_params"].get("amount") == "$2,450.00"
    finally:
        await _cleanup(sid, doc_name)


@pytest.mark.asyncio
async def test_native_gemini_tool_call_and_confirm_all_with_edited_params(api_client: AsyncClient):
    """Verify native Gemini functionCall binds top-5 tools + confirm_all allows param edits in HITL."""
    sid = f"test-confirm-all-{uuid.uuid4().hex[:8]}"
    mock_fn_call = {
        "name": "get_invoice",
        "args": {"invoice_id": "INVOICE_001", "recipient": "mike@acmecorp.com"},
        "reason": "User asked to retrieve Mike's existing invoice.",
    }
    try:
        with patch(
            "app.agents.nodes.executor.call_gemini_with_tools",
            new=AsyncMock(return_value=mock_fn_call),
        ):
            r1 = await api_client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "message": "get me invoice_001",
                    "require_hitl": True,
                    "confirm_all": True,
                },
            )
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["tool_used"] == "get_invoice"
        assert d1["requires_confirmation"] is True
        assert "Gemini Tool Call" in (d1["pending_action"].get("reason") or "")

        # Approve with edited parameter from UI
        r2 = await api_client.post(
            "/api/chat/confirm",
            json={
                "session_id": sid,
                "approved": True,
                "params": {"invoice_id": "INVOICE_001", "recipient": "mike-updated@acmecorp.com", "amount": "$2,450.00"},
            },
        )
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["requires_confirmation"] is False
        assert "mike-updated@acmecorp.com" in d2["response"]
    finally:
        await _cleanup(sid)


@pytest.mark.asyncio
async def test_multi_doc_entity_disambiguation_and_tool_accuracy(api_client: AsyncClient):
    """Ensure multi-invoice/PO KB docs disambiguate Sarah vs Mike cleanly across tool calls."""
    sid = f"test-multidoc-{uuid.uuid4().hex[:8]}"
    doc_mike = f"invoice_001_mike_{uuid.uuid4().hex[:4]}.txt"
    doc_sarah = f"invoice_002_sarah_{uuid.uuid4().hex[:4]}.txt"
    doc_summary = f"Spend_Summary_{uuid.uuid4().hex[:4]}.txt"

    try:
        for name, content in (
            (
                doc_mike,
                "Invoice ID: INVOICE_001\nRecipient: Mike Thompson <mike@acmecorp.com>\nTotal Amount Due: $2,450.00\n",
            ),
            (
                doc_sarah,
                "Invoice ID: INVOICE_002\nRecipient: Sarah Chen <sarah@globalfreight.com>\nTotal Amount Due: $6,850.00\nDue Date: 2026-12-10\n",
            ),
            (
                doc_summary,
                "Q4 Summary\nSarah Chen: $28,300.00\nMike Thompson: $47,450.00\n",
            ),
        ):
            r = await api_client.post(
                "/api/kb/upload",
                files={"file": (name, content.encode("utf-8"), "text/plain")},
            )
            assert r.status_code in (200, 201)

        res = await api_client.post(
            "/api/chat",
            json={"session_id": sid, "message": "get me the sarah invoice", "require_hitl": False},
        )
        assert res.status_code == 200
        d = res.json()
        assert d["domain"] == "invoicing"
        assert d["tool_used"] in {"get_invoice", "list_invoices"}
        assert d["extracted_params"].get("invoice_id") == "INVOICE_002"
        assert d["extracted_params"].get("recipient") == "sarah@globalfreight.com"
        assert d["extracted_params"].get("amount") == "$6,850.00"

        # Refund against capture ID CAP-7741 must stay in payments -> refund_payment (not disputes)
        r_ref = await api_client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "message": "Issue a partial refund of $300 for capture CAP-7741",
                "require_hitl": False,
            },
        )
        assert r_ref.status_code == 200
        d_ref = r_ref.json()
        assert d_ref["domain"] == "payments"
        assert d_ref["tool_used"] == "refund_payment"
        assert d_ref["extracted_params"].get("capture_id") == "CAP-7741"
        assert d_ref["extracted_params"].get("amount") == "$300"

        # Batch vendor payout must stay in payments -> create_payout_batch (never procurement -> create_vendor)
        doc_batch = f"Vendor_Payout_Batch_{uuid.uuid4().hex[:4]}.txt"
        batch_txt = "Batch Reference: BATCH-2026-1102\nTotal Amount Due: $10,000.00\nDue Date: 2026-11-14\n"
        await api_client.post("/api/kb/upload", files={"file": (doc_batch, batch_txt.encode("utf-8"), "text/plain")})
        try:
            r_batch = await api_client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "message": "Create batch vendor payout BATCH-2026-1102",
                    "require_hitl": False,
                },
            )
            assert r_batch.status_code == 200
            d_batch = r_batch.json()
            assert d_batch["domain"] == "payments"
            assert d_batch["tool_used"] == "create_payout_batch"
            assert d_batch["extracted_params"].get("payout_batch_id") == "BATCH-2026-1102"
            assert d_batch["extracted_params"].get("amount") == "$10,000.00"
        finally:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(KBChunk).where(KBChunk.document_name == doc_batch))
                await db.commit()
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.session_id == sid))
            await db.execute(delete(DBSession).where(DBSession.id == sid))
            await db.execute(delete(KBChunk).where(KBChunk.document_name.in_([doc_mike, doc_sarah, doc_summary])))
            await db.commit()

