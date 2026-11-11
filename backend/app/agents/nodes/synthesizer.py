"""
synthesizer.py — Response Synthesis Node.

Generates clean, business-ready responses from tool results (and handles HITL
cancellations, errors, RAG citations, and offline fallback formatting).
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict

import structlog
from langchain_core.messages import AIMessage

from app.agents.state import AgentState
from app.core.llm_client import call_gemini

logger = structlog.get_logger("procureiq.synthesizer")

_SYSTEM_PROMPT = """You are ProcureIQ, an enterprise procurement and payments intelligence assistant.

Based on the tool result below, write a clear, concise, and professional response to the user.
- If it's data/analytics: present numbers cleanly with key highlights.
- If it's a document/RAG answer: state the answer directly and cite sources.
- If it was a successful action: confirm what was done and show reference IDs.
- If there was an error: explain what happened clearly and suggest next steps.
Keep your response concise (under 200 words).
"""


async def synthesizer_node(state: AgentState) -> Dict[str, Any]:
    """Generate the final natural language response and append AIMessage to conversation."""
    started = time.perf_counter()
    tool_result = state.get("tool_result")
    tool_error = state.get("tool_error")
    tool_name = state.get("selected_tool") or "unknown"

    def _step(detail: str) -> list:
        return [
            {
                "node": "synthesizer",
                "title": "Response Synthesizer",
                "status": "completed",
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "detail": detail,
            }
        ]

    if isinstance(tool_result, dict) and tool_result.get("status") == "cancelled":
        response = f"Cancelled `{tool_name}` — no action was executed."
        return {
            "final_response": response,
            "messages": [AIMessage(content=response)],
            "execution_steps": _step("Formatted HITL cancellation confirmation"),
        }

    if state.get("domain") == "out_of_scope" or tool_error == "OUT_OF_SCOPE":
        is_greeting = (state.get("intent") or "").lower() == "greeting"
        if is_greeting:
            response = (
                "Hello! I'm **ProcureIQ**, your enterprise FinTech & Procurement Intelligence assistant. "
                "I can help you with:\n"
                "- **Payments & Payouts** (e.g., `Send $500 to john@example.com`, `Check account balance`, `What is the status of subscription SUB-402?`)\n"
                "- **Invoicing** (e.g., `Remind Priya Nair about overdue INVOICE_006`, `Get INVOICE_001`)\n"
                "- **Procurement & Vendors** (e.g., `Approve purchase order PO-2026-0302`)\n"
                "- **Disputes, KYC & Analytics** (e.g., `Look up dispute PP-D-30912 details`, `What was my total sales volume last month?`)\n"
                "- **Policy & Document Q&A** (e.g., `According to our budget policy, what is our FY2026 IT budget allocation?`, `What tools are available?`)"
            )
            step_msg = "Handled greeting with ProcureIQ capabilities guide"
        else:
            response = (
                "I'm **ProcureIQ**, a specialized assistant for enterprise **Payments, Invoicing, Procurement, "
                "Disputes/KYC, Financial Analytics, and Uploaded Policy Documents**—so I can't answer unrelated general topics.\n\n"
                "Try asking something within scope, such as:\n"
                "- `Get details for INVOICE_001` or `Remind Priya Nair about overdue INVOICE_006`\n"
                "- `Approve purchase order PO-2026-0301 for $32,000`\n"
                "- `According to our budget policy, what is our FY2026 IT budget allocation?`\n"
                "- `What tools are available for managing invoices?`"
            )
            step_msg = "Declined irrelevant/out-of-scope query cleanly with guidance"
        return {
            "final_response": response,
            "messages": [AIMessage(content=response)],
            "execution_steps": _step(step_msg),
        }

    if tool_error and not tool_result:
        alts = [
            t.get("name")
            for t in (state.get("retrieved_tools") or [])
            if t.get("name") and t.get("name") != tool_name
        ][:3]
        alt_hint = f" Alternative tools retrieved: {', '.join(alts)}." if alts else ""
        response = (
            f"I encountered an issue running `{tool_name}`: {tool_error}.{alt_hint} "
            "Please retry shortly or ask `What tools are available?` to see alternatives."
        )
        return {
            "final_response": response,
            "messages": [AIMessage(content=response)],
            "execution_steps": _step("Formatted graceful error recovery response"),
        }

    if tool_name == "rag_query" and isinstance(tool_result, dict) and tool_result.get("answer"):
        response = _format_offline_fallback(tool_name, tool_result)
        return {
            "final_response": response,
            "messages": [AIMessage(content=response)],
            "execution_steps": _step("Formatted grounded RAG answer with citations"),
        }

    result_str = (
        json.dumps(tool_result, indent=2)
        if isinstance(tool_result, dict)
        else str(tool_result or "No data returned.")
    )

    prompt = f"{_SYSTEM_PROMPT}\n\nTool: {tool_name}\nResult:\n{result_str[:3000]}"
    llm_response = await call_gemini(prompt, temperature=0.3, timeout=15.0)
    if llm_response and len(llm_response.strip()) >= 24:
        verified_response = _ensure_key_identifiers(llm_response.strip(), tool_name, tool_result)
        return {
            "final_response": verified_response,
            "messages": [AIMessage(content=verified_response)],
            "execution_steps": _step("Synthesized natural-language summary via Gemini"),
        }

    response = _format_offline_fallback(tool_name, tool_result)
    return {
        "final_response": response,
        "messages": [AIMessage(content=response)],
        "execution_steps": _step("Formatted structured tool result summary"),
    }


def _ensure_key_identifiers(text: str, tool_name: str, tool_result: Any) -> str:
    """Ensure critical reference IDs and audited tool names are never dropped in synthesis."""
    if not isinstance(tool_result, dict):
        return text

    missing: list[str] = []
    for key in (
        "transaction_id",
        "invoice_id",
        "po_id",
        "dispute_id",
        "refund_id",
        "payout_batch_id",
        "flag_id",
        "order_id",
    ):
        val = tool_result.get(key)
        if isinstance(val, str) and val and val not in text:
            missing.append(f"{key}={val}")

    if tool_name == "system_search" and tool_result.get("search_type") == "request_history":
        for h in (tool_result.get("history") or [])[:5]:
            tname = h.get("tool")
            if isinstance(tname, str) and tname and tname not in text:
                missing.append(f"tool={tname}")

    if not missing:
        return text
    return f"{text}\n\nReference details: {', '.join(missing)}"


def _format_offline_fallback(tool_name: str, tool_result: Any) -> str:
    """Clean, readable structured summary when Gemini API key is unconfigured."""
    if not isinstance(tool_result, dict):
        return f"Executed `{tool_name}`:\n{tool_result}"

    if tool_name == "rag_query":
        answer = tool_result.get("answer", "")
        sources = tool_result.get("sources") or []
        if sources:
            src_names = ", ".join(sorted({s.get("document", "Unknown") for s in sources}))
            return f"{answer}\n\nSources: {src_names}"
        return answer

    if tool_name == "system_search":
        search_type = tool_result.get("search_type")
        if search_type == "tool_capabilities":
            tools = tool_result.get("tools") or []
            if not tools:
                return "No matching tools found in the registry."
            lines = [f"- **{t['name']}** ({t['domain']}): {t['description']}" for t in tools[:8]]
            return f"Found {len(tools)} matching tool(s):\n" + "\n".join(lines)
        history = tool_result.get("history") or []
        if not history:
            return "No previous actions recorded for this session yet."
        lines = [f"- `{h['tool']}` ({h['action']}): {h['result']}" for h in history]
        return "Recent session history:\n" + "\n".join(lines)

    if "message" in tool_result:
        details = {k: v for k, v in tool_result.items() if k != "message"}
        detail_str = ", ".join(f"{k}={v}" for k, v in details.items())
        return f"{tool_result['message']}" + (f" ({detail_str})" if detail_str else "")

    lines = [f"- **{k}**: {v}" for k, v in tool_result.items()]
    return f"Result from `{tool_name}`:\n" + "\n".join(lines)
