"""
executor.py — Tool Selection, Parameter Extraction, and Resilient Execution Nodes.

Contains:
  - `tool_selector_node`: Chooses best tool from `retrieved_tools`, extracts
    parameters from conversation context, and flags write operations for HITL.
  - `executor_node`: Runs the selected tool guarded by CircuitBreaker + backoff
    retry (`run_with_resilience`) and writes rich explainability trace data to AuditLog.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List

import structlog
from langchain_core.messages import HumanMessage

from app.agents.state import AgentState
from app.core.llm_client import call_gemini, parse_json_response
from app.core.resilience import CircuitOpenError, run_with_resilience
from app.infrastructure.database.models import AuditLog
from app.infrastructure.database.session import AsyncSessionLocal
from app.tools.paypal_adapter import execute_paypal_tool, is_write_tool

logger = structlog.get_logger("procureiq.executor")


async def tool_selector_node(state: AgentState) -> Dict[str, Any]:
    """
    Pick the best tool from `retrieved_tools`, extract structured parameters,
    and determine whether Human-in-the-Loop confirmation is required.
    """
    retrieved_tools = state.get("retrieved_tools", [])
    if not retrieved_tools:
        return {
            "selected_tool": None,
            "extracted_params": {},
            "requires_confirmation": False,
            "pending_action": None,
            "tool_error": "No matching tools found for this request.",
        }

    user_msg = _last_user_message(state["messages"])
    best_tool = await _select_best_tool(user_msg, retrieved_tools)
    tool_name = best_tool.get("name", "unknown")
    params = await _extract_parameters(user_msg, best_tool)

    require_hitl = state.get("require_hitl", True)
    needs_confirm = bool(require_hitl and is_write_tool(tool_name))
    pending = (
        {
            "tool": tool_name,
            "domain": state.get("domain") or best_tool.get("domain"),
            "description": best_tool.get("description", ""),
            "params": params,
        }
        if needs_confirm
        else None
    )

    logger.info(
        "tool_selected",
        tool=tool_name,
        params=params,
        requires_confirmation=needs_confirm,
        session=state.get("session_id"),
    )
    return {
        "selected_tool": tool_name,
        "extracted_params": params,
        "requires_confirmation": needs_confirm,
        "pending_action": pending,
        "tool_error": None,
    }


async def executor_node(state: AgentState) -> Dict[str, Any]:
    """Execute the selected tool with circuit breaker + backoff retries and audit logging."""
    tool_name = state.get("selected_tool")
    session_id = state.get("session_id", "unknown")
    params = state.get("extracted_params") or {}
    user_msg = _last_user_message(state["messages"])
    retrieved_tools = state.get("retrieved_tools") or []
    trace_payload_meta = {
        "trace_id": state.get("trace_id"),
        "user_message": user_msg[:300],
        "params": params,
        "retrieval_latency_ms": state.get("retrieval_latency_ms"),
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

    if not tool_name:
        return {
            "tool_result": None,
            "tool_error": state.get("tool_error") or "No tool selected for execution.",
        }

    service_name = _service_name_for_tool(tool_name)
    started = time.perf_counter()

    async def _invoke_tool():
        if tool_name == "rag_query":
            from app.tools.rag_tool import execute_rag_query
            return await execute_rag_query(user_msg)
        if tool_name == "system_search":
            from app.tools.system_search import execute_system_search
            return await execute_system_search(user_msg, session_id)
        return await execute_paypal_tool(tool_name, user_msg, params=params)

    try:
        result = await run_with_resilience(service_name, _invoke_tool, max_attempts=2)
        exec_ms = round((time.perf_counter() - started) * 1000, 2)
        await write_audit(
            session_id=session_id,
            action="tool_called",
            domain=state.get("domain"),
            tool_name=tool_name,
            payload={**trace_payload_meta, "execution_ms": exec_ms},
            result=result,
        )
        return {"tool_result": result, "tool_error": None, "pending_action": None}

    except CircuitOpenError as exc:
        exec_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.warning("tool_circuit_open", tool=tool_name, service=service_name, error=str(exc))
        await write_audit(
            session_id=session_id,
            action="tool_failed",
            domain=state.get("domain"),
            tool_name=tool_name,
            payload={**trace_payload_meta, "execution_ms": exec_ms, "circuit_open": True},
            result={"error": str(exc)},
        )
        return {
            "tool_result": None,
            "tool_error": str(exc),
            "pending_action": None,
        }

    except Exception as exc:
        exec_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.error("tool_execution_failed", tool=tool_name, error=str(exc))
        await write_audit(
            session_id=session_id,
            action="tool_failed",
            domain=state.get("domain"),
            tool_name=tool_name,
            payload={**trace_payload_meta, "execution_ms": exec_ms},
            result={"error": str(exc)},
        )
        return {
            "tool_result": None,
            "tool_error": f"Tool '{tool_name}' failed: {exc}",
            "pending_action": None,
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


async def _select_best_tool(user_message: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Use Gemini to pick among top-k retrieved tools, defaulting to rank #1."""
    if len(tools) == 1:
        return tools[0]

    tool_list = "\n".join(
        f"{i+1}. {t['name']} ({t.get('domain', '')}): {t['description']}"
        for i, t in enumerate(tools)
    )
    prompt = (
        f"User request: {user_message}\n\n"
        f"Candidate tools (already pre-filtered by semantic retrieval):\n{tool_list}\n\n"
        f'Reply ONLY with JSON: {{"index": <1-based integer>}}'
    )
    raw = await call_gemini(prompt, temperature=0.0, timeout=6.0)
    parsed = parse_json_response(raw)
    if parsed and isinstance(parsed.get("index"), int):
        idx = parsed["index"] - 1
        if 0 <= idx < len(tools):
            return tools[idx]
    return tools[0]


