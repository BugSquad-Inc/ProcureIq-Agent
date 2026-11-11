"""
test_phase2_agent_core.py — Phase 2 (LangGraph Agent Core, HITL, Multi-turn, RAG & System Search) Verification.
"""
from __future__ import annotations

import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.infrastructure.database.models import AuditLog, KBChunk, Session as DBSession
from app.infrastructure.database.session import AsyncSessionLocal
from app.main import app


@pytest_asyncio.fixture
async def api_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _cleanup_session(session_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AuditLog).where(AuditLog.session_id == session_id))
        await db.execute(delete(DBSession).where(DBSession.id == session_id))
        await db.commit()


@pytest.mark.asyncio
async def test_read_only_analytics_and_dispute_queries(api_client: AsyncClient):
    sid = f"test-ro-{uuid.uuid4().hex[:8]}"
    try:
        r1 = await api_client.post(
            "/api/chat",
            json={"session_id": sid, "message": "What was my total sales volume last month?"},
        )
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["domain"] == "analytics"
        assert d1["tool_used"] == "get_sales_report"
        assert d1["requires_confirmation"] is False
        assert "$48,320.00" in d1["response"]
        assert len(d1["retrieved_tools"]) == 5

        r2 = await api_client.post(
            "/api/chat",
            json={"session_id": sid, "message": "Is there an open dispute from user_123?"},
        )
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["domain"] == "disputes"
        assert d2["tool_used"] in {"get_dispute", "list_disputes"}
        assert d2["requires_confirmation"] is False
        assert "user_123" in d2["response"]
    finally:
        await _cleanup_session(sid)


@pytest.mark.asyncio
async def test_hitl_confirmation_yes_via_chat(api_client: AsyncClient):
    sid = f"test-hitl-yes-{uuid.uuid4().hex[:8]}"
    try:
        r1 = await api_client.post(
            "/api/chat",
            json={"session_id": sid, "message": "Send $500 to john@example.com"},
        )
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["domain"] == "payments"
        assert d1["tool_used"] == "send_payment"
        assert d1["requires_confirmation"] is True
        assert d1["pending_action"] is not None
        assert d1["extracted_params"].get("amount") == "$500"
        assert d1["extracted_params"].get("recipient") == "john@example.com"
        assert "Confirm?" in d1["response"]

        # Verify session endpoint reports pending confirmation
        sess_resp = await api_client.get(f"/api/sessions/{sid}")
        assert sess_resp.status_code == 200
        assert sess_resp.json()["pending_confirmation"] is True

        # User replies "Yes" in natural chat
        r2 = await api_client.post(
            "/api/chat",
            json={"session_id": sid, "message": "Yes"},
        )
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["requires_confirmation"] is False
        assert d2["tool_used"] == "send_payment"
        assert "TXN-88412" in d2["response"]
        assert "john@example.com" in d2["response"]

        # Confirm audit log recorded the executed action
        hist = await api_client.get(f"/api/sessions/{sid}/history")
        assert hist.status_code == 200
        assert hist.json()["total"] == 1
        assert hist.json()["history"][0]["action"] == "tool_called"
    finally:
        await _cleanup_session(sid)


@pytest.mark.asyncio
async def test_hitl_cancel_via_confirm_endpoint(api_client: AsyncClient):
    sid = f"test-hitl-no-{uuid.uuid4().hex[:8]}"
    try:
        r1 = await api_client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "message": "Create a purchase order for $45,000 to Acme Corp for server hardware",
            },
        )
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["domain"] == "procurement"
        assert d1["tool_used"] == "create_purchase_order"
        assert d1["requires_confirmation"] is True
        assert d1["extracted_params"].get("amount") == "$45,000"
        assert d1["extracted_params"].get("vendor") == "Acme Corp"

        # Cancel via explicit /api/chat/confirm endpoint
        c_resp = await api_client.post(
            "/api/chat/confirm",
            json={"session_id": sid, "approved": False},
        )
        assert c_resp.status_code == 200
        c_data = c_resp.json()
        assert c_data["requires_confirmation"] is False
        assert "Cancelled" in c_data["response"]

        # Confirming again when nothing is pending returns 409
        dup_confirm = await api_client.post(
            "/api/chat/confirm",
            json={"session_id": sid, "approved": True},
        )
        assert dup_confirm.status_code == 409

        hist = await api_client.get(f"/api/sessions/{sid}/history")
        assert hist.json()["history"][0]["action"] == "action_cancelled"
    finally:
        await _cleanup_session(sid)


@pytest.mark.asyncio
async def test_system_search_and_multi_turn_history(api_client: AsyncClient):
    sid = f"test-sys-{uuid.uuid4().hex[:8]}"
    try:
        # 1. Tool capability search must route to system_search (not invoicing)
        r1 = await api_client.post(
            "/api/chat",
            json={"session_id": sid, "message": "What tools are available for managing invoices?"},
        )
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["domain"] == "system"
        assert d1["tool_used"] == "system_search"
        assert "invoice" in d1["response"].lower()

        # 2. Request history search
        r2 = await api_client.post(
            "/api/chat",
            json={"session_id": sid, "message": "What was the status of my last request?"},
        )
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["domain"] == "system"
        assert d2["tool_used"] == "system_search"
        assert "system_search" in d2["response"]

        # 3. Session state retains multi-turn messages
        sess = await api_client.get(f"/api/sessions/{sid}")
        assert sess.status_code == 200
        assert sess.json()["turn_count"] >= 4
    finally:
        await _cleanup_session(sid)


@pytest.mark.asyncio
async def test_kb_upload_and_rag_query_via_chat(api_client: AsyncClient):
    sid = f"test-rag-{uuid.uuid4().hex[:8]}"
    doc_name = f"sla_test_{uuid.uuid4().hex[:6]}.txt"
    sla_text = (
        "Enterprise Supplier SLA Section 4.2: All hardware deliveries must arrive within 5 business days. "
        "Late deliveries incur a 2% penalty per delayed day, capped at 10% of the purchase order value."
    )
    try:
        up = await api_client.post(
            "/api/kb/upload",
            files={"file": (doc_name, sla_text.encode("utf-8"), "text/plain")},
        )
        assert up.status_code == 201
        assert up.json()["chunks_created"] >= 1

        chat_resp = await api_client.post(
            "/api/chat",
            json={"session_id": sid, "message": "What does our supplier SLA say about delivery penalties?"},
        )
        assert chat_resp.status_code == 200
        data = chat_resp.json()
        assert data["domain"] == "rag"
        assert data["tool_used"] == "rag_query"
        assert data["sources"] is not None and len(data["sources"]) >= 1
        assert "2% penalty" in data["response"]
        assert doc_name in data["response"]
    finally:
        await _cleanup_session(sid)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(KBChunk).where(KBChunk.document_name == doc_name))
            await db.commit()

