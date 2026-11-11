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