async def _extract_parameters(user_message: str, tool: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract structured parameters using regex heuristics first and enrich via Gemini
    when configured. Works reliably both offline and with an LLM key.
    """
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
    """Deterministic entity/parameter extraction for amounts, emails, IDs, and periods."""
    params: Dict[str, Any] = {}

    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    if email_match:
        params["recipient"] = email_match.group(0)

    amount_match = re.search(r"\$\s?[\d,]+(?:\.\d{1,2})?", text)
    if amount_match:
        params["amount"] = amount_match.group(0).replace(" ", "")

    inv_match = re.search(r"\b(INV-[A-Za-z0-9-]+)\b", text, re.IGNORECASE)
    if inv_match:
        params["invoice_id"] = inv_match.group(1).upper()

    po_match = re.search(r"\b(PO-[A-Za-z0-9-]+)\b", text, re.IGNORECASE)
    if po_match:
        params["po_id"] = po_match.group(1).upper()

    disp_match = re.search(r"\b(PP-D-[A-Za-z0-9-]+)\b", text, re.IGNORECASE)
    if disp_match:
        params["dispute_id"] = disp_match.group(1).upper()

    user_match = re.search(r"\b(user_[A-Za-z0-9]+|vendor_[A-Za-z0-9]+)\b", text, re.IGNORECASE)
    if user_match:
        val = user_match.group(1)
        if val.lower().startswith("vendor_"):
            params["vendor_id"] = val
        else:
            params["user_id"] = val

    vendor_name = re.search(r"\b(?:to|from|for)\s+([A-Z][A-Za-z0-9]+(?:\s+(?:Corp|Inc|Ltd|LLC)))\b", text)
    if vendor_name:
        params["vendor"] = vendor_name.group(1)

    period_match = re.search(
        r"\b(last month|last quarter|this month|this quarter|Q[1-4](?:\s+\d{4})?)\b",
        text,
        re.IGNORECASE,
    )
    if period_match:
        params["period"] = period_match.group(1)

    return params


async def write_audit(
    session_id: str,
    action: str,
    domain: str | None,
    tool_name: str | None,
    payload: Dict[str, Any],
    result: Any,
) -> None:
    """Append an immutable audit record for this agent action."""
    try:
        async with AsyncSessionLocal() as session:
            log = AuditLog(
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
