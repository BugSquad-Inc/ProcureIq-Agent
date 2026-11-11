"""
state.py — LangGraph AgentState definition for ProcureIQ.

The state is the single source of truth passed between every graph node.
Using TypedDict + Annotated[list, add_messages] ensures LangGraph correctly
merges message lists across multi-turn conversations instead of overwriting them.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    # ── Conversation ──────────────────────────────────────────────────────────
    # LangGraph appends messages; never overwrite this field manually.
    messages: Annotated[List[BaseMessage], add_messages]

    # ── Routing ───────────────────────────────────────────────────────────────
    # Domain: "payments" | "invoicing" | "analytics" | "disputes" | "procurement" | "rag" | "system" | "general"
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
    requires_confirmation: bool
    hitl_approved: Optional[bool]
    pending_action: Optional[Dict[str, Any]]

    # ── Output & Session ──────────────────────────────────────────────────────
    final_response: Optional[str]
    session_id: str
    trace_id: Optional[str]
    retrieval_latency_ms: Optional[float]
