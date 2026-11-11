"""
synthesizer.py — Response Synthesis Node.

Generates clean, business-ready responses from tool results (and handles HITL
cancellations, errors, RAG citations, and offline fallback formatting).
"""
from __future__ import annotations

import json
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
    tool_result = state.get("tool_result")
    tool_error = state.get("tool_error")
    tool_name = state.get("selected_tool") or "unknown"

    if isinstance(tool_result, dict) and tool_result.get("status") == "cancelled":
        response = f"Cancelled `{tool_name}` — no action was executed."
        return {"final_response": response, "messages": [AIMessage(content=response)]}

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
        return {"final_response": response, "messages": [AIMessage(content=response)]}

    result_str = (
        json.dumps(tool_result, indent=2)
        if isinstance(tool_result, dict)
        else str(tool_result or "No data returned.")
    )

    prompt = f"{_SYSTEM_PROMPT}\n\nTool: {tool_name}\nResult:\n{result_str[:3000]}"
    llm_response = await call_gemini(prompt, temperature=0.3, timeout=15.0)
    if llm_response:
        return {"final_response": llm_response, "messages": [AIMessage(content=llm_response)]}

    response = _format_offline_fallback(tool_name, tool_result)
    return {"final_response": response, "messages": [AIMessage(content=response)]}


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
