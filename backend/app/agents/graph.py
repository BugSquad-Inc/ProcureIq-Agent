"""
graph.py — LangGraph StateGraph definition for ProcureIQ Agent.

Flow:
  START
    └─► intent_classifier   (multi-turn routing & domain classification)
          └─► tool_retriever (Tool RAG: pgvector + OR-BM25 + RRF + Reranker)
                └─► tool_selector (select best tool + extract params + check HITL)
                      ├─► hitl_gate (interrupt() for mutating write ops)
                      │      ├─► approved  ─► executor
                      │      └─► rejected  ─► synthesizer
                      └─► executor (run tool + audit log)
                            └─► synthesizer (response + AIMessage)
                                  └─► END
"""
from __future__ import annotations

from typing import Any, Dict, Optional
import structlog
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

try:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
except ImportError:  # pragma: no cover
    AsyncPostgresSaver = None

from app.agents.nodes.executor import executor_node, tool_selector_node, write_audit
from app.agents.nodes.intent_classifier import intent_classifier_node
from app.agents.nodes.synthesizer import synthesizer_node
from app.agents.nodes.tool_retriever import tool_retriever_node
from app.agents.state import AgentState

logger = structlog.get_logger("procureiq.graph")


async def hitl_gate_node(state: AgentState) -> Dict[str, Any]:
    """
    Pause execution via LangGraph `interrupt()` for mutating write operations
    until the user approves or cancels.
    """
    pending = state.get("pending_action") or {
        "tool": state.get("selected_tool"),
        "domain": state.get("domain"),
        "params": state.get("extracted_params") or {},
    }
    params = pending.get("params") or {}
    param_summary = ", ".join(f"{k}: {v}" for k, v in params.items()) or "default parameters"

    decision = interrupt(
        {
            **pending,
            "confirmation_prompt": (
                f"I'm ready to run **{pending.get('tool')}** ({param_summary}). "
                f"Confirm? [Yes/No]"
            ),
        }
    )

    approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
    if approved:
        return {
            "hitl_approved": True,
            "requires_confirmation": False,
        }

    tool_name = state.get("selected_tool")
    await write_audit(
        session_id=state.get("session_id", "unknown"),
        action="action_cancelled",
        domain=state.get("domain"),
        tool_name=tool_name,
        payload={"params": params},
        result="Cancelled by user at HITL confirmation gate.",
    )
    return {
        "hitl_approved": False,
        "requires_confirmation": False,
        "pending_action": None,
        "tool_result": {"status": "cancelled", "tool": tool_name, "params": params},
    }


def _route_after_selector(state: AgentState) -> str:
    if state.get("requires_confirmation"):
        return "hitl_gate"
    return "executor"


def _route_after_hitl(state: AgentState) -> str:
    if state.get("hitl_approved"):
        return "executor"
    return "synthesizer"


def build_graph(checkpointer=None):
    """Build and compile the ProcureIQ LangGraph StateGraph."""
    builder = StateGraph(AgentState)

    builder.add_node("intent_classifier", intent_classifier_node)
    builder.add_node("tool_retriever", tool_retriever_node)
    builder.add_node("tool_selector", tool_selector_node)
    builder.add_node("hitl_gate", hitl_gate_node)
    builder.add_node("executor", executor_node)
    builder.add_node("synthesizer", synthesizer_node)

    builder.add_edge(START, "intent_classifier")
    builder.add_edge("intent_classifier", "tool_retriever")
    builder.add_edge("tool_retriever", "tool_selector")

    builder.add_conditional_edges(
        "tool_selector",
        _route_after_selector,
        {
            "hitl_gate": "hitl_gate",
            "executor": "executor",
        },
    )

    builder.add_conditional_edges(
        "hitl_gate",
        _route_after_hitl,
        {
            "executor": "executor",
            "synthesizer": "synthesizer",
        },
    )

    builder.add_edge("executor", "synthesizer")
    builder.add_edge("synthesizer", END)

    return builder.compile(checkpointer=checkpointer)


_dev_graph = None
_dev_checkpointer: Optional[InMemorySaver] = None


def get_dev_graph():
    """Return singleton compiled LangGraph instance with InMemorySaver checkpointer."""
    global _dev_graph, _dev_checkpointer
    if _dev_graph is None:
        _dev_checkpointer = InMemorySaver()
        _dev_graph = build_graph(checkpointer=_dev_checkpointer)
    return _dev_graph
