"""
graph.py — LangGraph StateGraph definition for ProcureIQ Agent.

Flow:
  START
    └─► intent_classifier   (multi-turn routing & domain classification)
          └─► tool_retriever (Tool RAG: pgvector + OR-BM25 + RRF + Reranker)
                └─► tool_selector (select tool + KB enrichment + check HITL)
                      ├─► hitl_gate (interrupt() for mutating write ops)
                      │      ├─► approved  ─► executor
                      │      └─► rejected  ─► synthesizer
                      └─► executor (circuit breaker + retries + audit log)
                            └─► synthesizer (response + AIMessage)
                                  └─► END
"""
from __future__ import annotations

import time
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
    started = time.perf_counter()
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

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
    if approved:
        updated_params = (
            decision.get("params")
            if isinstance(decision, dict) and isinstance(decision.get("params"), dict)
            else None
        )
        approver_role = (
            decision.get("approver_role")
            if isinstance(decision, dict) and decision.get("approver_role")
            else None
        )
        return {
            "hitl_approved": True,
            "requires_confirmation": False,
            **({"extracted_params": updated_params} if updated_params is not None else {}),
            **({"user_role": approver_role} if approver_role is not None else {}),
            "execution_steps": [
                {
                    "node": "hitl_gate",
                    "title": "HITL Safety Gate",
                    "status": "completed",
                    "duration_ms": elapsed_ms,
                    "detail": f"User approved `{pending.get('tool')}` execution",
                }
            ],
        }

    tool_name = state.get("selected_tool")
    cancel_step = {
        "node": "hitl_gate",
        "title": "HITL Safety Gate",
        "status": "cancelled",
        "duration_ms": elapsed_ms,
        "detail": f"User cancelled `{tool_name}` before execution",
    }
    prior_steps = list(state.get("execution_steps") or [])
    await write_audit(
        session_id=state.get("session_id", "unknown"),
        action="action_cancelled",
        domain=state.get("domain"),
        tool_name=tool_name,
        payload={
            "trace_id": state.get("trace_id"),
            "params": params,
            "retrieval_latency_ms": state.get("retrieval_latency_ms"),
            "execution_steps": prior_steps + [cancel_step],
        },
        result="Cancelled by user at HITL confirmation gate.",
        tenant_id=state.get("tenant_id") or "default",
    )
    return {
        "hitl_approved": False,
        "requires_confirmation": False,
        "pending_action": None,
        "tool_result": {"status": "cancelled", "tool": tool_name, "params": params},
        "execution_steps": [cancel_step],
    }


def _route_after_selector(state: AgentState) -> str:
    if state.get("requires_confirmation"):
        return "hitl_gate"
    if not state.get("selected_tool"):
        return "synthesizer"
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
            "synthesizer": "synthesizer",
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
_durable_graph = None
_durable_checkpointer = None


def get_dev_graph():
    """Return singleton compiled LangGraph instance with InMemorySaver checkpointer."""
    global _dev_graph, _dev_checkpointer
    if _dev_graph is None:
        _dev_checkpointer = InMemorySaver()
        _dev_graph = build_graph(checkpointer=_dev_checkpointer)
    return _dev_graph


def get_durable_graph():
    """
    Return singleton compiled LangGraph instance backed by durable PostgreSQL checkpoints.
    Falls back to InMemorySaver only when `use_durable_checkpointer=False`.
    """
    global _durable_graph, _durable_checkpointer
    if _durable_graph is None:
        from app.config import get_settings
        if get_settings().use_durable_checkpointer:
            from app.agents.postgres_checkpointer import PostgresCheckpointSaver
            _durable_checkpointer = PostgresCheckpointSaver()
        else:
            _durable_checkpointer = InMemorySaver()
        _durable_graph = build_graph(checkpointer=_durable_checkpointer)
    return _durable_graph
