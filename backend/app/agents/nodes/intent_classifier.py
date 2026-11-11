"""
intent_classifier.py — Supervisor/Router Node.

Uses Gemini (when configured) with recent multi-turn context, falling back to
priority-ordered pattern classification so meta-queries (`system`, `rag`) never
get swallowed by domain keywords (`invoicing`, `procurement`).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agents.state import AgentState
from app.core.llm_client import call_gemini, parse_json_response

logger = structlog.get_logger("procureiq.intent_classifier")

VALID_DOMAINS = {
    "payments",
    "invoicing",
    "analytics",
    "disputes",
    "procurement",
    "rag",
    "system",
    "general",
}

# Checked in strict priority order so meta-intents (`system`, `rag`) win cleanly.
PRIORITY_PATTERNS: List[Tuple[str, str]] = [
    (
        "system",
        r"\b(what tools|which tools|available tools|capabilities|last request|"
        r"request history|session history|audit history|status of my last|did i run)\b",
    ),
    (
        "rag",
        r"\b(policy|policies|sla|contract|clause|sop|handbook|guideline|uploaded|"
        r"according to|what does .* say|document)\b",
    ),
    (
        "disputes",
        r"\b(disputes?|chargebacks?|complaints?|escalat\w+|claim)\b",
    ),
    (
        "invoicing",
        r"\b(invoices?|billing|bills?|invoice discrepancy|unpaid invoice)\b",
    ),
    (
        "procurement",
        r"\b(purchase orders?|pos?\b|vendors?|suppliers?|rfq|goods receipt|requisitions?)\b",
    ),
    (
        "analytics",
        r"\b(sales volume|sales report|revenue|total spend|spend by|budget utilization|"
        r"analytics|settlement report|export .* csv|last quarter|last month)\b",
    ),
    (
        "payments",
        r"\b(pay|payments?|send\s+\$?\d+(?:,\d{3})*(?:\.\d+)?|transfer|wire|refund|payout|balance|transactions?|"
        r"subscriptions?|authorize)\b",
    ),
]

_SYSTEM_PROMPT = """You are a routing supervisor for an enterprise procurement and payments intelligence agent.

Given the recent conversation and latest user message, reply ONLY with a JSON object:
- "domain": one of [payments, invoicing, analytics, disputes, procurement, rag, system, general]
- "intent": a concise 5-10 word description of the user's goal

Routing rules:
- system: asking which tools/capabilities exist, or checking status/history of past requests
- rag: asking questions about uploaded documents, SLAs, contracts, policies, or guides
- disputes: disputes, chargebacks, refunds/claims on disputes, KYC/risk
- invoicing: creating, sending, listing, reconciling, or reminding invoices
- procurement: purchase orders, vendors, suppliers, RFQs, goods receipts
- analytics: sales reports, revenue breakdowns, spend reports, budget utilization
- payments: sending money/payments, payouts, account balance, transactions, subscriptions
- general: greetings or uncategorized requests
"""


async def intent_classifier_node(state: AgentState) -> Dict[str, Any]:
    """
    Classify user intent and domain using multi-turn conversation history.
    """
    messages = state["messages"]
    last_user_msg = _last_human_text(messages)
    prior_domain = state.get("domain")

    domain, intent = _rule_classify(last_user_msg, prior_domain=prior_domain)

    history_snippet = _format_recent_history(messages, max_turns=4)
    prompt = f"{_SYSTEM_PROMPT}\n\nConversation:\n{history_snippet}\n\nLatest user message: {last_user_msg}"
    raw = await call_gemini(prompt, temperature=0.0, timeout=8.0)
    parsed = parse_json_response(raw)
    if parsed:
        llm_domain = str(parsed.get("domain", "")).strip().lower()
        llm_intent = str(parsed.get("intent", "")).strip()
        if llm_domain in VALID_DOMAINS:
            domain = llm_domain
        if llm_intent:
            intent = llm_intent

    logger.info("intent_classified", domain=domain, intent=intent, msg_preview=last_user_msg[:80])
    return {"domain": domain, "intent": intent}


def _last_human_text(messages: List[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return str(msg.content)
    return ""


def _format_recent_history(messages: List[BaseMessage], max_turns: int = 4) -> str:
    recent = messages[-(max_turns * 2) :]
    lines: List[str] = []
    for msg in recent:
        role = "User" if isinstance(msg, HumanMessage) else "Assistant" if isinstance(msg, AIMessage) else "System"
        lines.append(f"{role}: {str(msg.content)[:250]}")
    return "\n".join(lines)


def _rule_classify(text: str, prior_domain: str | None = None) -> Tuple[str, str]:
    """Deterministic priority-ordered fallback classifier."""
    lower = text.lower().strip()
    for domain, pattern in PRIORITY_PATTERNS:
        if re.search(pattern, lower):
            return domain, text[:80]

    # Short follow-ups (e.g. "what about last month?" or "show details") inherit prior domain
    if prior_domain and prior_domain in VALID_DOMAINS and len(lower.split()) <= 8:
        return prior_domain, text[:80]

    return "general", text[:80]
