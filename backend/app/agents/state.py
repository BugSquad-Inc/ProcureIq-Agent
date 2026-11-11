"""
state.py — LangGraph AgentState definition for ProcureIQ.

The state is the single source of truth passed between every graph node.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


def _merge_execution_steps(
    existing: Optional[List[Dict[str, Any]]],
    update: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Append step traces within a turn; reset cleanly when a new turn begins."""
    if update and len(update) == 1 and update[0].get("__reset__"):
        return []
    return list(existing or []) + list(update or [])


class AgentState(TypedDict):
    # ── Conversation ──────────────────────────────────────────────────────────
    messages: Annotated[List[BaseMessage], add_messages]

    # ── Routing ───────────────────────────────────────────────────────────────
    domain: Optional[str]
    intent: Optional[str]

    # ── Tool Retrieval & Selection ────────────────────────────────────────────
    retrieved_tools: List[Dict[str, Any]]
    selected_tool: Optional[str]
    extracted_params: Dict[str, Any]

    # ── Tool Execution ────────────────────────────────────────────────────────
    tool_result: Optional[Any]
    tool_error: Optional[str]

    # ── Human-in-the-Loop ─────────────────────────────────────────────────────
    require_hitl: bool
    confirm_all: Optional[bool]
    requires_confirmation: bool
    hitl_approved: Optional[bool]
    pending_action: Optional[Dict[str, Any]]

    # ── Step-by-Step Pipeline Execution Trace ─────────────────────────────────
    execution_steps: Annotated[List[Dict[str, Any]], _merge_execution_steps]

    # ── Output & Session ──────────────────────────────────────────────────────
    final_response: Optional[str]
    session_id: str
    tenant_id: str
    user_role: Optional[str]
    trace_id: Optional[str]
    retrieval_latency_ms: Optional[float]
