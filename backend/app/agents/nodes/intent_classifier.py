"""
intent_classifier.py — Supervisor/Router Node.

Uses Gemini (when configured) with recent multi-turn context, falling back to
priority-ordered pattern classification so meta-queries (`system`, `rag`) never
get swallowed by domain keywords (`invoicing`, `procurement`).
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Tuple

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agents.state import AgentState
from app.core.hybrid_search import normalize_query_text
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
    "out_of_scope",
}

_GREETING_PATTERN = re.compile(
    r"^(hi|hello|hey|good\s+(morning|afternoon|evening)|howdy|help|who are you|what can you do)[\s!?.]*$"
)
_OFF_TOPIC_PATTERN = re.compile(
    r"\b(weather|forecast|temperature|rain|sunny|recipe|cook|bake|pizza|pasta|joke|poem|"
    r"story|riddle|song|lyrics|movie|cricket|football|soccer|nba|fifa|world cup|"
    r"capital of|president of|prime minister|planet|galaxy|quantum|celebrity|horoscope|"
    r"play chess|write a python|palindrome)\b"
)
_DOMAIN_ANCHOR_PATTERN = re.compile(
    r"\b(invoice|invoiv|payment|pay|payout|refund|capture|balance|transaction|subscription|"
    r"purchase order|po[-_\s]|vendor|supplier|rfq|goods receipt|dispute|chargeback|kyc|risk|"
    r"sales|revenue|spend|budget|settlement|webhook|policy|sla|sop|contract|document|tool|soc2|finra)\b"
)

# Checked in strict priority order so meta-intents (`system`, `rag`) win cleanly.
PRIORITY_PATTERNS: List[Tuple[str, str]] = [
    (
        "system",
        r"\b(what tools|which tools|available tools|capabilities|last request|"
        r"request history|session history|audit history|status of my last|did i run)\b",
    ),
    (
        "rag",
        r"\b(policy|policies|sla|contract|clause|sop|handbook|guideline|playbook|uploaded|"
        r"according to|what does .* say|what is our .* rule|kyc requirement|document)\b",
    ),
    (
        "disputes",
        r"\b(disputes?|chargebacks?|complaints?|escalat\w+|claim)\b",
    ),
    (
        "invoicing",
        r"\b(invoic\w*|invoiv\w*|inv[-_]\d+|billing|bills?|invoice discrepancy|unpaid invoice)\b",
    ),
    (
        "payments",
        r"\b(payouts?|batch[-_][A-Za-z0-9-]+|vendor payout|refunds?|captures?|cap[-_]\w+)\b",
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
        r"\b(pay|payments?|send\s+\$?\d+(?:,\d{3})*(?:\.\d+)?|transfer|wire|balance|transactions?|"
        r"subscriptions?|authorize)\b",
    ),
]

_SYSTEM_PROMPT = """You are a routing supervisor for an enterprise procurement and payments intelligence agent.

Given the recent conversation and latest user message, reply ONLY with a JSON object:
- "domain": one of [payments, invoicing, analytics, disputes, procurement, rag, system, general, out_of_scope]
- "intent": a concise 5-10 word description of the user's goal

Routing rules:
- system: asking which tools/capabilities exist, or checking status/history of past requests
- rag: asking questions about uploaded documents, SLAs, contracts, policies, or guides
- disputes: counterparty disputes, chargebacks, dispute claims/evidence, KYC/risk
- invoicing: creating, sending, listing, reconciling, or reminding invoices
- procurement: purchase orders, vendor onboarding/profiles, suppliers, RFQs, goods receipts (NOT vendor batch payouts)
- analytics: sales reports, revenue breakdowns, spend reports, budget utilization
- payments: sending money/payments, batch vendor payouts (create_payout_batch), refunding payments or capture IDs, account balance, transactions, subscriptions
- general: potentially enterprise/KB related queries needing retrieval check
- out_of_scope: greetings or topics unrelated to finance, payments, invoicing, procurement, disputes, analytics, tools, or uploaded KB documents (e.g., weather, recipes, sports, jokes, trivia)
"""


async def intent_classifier_node(state: AgentState) -> Dict[str, Any]:
    """
    Classify user intent and domain using multi-turn conversation history.
    """
    started = time.perf_counter()
    messages = state["messages"]
    last_user_msg = normalize_query_text(_last_human_text(messages))
    prior_domain = state.get("domain")

    domain, intent = _rule_classify(last_user_msg, prior_domain=prior_domain)
    source = "rule_classifier"

    # Keep deterministic meta-routes (`system`, `rag`, `out_of_scope`) authoritative so questions like
    # "What tools are available for invoices?" or irrelevant queries bypass unnecessary LLM routing.
    if domain not in {"system", "rag", "out_of_scope"}:
        history_snippet = _format_recent_history(messages, max_turns=4)
        prompt = f"{_SYSTEM_PROMPT}\n\nConversation:\n{history_snippet}\n\nLatest user message: {last_user_msg}"
        raw = await call_gemini(prompt, temperature=0.0, timeout=8.0)
        parsed = parse_json_response(raw)
        if parsed:
            llm_domain = str(parsed.get("domain", "")).strip().lower()
            llm_intent = str(parsed.get("intent", "")).strip()
            if llm_domain in VALID_DOMAINS and llm_domain not in {"system"}:
                domain = llm_domain
                source = "gemini_supervisor"
            if llm_intent:
                intent = llm_intent

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info("intent_classified", domain=domain, intent=intent, msg_preview=last_user_msg[:80])
    return {
        "domain": domain,
        "intent": intent,
        "execution_steps": [
            {
                "node": "intent_classifier",
                "title": "Intent Classifier",
                "status": "completed",
                "duration_ms": elapsed_ms,
                "detail": f"Routed to domain '{domain}' via {source} (intent: {intent[:60]})",
            }
        ],
    }


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
    """Deterministic priority-ordered fallback classifier with out-of-scope guard."""
    lower = text.lower().strip()
    if _GREETING_PATTERN.match(lower):
        return "out_of_scope", "greeting"

    for domain, pattern in PRIORITY_PATTERNS:
        if re.search(pattern, lower):
            return domain, text[:80]

    if _OFF_TOPIC_PATTERN.search(lower) and not _DOMAIN_ANCHOR_PATTERN.search(lower):
        return "out_of_scope", text[:80]

    # Short follow-ups (e.g. "what about last month?" or "show details") inherit prior domain
    if prior_domain and prior_domain in VALID_DOMAINS and prior_domain != "out_of_scope" and len(lower.split()) <= 8:
        return prior_domain, text[:80]

    return "general", text[:80]
