"""
tool_retriever.py — LangGraph Tool Retrieval Node.

Delegates retrieval to the unified `ToolRetriever` service (`app.tools.retriever`)
so the LangGraph node and `POST /api/tools/retrieve` share one deterministic,
explainable Tool RAG pipeline.
"""
from __future__ import annotations

import time
from typing import Any, Dict

import structlog
from langchain_core.messages import HumanMessage

from app.agents.state import AgentState
from app.config import get_settings
from app.core.hybrid_search import normalize_query_text
from app.infrastructure.database.session import AsyncSessionLocal
from app.tools.retriever import ToolRetriever

logger = structlog.get_logger("procureiq.tool_retriever")


async def tool_retriever_node(state: AgentState) -> Dict[str, Any]:
    """
    Retrieve top-k tools semantically relevant to the current user query.
    Returns updated state with `retrieved_tools` list and execution step telemetry.
    """
    started = time.perf_counter()
    settings = get_settings()
    messages = state["messages"]
    domain = state.get("domain", "general")
    intent = state.get("intent", "")

    last_user_msg = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            last_user_msg = normalize_query_text(str(m.content))
            break

    if domain == "out_of_scope":
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "retrieved_tools": [],
            "retrieval_latency_ms": elapsed_ms,
            "execution_steps": [
                {
                    "node": "tool_retriever",
                    "title": "Scope Guard",
                    "status": "completed",
                    "duration_ms": elapsed_ms,
                    "detail": "Query is outside enterprise payments/procurement/KB scope; skipped tool retrieval.",
                }
            ],
        }

    if domain == "rag":
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "retrieved_tools": [_rag_tool_descriptor()],
            "retrieval_latency_ms": elapsed_ms,
            "execution_steps": [
                {
                    "node": "tool_retriever",
                    "title": "Tool RAG Retriever",
                    "status": "completed",
                    "duration_ms": elapsed_ms,
                    "detail": "Bound built-in tool: rag_query (Knowledge Base Q&A)",
                }
            ],
        }
    if domain == "system":
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "retrieved_tools": [_system_search_tool_descriptor()],
            "retrieval_latency_ms": elapsed_ms,
            "execution_steps": [
                {
                    "node": "tool_retriever",
                    "title": "Tool RAG Retriever",
                    "status": "completed",
                    "duration_ms": elapsed_ms,
                    "detail": "Bound built-in tool: system_search (Capabilities & Audit History)",
                }
            ],
        }

    tenant_id = state.get("tenant_id") or "default"

    if domain == "general":
        # Check if uploaded tenant KB docs can answer uncategorized queries before falling back to scope guard
        from app.core.hybrid_search import HybridSearchService

        async with AsyncSessionLocal() as kb_session:
            kb_hits = await HybridSearchService(session=kb_session).search_hybrid(
                query_text=last_user_msg,
                limit=3,
                tenant_id=tenant_id,
            )
        if any(h.bm25_score > 0 or h.cosine_sim >= 0.48 for h in kb_hits):
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            return {
                "domain": "rag",
                "retrieved_tools": [_rag_tool_descriptor()],
                "retrieval_latency_ms": elapsed_ms,
                "execution_steps": [
                    {
                        "node": "tool_retriever",
                        "title": "Tool RAG Retriever",
                        "status": "completed",
                        "duration_ms": elapsed_ms,
                        "detail": "Matched uploaded knowledge base document(s); routed to rag_query.",
                    }
                ],
            }

    if intent and intent.lower() not in last_user_msg.lower():
        query_text = f"{intent} {last_user_msg}".strip()
    else:
        query_text = last_user_msg.strip()

    async with AsyncSessionLocal() as session:
        retriever = ToolRetriever(session=session)
        result = await retriever.retrieve(
            query_text=query_text,
            domain=domain,
            top_k=settings.tool_retrieval_top_k,
        )

    tools = [t.to_dict() for t in result.tools]
    if domain == "general" and tools:
        best = tools[0]
        if (
            float(best.get("bm25_score", 0.0)) == 0.0
            and float(best.get("rerank_score", 0.0)) < 0.28
            and float(best.get("cosine_sim", 0.0)) < 0.42
        ):
            logger.info(
                "general_query_out_of_scope",
                best_tool=best.get("name"),
                cosine=best.get("cosine_sim"),
                rerank=best.get("rerank_score"),
            )
            return {
                "domain": "out_of_scope",
                "retrieved_tools": [],
                "retrieval_latency_ms": result.latency_ms,
                "execution_steps": [
                    {
                        "node": "tool_retriever",
                        "title": "Scope Guard",
                        "status": "completed",
                        "duration_ms": result.latency_ms,
                        "detail": (
                            f"No relevant KB docs or tools matched (top cosine={best.get('cosine_sim', 0):.2f}, "
                            "bm25=0); refused safely as out-of-scope."
                        ),
                    }
                ],
            }
    top_preview = ", ".join(f"{t['name']}({t.get('final_score', 0)})" for t in tools[:3])
    logger.info(
        "tools_retrieved",
        count=len(tools),
        domain=domain,
        latency_ms=result.latency_ms,
        query_preview=query_text[:60],
    )
    return {
        "retrieved_tools": tools,
        "retrieval_latency_ms": result.latency_ms,
        "execution_steps": [
            {
                "node": "tool_retriever",
                "title": "Tool RAG Retriever",
                "status": "completed",
                "duration_ms": result.latency_ms,
                "detail": (
                    f"Retrieved top-{len(tools)} of {result.total_active_tools} tools "
                    f"[{top_preview}]"
                ),
            }
        ],
    }


def _rag_tool_descriptor() -> Dict[str, Any]:
    return {
        "name": "rag_query",
        "domain": "rag",
        "description": "Query the knowledge base (uploaded documents, SOPs, contracts, policies) to answer factual questions with cited sources.",
        "schema": {"query": "string"},
        "endpoint": "internal:rag",
    }


def _system_search_tool_descriptor() -> Dict[str, Any]:
    return {
        "name": "system_search",
        "domain": "system",
        "description": "Search available tools by capability or query audit history to check the status of past requests.",
        "schema": {"query": "string"},
        "endpoint": "internal:system",
    }
