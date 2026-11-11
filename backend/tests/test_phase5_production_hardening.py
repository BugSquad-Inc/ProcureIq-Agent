"""
test_phase5_production_hardening.py — Phase 5 Production Readiness Verification.

Verifies:
  1. Durable PostgreSQL LangGraph Checkpointer survives full graph rebuild / server restart
  2. Multi-tenant KB & session isolation (403 on cross-tenant access)
  3. RBAC enforcement: Finance VP gate on PO approvals > $25,000 + viewer restrictions
  4. HS256 JWT token issuance, verification, tampered rejection, and X-API-Key auth (401)
  5. Sliding-window per-IP rate limiting middleware (429 Retry-After)
"""
from __future__ import annotations

import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from langgraph.types import Command
from langchain_core.messages import HumanMessage
from sqlalchemy import delete

from app.agents.graph import build_graph
from app.agents.postgres_checkpointer import PostgresCheckpointSaver
from app.config import get_settings
from app.infrastructure.database.models import (
    AgentCheckpoint,
    AgentCheckpointBlob,
    AgentCheckpointWrite,
    AuditLog,
    KBChunk,
    Session as DBSession,
)
from app.infrastructure.database.session import AsyncSessionLocal
from app.main import app


@pytest_asyncio.fixture
async def api_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _cleanup_thread(session_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AgentCheckpointWrite).where(AgentCheckpointWrite.thread_id == session_id))
        await db.execute(delete(AgentCheckpointBlob).where(AgentCheckpointBlob.thread_id == session_id))
        await db.execute(delete(AgentCheckpoint).where(AgentCheckpoint.thread_id == session_id))
        await db.execute(delete(AuditLog).where(AuditLog.session_id == session_id))
        await db.execute(delete(DBSession).where(DBSession.id == session_id))
        await db.commit()


async def _cleanup_kb_doc(doc_name: str, tenant_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(KBChunk).where(
                KBChunk.document_name == doc_name,
                KBChunk.tenant_id == tenant_id,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_durable_postgres_checkpointer_survives_graph_rebuild():
    sid = f"test-durable-{uuid.uuid4().hex[:8]}"
    try:
        # Graph instance #1 pauses in HITL gate and writes checkpoint to PostgreSQL
        graph_before_restart = build_graph(checkpointer=PostgresCheckpointSaver())
        config = {"configurable": {"thread_id": sid}}
        paused = await graph_before_restart.ainvoke(
            {
                "messages": [HumanMessage(content="Send $500 to john@example.com")],
                "domain": None,
                "intent": None,
                "retrieved_tools": [],
                "selected_tool": None,
                "extracted_params": {},
                "tool_result": None,
                "tool_error": None,
                "require_hitl": True,
                "confirm_all": False,
                "requires_confirmation": False,
                "hitl_approved": None,
                "pending_action": None,
                "execution_steps": [],
                "final_response": None,
                "session_id": sid,
                "tenant_id": "default",
                "user_role": "finance_vp",
                "trace_id": "trace-p5-cp",
                "retrieval_latency_ms": None,
            },
            config=config,
        )
        assert "__interrupt__" in paused

        # Simulate process restart with a brand-new checkpointer + compiled graph instance
        graph_after_restart = build_graph(checkpointer=PostgresCheckpointSaver())
        snapshot = await graph_after_restart.aget_state(config)
        assert snapshot is not None
        assert "hitl_gate" in (snapshot.next or ())
        assert snapshot.values["pending_action"]["tool"] == "send_payment"

        resumed = await graph_after_restart.ainvoke(
            Command(resume={"approved": True}),
            config=config,
        )
        assert resumed["selected_tool"] == "send_payment"
        assert resumed["tool_result"]["status"] in {"COMPLETED", "SUCCESS"}
        assert "$500" in resumed["final_response"]
    finally:
        await _cleanup_thread(sid)


@pytest.mark.asyncio
async def test_multi_tenant_kb_and_session_isolation(api_client: AsyncClient):
    doc_a = f"alpha_secret_{uuid.uuid4().hex[:6]}.txt"
    doc_b = f"beta_secret_{uuid.uuid4().hex[:6]}.txt"
    sid_a = f"test-t-alpha-{uuid.uuid4().hex[:6]}"
    headers_a = {"X-Tenant-ID": "tenant-alpha", "X-User-Role": "operator"}
    headers_b = {"X-Tenant-ID": "tenant-beta", "X-User-Role": "operator"}

    try:
        up_a = await api_client.post(
            "/api/kb/upload",
            headers=headers_a,
            files={"file": (doc_a, b"Confidential Alpha Policy Code: ALPHA-TOKEN-991.", "text/plain")},
        )
        assert up_a.status_code == 201
        assert up_a.json()["tenant_id"] == "tenant-alpha"

        up_b = await api_client.post(
            "/api/kb/upload",
            headers=headers_b,
            files={"file": (doc_b, b"Confidential Beta Policy Code: BETA-TOKEN-772.", "text/plain")},
        )
        assert up_b.status_code == 201

        list_a = (await api_client.get("/api/kb/documents", headers=headers_a)).json()
        names_a = {d["document_name"] for d in list_a["documents"]}
        assert doc_a in names_a
        assert doc_b not in names_a

        # Tenant Beta RAG search must NOT retrieve Tenant Alpha's secret document
        rag_b = await api_client.post(
            "/api/chat",
            headers=headers_b,
            json={"session_id": f"{sid_a}-b", "message": "According to our policy, what is the ALPHA-TOKEN-991 code?"},
        )
        assert rag_b.status_code == 200
        assert doc_a not in str(rag_b.json().get("sources") or [])

        # Session created by Alpha must return 403 when accessed by Beta
        create_a = await api_client.post(
            "/api/chat",
            headers=headers_a,
            json={"session_id": sid_a, "message": "Check account balance"},
        )
        assert create_a.status_code == 200

        cross_state = await api_client.get(f"/api/sessions/{sid_a}", headers=headers_b)
        assert cross_state.status_code == 403
        cross_hist = await api_client.get(f"/api/sessions/{sid_a}/history", headers=headers_b)
        assert cross_hist.status_code == 403
        cross_trace = await api_client.get(f"/api/sessions/{sid_a}/trace", headers=headers_b)
        assert cross_trace.status_code == 403
    finally:
        await _cleanup_thread(sid_a)
        await _cleanup_thread(f"{sid_a}-b")
        await _cleanup_kb_doc(doc_a, "tenant-alpha")
        await _cleanup_kb_doc(doc_b, "tenant-beta")


@pytest.mark.asyncio
async def test_rbac_po_vp_threshold_and_viewer_restrictions(api_client: AsyncClient):
    sid_hitl = f"test-rbac-hitl-{uuid.uuid4().hex[:6]}"
    sid_direct = f"test-rbac-dir-{uuid.uuid4().hex[:6]}"
    try:
        # 1. Viewer cannot upload docs or reset breakers
        res_viewer = await api_client.post(
            "/api/kb/upload",
            headers={"X-User-Role": "viewer"},
            files={"file": ("viewer_blocked.txt", b"Hello", "text/plain")},
        )
        assert res_viewer.status_code == 403

        res_reset = await api_client.post(
            "/api/system/circuit-breakers/reset",
            headers={"X-User-Role": "operator"},
        )
        assert res_reset.status_code == 403

        # 2. Operator cannot bypass HITL to approve > $25,000 PO
        res_direct = await api_client.post(
            "/api/chat",
            headers={"X-User-Role": "operator"},
            json={
                "session_id": sid_direct,
                "message": "Approve purchase order PO-2026-0301 for $32,000",
                "require_hitl": False,
            },
        )
        assert res_direct.status_code == 403
        assert "finance_vp" in res_direct.json()["detail"]

        # 3. With HITL paused, operator is blocked at /chat/confirm -> finance_vp succeeds!
        r_pause = await api_client.post(
            "/api/chat",
            headers={"X-User-Role": "operator"},
            json={"session_id": sid_hitl, "message": "Approve purchase order PO-2026-0301 for $32,000"},
        )
        assert r_pause.status_code == 200
        assert r_pause.json()["requires_confirmation"] is True
        assert r_pause.json()["tool_used"] == "approve_purchase_order"

        r_op_confirm = await api_client.post(
            "/api/chat/confirm",
            headers={"X-User-Role": "operator"},
            json={"session_id": sid_hitl, "approved": True},
        )
        assert r_op_confirm.status_code == 403

        r_vp_confirm = await api_client.post(
            "/api/chat/confirm",
            headers={"X-User-Role": "finance_vp"},
            json={"session_id": sid_hitl, "approved": True},
        )
        assert r_vp_confirm.status_code == 200
        assert "approve_purchase_order" == r_vp_confirm.json()["tool_used"]
    finally:
        await _cleanup_thread(sid_hitl)
        await _cleanup_thread(sid_direct)


@pytest.mark.asyncio
async def test_jwt_and_api_key_auth_enforcement(api_client: AsyncClient):
    settings = get_settings()
    app.state.auth_enabled_override = True
    try:
        # Missing credentials -> 401
        r_unauth = await api_client.get("/api/tools")
        assert r_unauth.status_code == 401

        # Token minting without secret when auth enabled -> 401
        r_bad_mint = await api_client.post(
            "/api/auth/token",
            json={"user_id": "alice", "tenant_id": "acme", "role": "finance_vp"},
        )
        assert r_bad_mint.status_code == 401

        # Token minting WITH secret -> 200
        r_mint = await api_client.post(
            "/api/auth/token",
            json={
                "user_id": "alice",
                "tenant_id": "acme",
                "role": "finance_vp",
                "secret": settings.auth_secret_key,
            },
        )
        assert r_mint.status_code == 200
        token = r_mint.json()["access_token"]

        # Valid JWT -> 200
        r_me = await api_client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r_me.status_code == 200
        assert r_me.json()["tenant_id"] == "acme"
        assert r_me.json()["role"] == "finance_vp"
        assert r_me.json()["auth_method"] == "jwt"

        # Tampered JWT -> 401
        r_tampered = await api_client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}x"},
        )
        assert r_tampered.status_code == 401
    finally:
        app.state.auth_enabled_override = None


