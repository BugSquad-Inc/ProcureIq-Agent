"""
llm_client.py — Shared async Gemini REST client for ProcureIQ.

Centralizes Gemini API calls with SSL configuration, fallback model cascade,
and optional LangSmith tracing so nodes and tools never duplicate HTTP logic.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx
import structlog

from app.config import get_settings

try:
    from langsmith import traceable
except ImportError:  # pragma: no cover
    def traceable(*args, **kwargs):
        def _decorator(fn):
            return fn
        return _decorator

logger = structlog.get_logger("procureiq.llm_client")


@traceable(name="procureiq.gemini.generate", run_type="llm")
async def call_gemini(
    prompt: str,
    temperature: float = 0.2,
    timeout: float = 12.0,
) -> Optional[str]:
    """
    Call Google Gemini generateContent REST API with automatic model fallback.
    Returns stripped response text, or None if unconfigured / unavailable.
    """
    settings = get_settings()
    api_key = (settings.gemini_api_key or "").strip().strip('"').strip("'")
    if not api_key or api_key == "your_gemini_api_key_here":
        return None

    primary = (settings.gemini_model or "gemini-2.5-flash-lite").replace("models/", "")
    candidates: List[str] = [primary]
    for fallback in ("gemini-2.5-flash-lite", "gemini-flash-lite-latest", "gemini-flash-latest"):
        if fallback not in candidates:
            candidates.append(fallback)

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }

    async with httpx.AsyncClient(verify=settings.gemini_verify_ssl, timeout=timeout) as client:
        for model in candidates:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={api_key}"
            )
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    cands = data.get("candidates", [])
                    if cands:
                        parts = cands[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", "").strip()
                elif resp.status_code in (404, 429, 503):
                    logger.warning("gemini_model_fallback", model=model, status=resp.status_code)
                    continue
                else:
                    logger.warning("gemini_unexpected_status", model=model, status=resp.status_code)
                    return None
            except Exception as exc:
                logger.warning("gemini_call_error", model=model, error=str(exc))
                continue

    return None


def parse_json_response(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """Strip optional markdown code fences and parse JSON object safely."""
    if not raw:
        return None
    cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", raw.strip())
    cleaned = re.sub(r"\n?```$", "", cleaned.strip())
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None
        return None


def _to_gemini_parameters_schema(schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Convert ProcureIQ compact tool schema dicts to valid Gemini OpenAPI schemas."""
    type_map = {
        "string": "STRING",
        "str": "STRING",
        "number": "NUMBER",
        "float": "NUMBER",
        "integer": "INTEGER",
        "int": "INTEGER",
        "boolean": "BOOLEAN",
        "bool": "BOOLEAN",
        "array": "ARRAY",
        "object": "OBJECT",
    }
    properties: Dict[str, Any] = {}
    for k, v in (schema or {}).items():
        if isinstance(v, str):
            gtype = type_map.get(v.lower(), "STRING")
            if gtype == "ARRAY":
                properties[k] = {"type": "ARRAY", "items": {"type": "STRING"}}
            else:
                properties[k] = {"type": gtype, "description": f"Parameter {k}"}
        elif isinstance(v, dict) and "type" in v:
            gtype = type_map.get(str(v["type"]).lower(), "STRING")
            prop: Dict[str, Any] = {"type": gtype, "description": str(v.get("description", k))}
            if gtype == "ARRAY":
                prop["items"] = {"type": "STRING"}
            properties[k] = prop
        else:
            properties[k] = {"type": "STRING", "description": f"Parameter {k}"}
    return {"type": "OBJECT", "properties": properties}


@traceable(name="procureiq.gemini.function_call", run_type="llm")
async def call_gemini_with_tools(
    user_message: str,
    candidate_tools: List[Dict[str, Any]],
    kb_context: Optional[str] = None,
    temperature: float = 0.0,
    timeout: float = 8.0,
) -> Optional[Dict[str, Any]]:
    """
    Use Gemini native Function Calling (`tools` + `functionDeclarations`) across the
    bound top-k retrieved tools so Gemini selects both the optimal tool and arguments.
    Returns `{"name": str, "args": dict, "reason": str}` or None when unavailable.
    """
    settings = get_settings()
    api_key = (settings.gemini_api_key or "").strip().strip('"').strip("'")
    if not api_key or api_key == "your_gemini_api_key_here" or not candidate_tools:
        return None

    declarations = [
        {
            "name": t["name"],
            "description": f"[{t.get('domain', 'general')}] {t.get('description', '')}",
            "parameters": _to_gemini_parameters_schema(t.get("schema")),
        }
        for t in candidate_tools
        if t.get("name")
    ]
    if not declarations:
        return None

    context_block = f"\n\nUploaded Knowledge Base & Audit Context:\n{kb_context[:3500]}" if kb_context else ""
    prompt_text = (
        "You are ProcureIQ. Select the single best tool from the declared functions and fill all arguments "
        "you can verify from the user request and Knowledge Base context. Guidelines:\n"
        "- Never choose destructive actions (cancel_invoice, cancel_purchase_order, send_invoice) when the user asks "
        "to retrieve, view, check, find, or get an existing or already-sent record.\n"
        "- When a specific invoice_id, po_id, or dispute_id (or named person like Mike -> INVOICE_001) is present in the "
        "request or KB context, prefer single-record lookup tools (get_invoice, get_purchase_order, get_dispute) over list_*.\n"
        "- Use refund_payment for refunding a captured payment/capture ID; use accept_dispute_claim or provide_dispute_evidence for dispute claims.\n"
        "- Use flag_invoice_discrepancy when there is a price/tax/quantity mismatch between an invoice and a PO.\n"
        "- Use create_payout_batch for paying multiple vendors in a batch (NOT create_vendor).\n\n"
        f"User request: {user_message}{context_block}"
    )

    primary = (settings.gemini_model or "gemini-2.5-flash-lite").replace("models/", "")
    candidates: List[str] = [primary]
    for fallback in ("gemini-2.5-flash-lite", "gemini-flash-lite-latest", "gemini-flash-latest"):
        if fallback not in candidates:
            candidates.append(fallback)

    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "tools": [{"functionDeclarations": declarations}],
        "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
        "generationConfig": {"temperature": temperature},
    }

    async with httpx.AsyncClient(verify=settings.gemini_verify_ssl, timeout=timeout) as client:
        for model in candidates:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={api_key}"
            )
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    cands = data.get("candidates", [])
                    if not cands:
                        continue
                    parts = cands[0].get("content", {}).get("parts", [])
                    chosen_call = None
                    text_notes: List[str] = []
                    for part in parts:
                        if "functionCall" in part:
                            chosen_call = part["functionCall"]
                        elif "text" in part and part["text"]:
                            text_notes.append(part["text"].strip())
                    if chosen_call and chosen_call.get("name"):
                        return {
                            "name": chosen_call["name"],
                            "args": chosen_call.get("args") or {},
                            "reason": " ".join(text_notes).strip() or f"Native Gemini functionCall (`{model}`)",
                        }
                elif resp.status_code in (404, 429, 503):
                    logger.warning("gemini_tool_call_fallback", model=model, status=resp.status_code)
                    continue
                else:
                    logger.warning("gemini_tool_call_http_error", model=model, status=resp.status_code)
                    return None
            except Exception as exc:
                logger.warning("gemini_tool_call_error", model=model, error=str(exc))
                continue

    return None

