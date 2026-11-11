"""
system_search.py — System Search Tool.

Two search modes:
  1. Tool Capability Search: "What tools are available for managing invoices?"
     → Uses ToolRetriever (Hybrid pgvector + OR-BM25) to surface relevant tools.
  2. Request History Search: "What was the status of my last request?"
     → Searches the PostgreSQL `audit_log` table for the current session.
"""
from __future__ import annotations

from typing import Any, Dict

import structlog
from sqlalchemy import desc, select

from app.infrastructure.database.models import AuditLog
from app.infrastructure.database.session import AsyncSessionLocal
from app.tools.retriever import ToolRetriever

logger = structlog.get_logger("procureiq.system_search")

HISTORY_KEYWORDS = {
    "status of my last",
    "last request",
    "request history",
    "session history",
    "audit history",
    "did i",
    "what happened",
    "previous request",
}


async def execute_system_search(
    query: str,
    session_id: str,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """Route to tool capability search or tenant-scoped audit request history search."""
    lower = query.lower()
    if any(kw in lower for kw in HISTORY_KEYWORDS):
        return await _search_history(session_id, limit=10, tenant_id=tenant_id)
    return await _search_tools(query, limit=8)


async def _search_tools(query: str, limit: int = 8) -> Dict[str, Any]:
    """Find tools matching a natural-language capability query using ToolRetriever."""
    async with AsyncSessionLocal() as session:
        retriever = ToolRetriever(session=session)
        result = await retriever.retrieve(query_text=query, domain=None, top_k=limit)

    tools = [
        {
            "name": t.name,
            "domain": t.domain,
            "description": t.description,
            "score": t.final_score,
        }
        for t in result.tools
    ]
    return {
        "search_type": "tool_capabilities",
        "query": query,
        "total_active_tools": result.total_active_tools,
        "tools_found": len(tools),
        "tools": tools,
    }


async def _search_history(
    session_id: str,
    limit: int = 10,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """Return recent agent actions for this session & tenant from the audit log."""
    async with AsyncSessionLocal() as session:
        stmt = (
            select(AuditLog)
            .where(
                AuditLog.session_id == session_id,
                AuditLog.tenant_id == tenant_id,
            )
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
        )
        result = await session.execute(stmt)
        logs = result.scalars().all()

    history = [
        {
            "action": log.action,
            "tool": log.tool_name,
            "domain": log.domain,
            "result": log.result_summary,
            "timestamp": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
    return {
        "search_type": "request_history",
        "session_id": session_id,
        "records_found": len(history),
        "history": history,
    }
