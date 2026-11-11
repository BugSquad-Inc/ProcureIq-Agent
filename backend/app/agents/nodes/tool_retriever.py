"""
tool_retriever.py — LangGraph Tool Retrieval Node.

Delegates retrieval to the unified `ToolRetriever` service (`app.tools.retriever`)
so the LangGraph node and `POST /api/tools/retrieve` share one deterministic,
explainable Tool RAG pipeline.
"""
from __future__ import annotations

from typing import Any, Dict

import structlog
from langchain_core.messages import HumanMessage

from app.agents.state import AgentState
from app.config import get_settings
from app.infrastructure.database.session import AsyncSessionLocal
from app.tools.retriever import ToolRetriever

logger = structlog.get_logger("procureiq.tool_retriever")


async def tool_retriever_node(state: AgentState) -> Dict[str, Any]:
    """
    Retrieve top-k tools semantically relevant to the current user query.
    Returns updated state with `retrieved_tools` list populated.
    """
    settings = get_settings()
    messages = state["messages"]
    domain = state.get("domain", "general")
    intent = state.get("intent", "")

    last_user_msg = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            last_user_msg = m.content
            break

    if domain == "rag":
        return {"retrieved_tools": [_rag_tool_descriptor()]}
    if domain == "system":
        return {"retrieved_tools": [_system_search_tool_descriptor()]}

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
