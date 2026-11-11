"""
executor.py — Tool Selection, KB Entity Enrichment, Parameter Extraction & Resilient Execution.

Contains:
  - `tool_selector_node`: Chooses best tool from `retrieved_tools`, extracts
    parameters from conversation + uploaded KB documents (`kb_chunks`), and
    flags mutating write operations for HITL.
  - `executor_node`: Runs the selected tool guarded by CircuitBreaker + backoff
    retry (`run_with_resilience`) and writes step-by-step trace data to AuditLog.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import structlog
from langchain_core.messages import HumanMessage
from sqlalchemy import desc, or_, select

from app.agents.state import AgentState
from app.core.hybrid_search import normalize_query_text
from app.core.llm_client import call_gemini, call_gemini_with_tools, parse_json_response
from app.core.resilience import CircuitOpenError, run_with_resilience
from app.infrastructure.database.models import AuditLog, KBChunk
from app.infrastructure.database.session import AsyncSessionLocal
from app.tools.paypal_adapter import execute_paypal_tool, is_write_tool

logger = structlog.get_logger("procureiq.executor")


async def tool_selector_node(state: AgentState) -> Dict[str, Any]:
    """
    Pick the best tool from `retrieved_tools`, extract structured parameters,
    enrich missing details (e.g., invoice_001 / Mike's email) from uploaded KB docs,
    and determine whether Human-in-the-Loop confirmation is required.
    """
    started = time.perf_counter()
    if state.get("domain") == "out_of_scope":
        return {
            "selected_tool": None,
            "extracted_params": {},
            "requires_confirmation": False,
            "pending_action": None,
            "tool_error": "OUT_OF_SCOPE",
            "execution_steps": [
                {
                    "node": "tool_selector",
                    "title": "Out-of-Scope Guard",
                    "status": "completed",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "detail": "Declined out-of-scope request safely without running any tool.",
                }
            ],
        }

    retrieved_tools = state.get("retrieved_tools", [])
    if not retrieved_tools:
        return {
            "selected_tool": None,
            "extracted_params": {},
            "requires_confirmation": False,
            "pending_action": None,
            "tool_error": "No matching tools found for this request.",
            "execution_steps": [
                {
                    "node": "tool_selector",
                    "title": "Tool Selector",
                    "status": "failed",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "detail": "No candidate tools matched this query.",
                }
            ],
        }

    user_msg = normalize_query_text(_last_user_message(state["messages"]))
    domain = state.get("domain") or "general"
    tenant_id = state.get("tenant_id") or "default"

    # 1. Pre-extract deterministic params + resolve KB / Audit context BEFORE calling Gemini
    params = _regex_extract_params(user_msg)
    kb_started = time.perf_counter()
    params, kb_sources, kb_context = await _enrich_params_from_kb(
        domain=domain,
        user_message=user_msg,
        params=params,
        tenant_id=tenant_id,
    )
    kb_ms = round((time.perf_counter() - kb_started) * 1000, 2)

    # 2. Ask Gemini via native Function Calling across the top-5 retrieved tools + KB context
    tool_by_name = {t["name"]: t for t in retrieved_tools if t.get("name")}
    gemini_call = await call_gemini_with_tools(
        user_message=user_msg,
        candidate_tools=retrieved_tools,
        kb_context=kb_context,
    )

    if gemini_call and gemini_call.get("name") in tool_by_name:
        best_tool = tool_by_name[gemini_call["name"]]
        tool_name = best_tool["name"]
        selection_reason = f"Gemini Tool Call: {gemini_call['reason']}"
        for k, v in (gemini_call.get("args") or {}).items():
            if v not in (None, "", []):
                # Normalize synonym keys cleanly without overwriting verified KB fields
                target_key = "recipient" if k == "recipient_email" else k
                if target_key not in params or target_key == "status":
                    params[target_key] = v
    else:
        best_tool, selection_reason = await _select_best_tool(user_msg, retrieved_tools)
        tool_name = best_tool.get("name", "unknown")
        # Run schema extraction if no native function call occurred
        extra_params = await _extract_parameters(user_msg, best_tool)
        for k, v in extra_params.items():
            if v not in (None, "", []) and k not in params:
                params[k] = v

    if tool_name in {"rag_query", "system_search"}:
        kb_sources = []

    require_hitl = state.get("require_hitl", True)
    confirm_all = bool(state.get("confirm_all", False))
    needs_confirm = bool(
        require_hitl and (confirm_all or is_write_tool(tool_name))
    )
    pending = (
        {
            "tool": tool_name,
            "domain": state.get("domain") or best_tool.get("domain"),
            "description": best_tool.get("description", ""),
            "reason": selection_reason,
            "kb_sources": kb_sources,
            "params": params,
        }
        if needs_confirm
        else None
    )

    steps: List[Dict[str, Any]] = []
    if kb_sources:
        steps.append(
            {
                "node": "kb_enrichment",
                "title": "KB Document Lookup",
                "status": "completed",
                "duration_ms": kb_ms,
                "detail": f"Resolved context from uploaded doc(s): {', '.join(kb_sources)}",
            }
        )

    sel_ms = round((time.perf_counter() - started) * 1000, 2)
    param_summary = ", ".join(f"{k}={v}" for k, v in params.items()) or "none"
    steps.append(
        {
            "node": "tool_selector",
            "title": "Tool Selector & Params",
            "status": "completed",
            "duration_ms": sel_ms,
            "detail": (
                f"Selected `{tool_name}` ({selection_reason}) | "
                f"params: [{param_summary}] | "
                f"{'HITL gate triggered' if needs_confirm else 'Read-only fast path'}"
            ),
        }
    )

    logger.info(
        "tool_selected",
        tool=tool_name,
        params=params,
        kb_sources=kb_sources,
        requires_confirmation=needs_confirm,
        session=state.get("session_id"),
    )
    return {
        "selected_tool": tool_name,
        "extracted_params": params,
        "requires_confirmation": needs_confirm,
        "pending_action": pending,
        "tool_error": None,
        "execution_steps": steps,
    }


async def executor_node(state: AgentState) -> Dict[str, Any]:
    """Execute the selected tool with RBAC guard, circuit breaker + backoff retries and audit logging."""
    tool_name = state.get("selected_tool")
    session_id = state.get("session_id", "unknown")
    tenant_id = state.get("tenant_id") or "default"
    user_role = state.get("user_role")
    params = state.get("extracted_params") or {}
    user_msg = _last_user_message(state["messages"])
    retrieved_tools = state.get("retrieved_tools") or []
    prior_steps = list(state.get("execution_steps") or [])

    if not tool_name:
        return {
            "tool_result": None,
            "tool_error": state.get("tool_error") or "No tool selected for execution.",
        }

    if user_role:
        from fastapi import HTTPException as _HTTPException
        from app.core.security import AuthContext, enforce_tool_rbac

        try:
            enforce_tool_rbac(
                tool_name,
                params,
                AuthContext(
                    user_id="graph-executor",
                    tenant_id=tenant_id,
                    role=user_role,
                    auth_method="state",
                ),
            )
        except _HTTPException as rbac_exc:
            await write_audit(
                session_id=session_id,
                action="rbac_denied",
                domain=state.get("domain"),
                tool_name=tool_name,
                payload={"params": params, "role": user_role, "tenant_id": tenant_id},
                result={"error": rbac_exc.detail},
                tenant_id=tenant_id,
            )
            raise PermissionError(rbac_exc.detail) from rbac_exc

    service_name = _service_name_for_tool(tool_name)
    started = time.perf_counter()

    async def _invoke_tool():
        if tool_name == "rag_query":
            from app.tools.rag_tool import execute_rag_query
            return await execute_rag_query(user_msg, tenant_id=tenant_id)
        if tool_name == "system_search":
            from app.tools.system_search import execute_system_search
            return await execute_system_search(user_msg, session_id, tenant_id=tenant_id)
        exec_params = dict(params)
        if tool_name in {"get_invoice", "list_invoices"}:
            exec_params = await _attach_live_invoice_history(exec_params, tenant_id=tenant_id)
        return await execute_paypal_tool(tool_name, user_msg, params=exec_params)

    try:
        result = await run_with_resilience(service_name, _invoke_tool, max_attempts=2)
        exec_ms = round((time.perf_counter() - started) * 1000, 2)
        exec_step = {
            "node": "executor",
            "title": "Tool Executor",
            "status": "completed",
            "duration_ms": exec_ms,
            "detail": f"Executed `{tool_name}` via `{service_name}` (circuit: closed)",
        }
        trace_payload = _build_trace_payload(
            state=state,
            user_msg=user_msg,
            params=params,
            retrieved_tools=retrieved_tools,
            exec_ms=exec_ms,
            execution_steps=prior_steps + [exec_step],
        )
        await write_audit(
            session_id=session_id,
            action="tool_called",
            domain=state.get("domain"),
            tool_name=tool_name,
            payload=trace_payload,
            result=result,
            tenant_id=tenant_id,
        )
        return {
            "tool_result": result,
            "tool_error": None,
            "pending_action": None,
            "execution_steps": [exec_step],
        }

    except CircuitOpenError as exc:
        exec_ms = round((time.perf_counter() - started) * 1000, 2)
        exec_step = {
            "node": "executor",
            "title": "Tool Executor",
            "status": "failed",
            "duration_ms": exec_ms,
            "detail": f"Circuit breaker OPEN for `{service_name}`: {exc}",
        }
        trace_payload = _build_trace_payload(
            state=state,
            user_msg=user_msg,
            params=params,
            retrieved_tools=retrieved_tools,
            exec_ms=exec_ms,
            execution_steps=prior_steps + [exec_step],
            circuit_open=True,
        )
        logger.warning("tool_circuit_open", tool=tool_name, service=service_name, error=str(exc))
        await write_audit(
            session_id=session_id,
            action="tool_failed",
            domain=state.get("domain"),
            tool_name=tool_name,
            payload=trace_payload,
            result={"error": str(exc)},
            tenant_id=tenant_id,
        )
        return {
            "tool_result": None,
            "tool_error": str(exc),
            "pending_action": None,
            "execution_steps": [exec_step],
        }

    except Exception as exc:
        exec_ms = round((time.perf_counter() - started) * 1000, 2)
        exec_step = {
            "node": "executor",
            "title": "Tool Executor",
            "status": "failed",
            "duration_ms": exec_ms,
            "detail": f"Tool `{tool_name}` failed: {exc}",
        }
        trace_payload = _build_trace_payload(
            state=state,
            user_msg=user_msg,
            params=params,
            retrieved_tools=retrieved_tools,
            exec_ms=exec_ms,
            execution_steps=prior_steps + [exec_step],
        )
        logger.error("tool_execution_failed", tool=tool_name, error=str(exc))
        await write_audit(
            session_id=session_id,
            action="tool_failed",
            domain=state.get("domain"),
            tool_name=tool_name,
            payload=trace_payload,
            result={"error": str(exc)},
            tenant_id=tenant_id,
        )
        return {
            "tool_result": None,
            "tool_error": f"Tool '{tool_name}' failed: {exc}",
            "pending_action": None,
            "execution_steps": [exec_step],
        }


def _build_trace_payload(
    state: AgentState,
    user_msg: str,
    params: Dict[str, Any],
    retrieved_tools: List[Dict[str, Any]],
    exec_ms: float,
    execution_steps: List[Dict[str, Any]],
    circuit_open: bool = False,
) -> Dict[str, Any]:
    return {
        "trace_id": state.get("trace_id"),
        "user_message": user_msg[:300],
        "params": params,
        "retrieval_latency_ms": state.get("retrieval_latency_ms"),
        "execution_ms": exec_ms,
        "circuit_open": circuit_open,
        "execution_steps": execution_steps,
        "candidates": [
            {
                "name": t.get("name"),
                "domain": t.get("domain"),
                "final_score": t.get("final_score", 0.0),
                "cosine_sim": t.get("cosine_sim", 0.0),
                "bm25_score": t.get("bm25_score", 0.0),
            }
            for t in retrieved_tools[:5]
        ],
    }


def _service_name_for_tool(tool_name: str) -> str:
    if tool_name == "rag_query":
        return "rag_service"
    if tool_name == "system_search":
        return "system_service"
    return "paypal_api"


def _last_user_message(messages: List[Any]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return str(m.content)
    return ""


async def _select_best_tool(
    user_message: str, tools: List[Dict[str, Any]]
) -> Tuple[Dict[str, Any], str]:
    """Use Gemini to choose the highest-fit tool from top-k retrieved candidates with reasoning."""
    if len(tools) == 1:
        return tools[0], f"Only candidate returned (`{tools[0].get('name')}`)"

    tool_list = "\n".join(
        f"{i+1}. {t['name']} ({t.get('domain', '')}, score={t.get('final_score', 0.0)}): {t['description']}"
        for i, t in enumerate(tools)
    )
    prompt = (
        f"You are selecting the ultra-suitable tool for an enterprise procurement request.\n"
        f"User request: {user_message}\n\n"
        f"Candidate tools (pre-filtered by pgvector Hybrid cosine + BM25 + RRF):\n{tool_list}\n\n"
        f'Reply ONLY with JSON: {{"index": <1-based integer>, "reason": "<concise 1-sentence reason>"}}'
    )
    raw = await call_gemini(prompt, temperature=0.0, timeout=6.0)
    parsed = parse_json_response(raw)
    if parsed and isinstance(parsed.get("index"), int):
        idx = parsed["index"] - 1
        if 0 <= idx < len(tools):
            reason = str(parsed.get("reason") or "").strip()
            label = f"Gemini LLM: {reason}" if reason else f"Gemini LLM selected rank #{idx + 1}"
            return tools[idx], label
    top_score = tools[0].get("final_score", 0.0)
    return tools[0], f"Hybrid RRF rank #1 (score={top_score})"


async def _extract_parameters(user_message: str, tool: Dict[str, Any]) -> Dict[str, Any]:
    """Extract structured parameters using regex heuristics and optional Gemini enrichment."""
    params = _regex_extract_params(user_message)
    schema = tool.get("schema") or {}
    if not schema:
        return params

    prompt = (
        f"Extract parameters for tool `{tool['name']}`.\n"
        f"Expected parameter schema keys: {list(schema.keys())}\n"
        f"User message: {user_message}\n\n"
        f"Return ONLY a JSON object with parameters clearly stated by the user."
    )
    raw = await call_gemini(prompt, temperature=0.0, timeout=6.0)
    parsed = parse_json_response(raw)
    if parsed:
        for k, v in parsed.items():
            if v not in (None, "", []):
                params[k] = v
    return params


def _regex_extract_params(text: str) -> Dict[str, Any]:
    """Deterministic entity/parameter extraction for amounts, emails, IDs, names & periods."""
    params: Dict[str, Any] = {}

    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    if email_match:
        params["recipient"] = email_match.group(0)

    amount_match = re.search(r"\$\s?[\d,]+(?:\.\d{1,2})?", text)
    if amount_match:
        params["amount"] = amount_match.group(0).replace(" ", "")

    # Matches INV-2026-0042, invoice_001, invoive_001, inv_001
    inv_match = re.search(r"\b((?:invoice|invoive|inv)[_-][A-Za-z0-9-]+)\b", text, re.IGNORECASE)
    if inv_match:
        raw_id = inv_match.group(1)
        params["invoice_id"] = re.sub(r"^invoive", "invoice", raw_id, flags=re.IGNORECASE).upper()

    po_match = re.search(r"\b(PO[-_][A-Za-z0-9-]+)\b", text, re.IGNORECASE)
    if po_match:
        params["po_id"] = po_match.group(1).upper()

    disp_match = re.search(r"\b(PP-D-[A-Za-z0-9-]+)\b", text, re.IGNORECASE)
    if disp_match:
        params["dispute_id"] = disp_match.group(1).upper()

    cap_match = re.search(r"\b(CAP[-_][A-Za-z0-9-]+)\b", text, re.IGNORECASE)
    if cap_match:
        params["capture_id"] = cap_match.group(1).upper()

    txn_match = re.search(r"\b(TXN[-_][A-Za-z0-9-]+)\b", text, re.IGNORECASE)
    if txn_match:
        params["transaction_id"] = txn_match.group(1).upper()

    ord_match = re.search(r"\b(ORD[-_][A-Za-z0-9-]+)\b", text, re.IGNORECASE)
    if ord_match:
        params["order_id"] = ord_match.group(1).upper()

    batch_match = re.search(r"\b(BATCH[-_][A-Za-z0-9-]+)\b", text, re.IGNORECASE)
    if batch_match:
        params["payout_batch_id"] = batch_match.group(1).upper()

    user_match = re.search(r"\b(user_[A-Za-z0-9]+|vendor_[A-Za-z0-9]+)\b", text, re.IGNORECASE)
    if user_match:
        val = user_match.group(1)
        if val.lower().startswith("vendor_"):
            params["vendor_id"] = val
        else:
            params["user_id"] = val

    vendor_name = re.search(
        r"\b(?:to|from|for)\s+([A-Z][A-Za-z0-9]+(?:\s+(?:Corp|Inc|Ltd|LLC)))\b",
        text,
    )
    if vendor_name:
        params["vendor"] = vendor_name.group(1)
    elif "recipient" not in params:
        # Match recipient person name like "to mike" or "to Mike" (ignoring pronouns/articles)
        person_match = re.search(r"\bto\s+([A-Za-z][A-Za-z]{1,24})\b", text, re.IGNORECASE)
        if person_match and person_match.group(1).lower() not in {
            "confirm", "approve", "create", "send", "our", "my", "the", "your",
            "this", "that", "its", "their", "his", "her", "pay", "check", "find",
            "get", "avoid", "review", "flag", "issue",
        }:
            params["recipient_name"] = person_match.group(1).title()

    period_match = re.search(
        r"\b(last month|last quarter|this month|this quarter|Q[1-4](?:\s+\d{4})?)\b",
        text,
        re.IGNORECASE,
    )
    if period_match:
        params["period"] = period_match.group(1)

    return params


_GENERIC_QUERY_WORDS = {
    "the", "for", "and", "get", "me", "my", "our", "already", "sent", "was",
    "is", "are", "this", "that", "invoice", "invoices", "payment", "payments",
    "order", "purchase", "dispute", "disputes", "vendor", "vendors", "supplier",
    "report", "sales", "volume", "total", "last", "month", "quarter", "please",
    "find", "check", "show", "view", "with", "from", "to", "all", "status",
    "details", "can", "you", "what", "which", "send", "create", "cancel",
    "approve", "list", "about", "there", "open", "have", "has", "been",
    "available", "managing", "manage", "tool", "tools", "handle", "capabilities",
    "history", "requests", "request", "refund", "discrepancy", "mismatch", "flag",
    "payout", "payouts", "batch", "verify", "verification", "identity", "kyc",
    "evidence", "escalate", "outstanding", "unpaid", "existing", "regarding",
}


async def _attach_live_invoice_history(
    params: Dict[str, Any],
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """Enrich `get_invoice` / `list_invoices` with executed tenant audit records from PostgreSQL."""
    enriched = dict(params)
    try:
        async with AsyncSessionLocal() as db:
            stmt = (
                select(AuditLog)
                .where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.action == "tool_called",
                    AuditLog.tool_name.in_(["send_invoice", "create_invoice", "cancel_invoice", "record_invoice_payment"]),
                )
                .order_by(desc(AuditLog.created_at))
                .limit(10)
            )
            logs = (await db.execute(stmt)).scalars().all()
    except Exception:
        return enriched

    if not logs:
        return enriched

    recent_list: List[Dict[str, Any]] = []
    target_inv = str(enriched.get("invoice_id") or "").upper()
    target_rec = str(enriched.get("recipient") or enriched.get("recipient_name") or "").lower()

    for log in logs:
        p = (log.payload or {}).get("params") or {}
        inv_id = str(p.get("invoice_id") or "")
        rec = str(p.get("recipient") or p.get("recipient_name") or "")
        amt = p.get("amount") or "$500.00"
        status_map = {
            "send_invoice": "SENT",
            "create_invoice": "DRAFT",
            "cancel_invoice": "CANCELLED",
            "record_invoice_payment": "PAID",
        }
        st = status_map.get(log.tool_name or "", "SENT")
        entry = {
            "invoice_id": inv_id or "INV-2026-0042",
            "status": st,
            "amount": amt,
            "recipient": rec or "vendor@example.com",
            "sent_at": log.created_at.isoformat() if log.created_at else None,
        }
        recent_list.append(entry)

        if target_inv and inv_id.upper() == target_inv and "audit_status" not in enriched:
            enriched["audit_status"] = st
            enriched["sent_at"] = entry["sent_at"]
        elif target_rec and (target_rec in rec.lower()) and "audit_status" not in enriched:
            if not target_inv and inv_id:
                enriched["invoice_id"] = inv_id
            if "amount" not in enriched and amt:
                enriched["amount"] = amt
            enriched["audit_status"] = st
            enriched["sent_at"] = entry["sent_at"]

    if recent_list:
        enriched["recent_audit_invoices"] = recent_list[:5]
    return enriched


async def _enrich_params_from_kb(
    domain: str,
    user_message: str,
    params: Dict[str, Any],
    tenant_id: str = "default",
) -> Tuple[Dict[str, Any], List[str], str]:
    """
    Look up uploaded KB documents (`kb_chunks`) & AuditLogs when a query references
    an entity ID (`INVOICE_001`), contact name (`Mike`), or ambiguous entity, then
    optionally refine missing fields via Gemini.
    Returns `(enriched_params, matched_document_names, context_text_for_llm)`.
    """
    if domain in {"rag", "system"}:
        return params, [], ""

    terms: List[str] = []
    for key in (
        "invoice_id",
        "po_id",
        "dispute_id",
        "capture_id",
        "transaction_id",
        "order_id",
        "payout_batch_id",
        "recipient_name",
        "vendor",
        "user_id",
    ):
        if params.get(key):
            terms.append(str(params[key]))

    # Also extract specific entity/person tokens directly (e.g., "mike" in "get me the mike invoice")
    entity_tokens: List[str] = []
    for tok in re.findall(r"[a-zA-Z0-9_-]+", user_message):
        low = tok.lower()
        if len(low) >= 3 and low not in _GENERIC_QUERY_WORDS and not low.isdigit():
            if low not in {t.lower() for t in terms} and tok not in entity_tokens:
                entity_tokens.append(tok)

    search_terms = terms + entity_tokens[:3]
    if not search_terms:
        return params, [], ""

    enriched = dict(params)
    matched_docs: List[str] = []

    try:
        async with AsyncSessionLocal() as db:
            filters = [KBChunk.text.ilike(f"%{t}%") for t in search_terms]
            stmt = select(KBChunk).where(KBChunk.tenant_id == tenant_id, or_(*filters)).limit(12)
            chunks = list((await db.execute(stmt)).scalars().all())
            if not chunks and entity_tokens:
                from app.core.hybrid_search import HybridSearchService

                hybrid_hits = await HybridSearchService(session=db).search_hybrid(
                    query_text=user_message,
                    limit=4,
                    tenant_id=tenant_id,
                )
                chunks = [
                    type(
                        "_ChunkView",
                        (),
                        {"document_name": h.document_name, "text": h.text},
                    )()
                    for h in hybrid_hits
                ]
    except Exception as exc:
        logger.warning("kb_param_enrichment_failed", error=str(exc))
        return params, [], ""

    if not chunks:
        return params, [], ""

    primary_ids = [
        str(params[k]).lower()
        for k in ("invoice_id", "po_id", "dispute_id", "capture_id", "transaction_id", "payout_batch_id")
        if params.get(k)
    ]
    focus_terms = primary_ids + [t.lower() for t in entity_tokens[:3]]
    chunks.sort(
        key=lambda ch: (
            sum(1 for pid in primary_ids if pid in (ch.document_name or "").lower()),
            sum(1 for ft in focus_terms if ft in (ch.document_name or "").lower()),
            sum(1 for pid in primary_ids if pid in (ch.text or "").lower()),
            sum(1 for ft in focus_terms if ft in (ch.text or "").lower()),
            1 if domain == "invoicing" and "invoice" in (ch.document_name or "").lower() else 0,
            1 if domain == "procurement" and ("po-" in (ch.document_name or "").lower() or "purchase" in (ch.document_name or "").lower()) else 0,
            0 if any(w in (ch.document_name or "").lower() for w in ("directory", "summary", "playbook", "policy", "sla")) else 1,
        ),
        reverse=True,
    )

    candidate_person = (enriched.get("recipient_name") or (entity_tokens[0].title() if entity_tokens else "")).strip()

    for ch in chunks:
        if ch.document_name not in matched_docs:
            matched_docs.append(ch.document_name)
        txt = ch.text or ""

        # Resolve invoice_id / po_id from matched KB doc when omitted in query (e.g., "get me the mike invoice")
        if "invoice_id" not in enriched and (domain == "invoicing" or "invoice" in user_message.lower()):
            kb_inv = re.search(r"Invoice\s*ID[:\s]+([A-Za-z0-9_-]+)", txt, re.IGNORECASE)
            if kb_inv:
                enriched["invoice_id"] = kb_inv.group(1).upper()

        if "po_id" not in enriched and (domain == "procurement" or "purchase order" in user_message.lower()):
            kb_po = re.search(r"PO\s*Number[:\s]+(PO[-_A-Za-z0-9]+)", txt, re.IGNORECASE)
            if kb_po:
                enriched["po_id"] = kb_po.group(1).upper()

        # Resolve recipient email for named contact (e.g., "Mike Thompson <mike@acmecorp.com>")
        if "recipient" not in enriched and candidate_person:
            name_q = candidate_person.lower()
            for line in txt.splitlines():
                if name_q in line.lower():
                    email_in_line = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", line)
                    if email_in_line:
                        enriched["recipient"] = email_in_line.group(0)
                        enriched.setdefault("recipient_name", candidate_person)
                        break
            if "recipient" not in enriched and enriched.get("recipient_name"):
                any_email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", txt)
                if any_email:
                    enriched["recipient"] = any_email.group(0)

        # Resolve invoice/PO amount if missing (prefer explicit Total over first line item)
        if "amount" not in enriched:
            total_amt = re.search(
                r"(?:Total(?:\s+(?:Amount|PO))?(?:\s+(?:Due|Value))?|Grand\s+Total)[:\s]+(\$\s?[\d,]+(?:\.\d{1,2})?)",
                txt,
                re.IGNORECASE,
            )
            amt = total_amt.group(1) if total_amt else None
            if not amt:
                first_amt = re.search(r"\$\s?[\d,]+(?:\.\d{1,2})?", txt)
                amt = first_amt.group(0) if first_amt else None
            if amt:
                enriched["amount"] = amt.replace(" ", "")

        # Resolve due date if present
        if "due_date" not in enriched:
            due = re.search(r"Due\s*Date[:\s]+([0-9]{4}-[0-9]{2}-[0-9]{2})", txt, re.IGNORECASE)
            if due:
                enriched["due_date"] = due.group(1)

        # Resolve vendor/company name when explicitly listed in document header
        if "vendor" not in enriched:
            vnd = re.search(r"^\s*(?:Vendor|Company)\s*:\s*([^\n\r]+)$", txt, re.IGNORECASE | re.MULTILINE)
            if vnd:
                enriched["vendor"] = vnd.group(1).strip()

    context = "\n---\n".join(
        f"[{ch.document_name}]\n{(ch.text or '')[:1200]}" for ch in chunks[:4]
    )
    prompt = (
        f"Extract missing parameter values for domain `{domain}` from the user request and KB snippets.\n"
        f"User request: {user_message}\n"
        f"Current extracted parameters: {json.dumps(enriched)}\n\n"
        f"KB Snippets:\n{context[:3500]}\n\n"
        f"Return ONLY JSON with verified values for missing fields "
        f"(such as recipient, recipient_name, amount, invoice_id, po_id, dispute_id, due_date, vendor)."
    )
    raw = await call_gemini(prompt, temperature=0.0, timeout=6.0)
    parsed = parse_json_response(raw)
    if parsed:
        for key in ("recipient", "recipient_name", "amount", "invoice_id", "po_id", "dispute_id", "due_date", "vendor"):
            val = parsed.get(key)
            if val not in (None, "", []) and key not in enriched:
                enriched[key] = val

    return enriched, matched_docs, context


async def write_audit(
    session_id: str,
    action: str,
    domain: str | None,
    tool_name: str | None,
    payload: Dict[str, Any],
    result: Any,
    tenant_id: str = "default",
) -> None:
    """Append an immutable tenant-scoped audit record for this agent action."""
    try:
        async with AsyncSessionLocal() as session:
            log = AuditLog(
                tenant_id=tenant_id,
                session_id=session_id,
                action=action,
                domain=domain,
                tool_name=tool_name,
                payload=payload,
                result_summary=str(result)[:500] if result else None,
            )
            session.add(log)
            await session.commit()
    except Exception as exc:
        logger.warning("audit_write_failed", error=str(exc))