@pytest.mark.asyncio
async def test_rate_limit_middleware_returns_429(api_client: AsyncClient):
    app.state.rate_limit_rpm_override = 3
    try:
        ip_headers = {"X-Forwarded-For": f"10.0.99.{uuid.uuid4().int % 200 + 10}"}
        for _ in range(3):
            ok_res = await api_client.get("/api/auth/me", headers=ip_headers)
            assert ok_res.status_code == 200

        blocked = await api_client.get("/api/auth/me", headers=ip_headers)
        assert blocked.status_code == 429
        assert blocked.headers.get("Retry-After") == "60"
    finally:
        app.state.rate_limit_rpm_override = None



@pytest.mark.asyncio
async def test_irrelevant_query_and_greeting_handled_without_tool_execution(api_client: AsyncClient):
    sids = [f"test-oos-{i}-{uuid.uuid4().hex[:6]}" for i in range(3)]
    try:
        r_weather = await api_client.post(
            "/api/chat",
            json={"session_id": sids[0], "message": "What is the weather in Tokyo tomorrow?"},
        )
        assert r_weather.status_code == 200
        d1 = r_weather.json()
        assert d1["domain"] == "out_of_scope"
        assert d1["tool_used"] is None
        assert d1["requires_confirmation"] is False
        assert "Payments, Invoicing, Procurement" in d1["response"]

        r_greet = await api_client.post(
            "/api/chat",
            json={"session_id": sids[1], "message": "Hello!"},
        )
        assert r_greet.status_code == 200
        d2 = r_greet.json()
        assert d2["domain"] == "out_of_scope"
        assert d2["tool_used"] is None
        assert "ProcureIQ" in d2["response"]

        # Semantic fallback out-of-scope query (even without explicit off-topic keyword)
        r_sem = await api_client.post(
            "/api/chat",
            json={
                "session_id": sids[2],
                "message": "Explain the biology of photosynthesis and chlorophyll in oak trees",
            },
        )
        assert r_sem.status_code == 200
        d3 = r_sem.json()
        assert d3["domain"] == "out_of_scope"
        assert d3["tool_used"] is None
        assert d3["requires_confirmation"] is False
    finally:
        for sid in sids:
            await _cleanup_thread(sid)


@pytest.mark.asyncio
async def test_input_and_payload_validation_errors(api_client: AsyncClient):
    # 1. Whitespace-only message -> 422 with clean string detail
    r_blank = await api_client.post("/api/chat", json={"message": "    "})
    assert r_blank.status_code == 422
    assert isinstance(r_blank.json()["detail"], str)

    # 2. Oversized or path-unsafe session_id -> 422
    r_bad_sid = await api_client.post(
        "/api/chat",
        json={"session_id": "../bad/session", "message": "Check account balance"},
    )
    assert r_bad_sid.status_code == 422

    # 3. Unsupported upload extension (.exe) -> 400
    r_bad_ext = await api_client.post(
        "/api/kb/upload",
        files={"file": ("malware.exe", b"MZbinary", "application/octet-stream")},
    )
    assert r_bad_ext.status_code == 400
    assert "Unsupported file type" in r_bad_ext.json()["detail"]

    # 4. Empty upload -> 400
    r_empty = await api_client.post(
        "/api/kb/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert r_empty.status_code == 400

    # 5. Negative amount override on confirm -> 422
    r_neg_amt = await api_client.post(
        "/api/chat/confirm",
        json={"session_id": "valid-sid-1", "approved": True, "params": {"amount": "-250"}},
    )
    assert r_neg_amt.status_code == 422

    # 6. Invalid tool name slug -> 422
    r_bad_tool = await api_client.post(
        "/api/tools",
        json={"name": "Invalid Tool Name!", "domain": "payments", "description": "Valid test description"},
    )
    assert r_bad_tool.status_code == 422
