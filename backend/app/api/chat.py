"""
chat.py — Multi-turn Conversational Agent & HITL Confirmation API.

Endpoints:
  POST /api/chat                      — Send a message, get agent response (or HITL prompt)
  POST /api/chat/confirm              — Explicitly approve/cancel a pending HITL action
  GET  /api/sessions/{id}             — Inspect session state, turn count & pending action
  GET  /api/sessions/{id}/history     — Get audit log & conversation turns for a session
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc, select
import structlog

from app.agents.graph import get_durable_graph
from app.core.security import AuthContext, enforce_tool_rbac, get_auth_context
from app.infrastructure.database.models import AuditLog, Session as DBSession
from app.infrastructure.database.session import AsyncSessionLocal

router = APIRouter(prefix="/api", tags=["chat"])
logger = structlog.get_logger("procureiq.api.chat")

_APPROVAL_WORDS = {"yes", "y", "confirm", "approved", "approve", "ok", "okay", "proceed", "go ahead"}
_REJECTION_WORDS = {"no", "n", "cancel", "abort", "stop", "reject", "deny", "nevermind"}
_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9._:-]{1,64}$")
_AMOUNT_VAL_RE = re.compile(r"^\$?\s*([+-]?\d[\d,]*(?:\.\d{1,2})?)\s*$")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = Field(default=None, max_length=64)
    require_hitl: bool = True
    confirm_all: bool = False

    @field_validator("message")
    @classmethod
    def _clean_message(cls, v: str) -> str:
        cleaned = (v or "").strip()
        if not cleaned:
            raise ValueError("Message cannot be empty or whitespace.")
        return cleaned

    @field_validator("session_id")
    @classmethod
    def _validate_session_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            return None
        if not _SESSION_ID_RE.match(cleaned):
            raise ValueError("session_id must be 1-64 alphanumeric, '.', '_', ':', or '-' characters.")
        return cleaned


class ConfirmRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    approved: bool
    params: Optional[Dict[str, Any]] = None

    @field_validator("session_id")
    @classmethod
    def _validate_confirm_session(cls, v: str) -> str:
        cleaned = (v or "").strip()
        if not _SESSION_ID_RE.match(cleaned):
            raise ValueError("session_id must be 1-64 alphanumeric, '.', '_', ':', or '-' characters.")
        return cleaned

    @field_validator("params")
    @classmethod
    def _validate_override_params(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is None:
            return None
        if "amount" in v and v["amount"] not in (None, ""):
            raw = str(v["amount"]).strip()
            if isinstance(v["amount"], (int, float)):
                num = float(v["amount"])
            else:
                m = _AMOUNT_VAL_RE.match(raw)
                if not m:
                    raise ValueError(f"Invalid amount format: '{raw}'. Expected positive number (e.g. '$500.00').")
                num = float(m.group(1).replace(",", ""))
            if num <= 0:
                raise ValueError("Amount must be greater than zero.")
        return v


class ChatResponse(BaseModel):
    session_id: str
    trace_id: Optional[str] = None
    response: str
    domain: Optional[str] = None
    intent: Optional[str] = None
    tool_used: Optional[str] = None
    extracted_params: Dict[str, Any] = Field(default_factory=dict)
    retrieved_tools: List[Dict[str, Any]] = Field(default_factory=list)
    execution_steps: List[Dict[str, Any]] = Field(default_factory=list)
    retrieval_latency_ms: Optional[float] = None
    requires_confirmation: bool = False
    pending_action: Optional[Dict[str, Any]] = None
    sources: Optional[list] = None


async def _ensure_session_row(session_id: str, tenant_id: str = "default") -> None:
    """Create or verify ownership of the PostgreSQL `sessions` metadata row."""
    async with AsyncSessionLocal() as db:
        existing = await db.get(DBSession, session_id)
        if existing is None:
            db.add(DBSession(id=session_id, tenant_id=tenant_id, metadata_={"channel": "api"}))
        else:
            if existing.tenant_id != tenant_id:
                raise HTTPException(
                    status_code=403,
                    detail=f"Tenant access denied for session '{session_id}'.",
                )
            existing.metadata_ = {**(existing.metadata_ or {}), "last_channel": "api"}
        await db.commit()


async def _verify_session_tenant(session_id: str, tenant_id: str) -> None:
    """Verify existing session row belongs to `tenant_id` (403 on cross-tenant access)."""
    async with AsyncSessionLocal() as db:
        existing = await db.get(DBSession, session_id)
        if existing is not None and existing.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403,
                detail=f"Tenant access denied for session '{session_id}'.",
            )


def _format_chat_response(session_id: str, result: Dict[str, Any]) -> ChatResponse:
    interrupts = result.get("__interrupt__")
    steps = list(result.get("execution_steps") or [])
    if interrupts:
        first_int = interrupts[0]
        payload = getattr(first_int, "value", first_int)
        if not isinstance(payload, dict):
            payload = {"confirmation_prompt": str(payload)}
        prompt_text = payload.get("confirmation_prompt") or (
            f"Confirm running `{payload.get('tool')}`? [Yes/No]"
        )
        steps.append(
            {
                "node": "hitl_gate",
                "title": "HITL Safety Gate",
                "status": "awaiting_approval",
                "duration_ms": 0.0,
                "detail": f"Paused before executing `{payload.get('tool')}` — waiting for user confirmation",
            }
        )
        return ChatResponse(
            session_id=session_id,
            trace_id=result.get("trace_id"),
            response=prompt_text,
            domain=payload.get("domain") or result.get("domain"),
            intent=result.get("intent"),
            tool_used=payload.get("tool") or result.get("selected_tool"),
            extracted_params=payload.get("params") or result.get("extracted_params") or {},
            retrieved_tools=_compact_retrieved_tools(result.get("retrieved_tools")),
            execution_steps=steps,
            retrieval_latency_ms=result.get("retrieval_latency_ms"),
            requires_confirmation=True,
            pending_action={
                "tool": payload.get("tool"),
                "domain": payload.get("domain"),
                "description": payload.get("description", ""),
                "reason": payload.get("reason"),
                "kb_sources": payload.get("kb_sources") or [],
                "params": payload.get("params") or {},
            },
            sources=None,
        )

    response_text = result.get("final_response") or "I could not process your request. Please try again."
    tool_result = result.get("tool_result") or {}
    sources = tool_result.get("sources") if isinstance(tool_result, dict) else None

    return ChatResponse(
        session_id=session_id,
        trace_id=result.get("trace_id"),
        response=response_text,
        domain=result.get("domain"),
        intent=result.get("intent"),
        tool_used=result.get("selected_tool"),
        extracted_params=result.get("extracted_params") or {},
        retrieved_tools=_compact_retrieved_tools(result.get("retrieved_tools")),
        execution_steps=steps,
        retrieval_latency_ms=result.get("retrieval_latency_ms"),
        requires_confirmation=False,
        pending_action=None,
        sources=sources,
    )


def _compact_retrieved_tools(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if not tools:
        return []
    return [
        {
            "name": t.get("name"),
            "domain": t.get("domain"),
            "final_score": t.get("final_score", 0.0),
        }
        for t in tools
    ]


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, auth: AuthContext = Depends(get_auth_context)):
    """
    Send a user message through the durable LangGraph StateGraph.
    Automatically handles multi-turn state, tenant isolation, RBAC, and HITL confirmation replies.
    """
    session_id = req.session_id or str(uuid.uuid4())
    await _ensure_session_row(session_id, tenant_id=auth.tenant_id)

    graph = get_durable_graph()
    config = {"configurable": {"thread_id": session_id}}

    try:
        snapshot = await graph.aget_state(config)
        is_waiting_hitl = bool(snapshot and snapshot.next and "hitl_gate" in snapshot.next)

        if is_waiting_hitl:
            normalized = req.message.strip().lower().rstrip(".!?")
            if normalized in _APPROVAL_WORDS:
                pending = (snapshot.values or {}).get("pending_action") or {}
                enforce_tool_rbac(pending.get("tool"), pending.get("params") or {}, auth)
                result = await graph.ainvoke(
                    Command(resume={"approved": True, "approver_role": auth.role}),
                    config=config,
                )
                return _format_chat_response(session_id, result)
            if normalized in _REJECTION_WORDS:
                result = await graph.ainvoke(Command(resume={"approved": False}), config=config)
                return _format_chat_response(session_id, result)
            # User asked a new unrelated question: clear pending gate cleanly first.
            await graph.ainvoke(Command(resume={"approved": False}), config=config)

        prior_domain = snapshot.values.get("domain") if (snapshot and snapshot.values) else None
        trace_id = str(uuid.uuid4())
        initial_state = {
            "messages": [HumanMessage(content=req.message)],
            "domain": prior_domain,
            "intent": None,
            "retrieved_tools": [],
            "selected_tool": None,
            "extracted_params": {},
            "tool_result": None,
            "tool_error": None,
            "require_hitl": req.require_hitl,
            "confirm_all": req.confirm_all,
            "requires_confirmation": False,
            "hitl_approved": None,
            "pending_action": None,
            "execution_steps": [{"__reset__": True}],
            "final_response": None,
            "session_id": session_id,
            "tenant_id": auth.tenant_id,
            "user_role": auth.role,
            "trace_id": trace_id,
            "retrieval_latency_ms": None,
        }
        run_config = {
            **config,
            "run_name": "procureiq_agent_turn",
            "metadata": {
                "session_id": session_id,
                "tenant_id": auth.tenant_id,
                "role": auth.role,
                "trace_id": trace_id,
            },
        }
        result = await graph.ainvoke(initial_state, config=run_config)
        return _format_chat_response(session_id, result)
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.error("agent_invocation_failed", error=str(exc), session=session_id)
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}")


@router.post("/chat/confirm", response_model=ChatResponse)
async def confirm_pending_action(req: ConfirmRequest, auth: AuthContext = Depends(get_auth_context)):
    """Explicitly approve or cancel a pending HITL write action for `session_id`."""
    await _verify_session_tenant(req.session_id, auth.tenant_id)
    graph = get_durable_graph()
    config = {"configurable": {"thread_id": req.session_id}}

    snapshot = await graph.aget_state(config)
    if not (snapshot and snapshot.next and "hitl_gate" in snapshot.next):
        raise HTTPException(
            status_code=409,
            detail=f"No pending confirmation found for session '{req.session_id}'.",
        )

    if req.approved:
        pending = (snapshot.values or {}).get("pending_action") or {}
        merged_params = {**(pending.get("params") or {}), **(req.params or {})}
        enforce_tool_rbac(pending.get("tool"), merged_params, auth)

    try:
        resume_payload: Dict[str, Any] = {"approved": req.approved, "approver_role": auth.role}
        if req.params is not None:
            resume_payload["params"] = req.params
        result = await graph.ainvoke(Command(resume=resume_payload), config=config)
        return _format_chat_response(req.session_id, result)
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.error("hitl_confirm_failed", error=str(exc), session=req.session_id)
        raise HTTPException(status_code=500, detail=f"Confirmation error: {exc}")


@router.get("/sessions/{session_id}")
async def get_session_state(session_id: str, auth: AuthContext = Depends(get_auth_context)):
    """Inspect current LangGraph checkpoint state and pending HITL actions."""
    await _verify_session_tenant(session_id, auth.tenant_id)
    graph = get_durable_graph()
    config = {"configurable": {"thread_id": session_id}}
    snapshot = await graph.aget_state(config)

    values = snapshot.values if (snapshot and snapshot.values) else {}
    msgs = values.get("messages") or []
    turns = [
        {
            "role": "user" if isinstance(m, HumanMessage) else "assistant" if isinstance(m, AIMessage) else "system",
            "content": str(m.content),
        }
        for m in msgs
    ]
    is_pending = bool(snapshot and snapshot.next and "hitl_gate" in snapshot.next)

    return {
        "session_id": session_id,
        "domain": values.get("domain"),
        "turn_count": len(turns),
        "pending_confirmation": is_pending,
        "pending_action": values.get("pending_action") if is_pending else None,
        "messages": turns,
    }


@router.get("/sessions/{session_id}/history")
async def get_history(session_id: str, auth: AuthContext = Depends(get_auth_context)):
    """Return tenant-scoped audit log entries for a session."""
    await _verify_session_tenant(session_id, auth.tenant_id)
    async with AsyncSessionLocal() as session:
        stmt = (
            select(AuditLog)
            .where(
                AuditLog.session_id == session_id,
                AuditLog.tenant_id == auth.tenant_id,
            )
            .order_by(desc(AuditLog.created_at))
            .limit(20)
        )
        result = await session.execute(stmt)
        logs = result.scalars().all()

    return {
        "session_id": session_id,
        "total": len(logs),
        "history": [
            {
                "action": log.action,
                "tool": log.tool_name,
                "domain": log.domain,
                "payload": log.payload,
                "result": log.result_summary,
                "timestamp": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }
