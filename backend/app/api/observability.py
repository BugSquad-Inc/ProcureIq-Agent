"""
observability.py — Session Trace, Circuit Breaker & System Observability Endpoints.

Endpoints:
  GET  /api/sessions/{session_id}/trace     — Per-turn trace & candidate explainability
  GET  /api/system/observability            — Global Tool RAG, audit & circuit breaker telemetry
  POST /api/system/circuit-breakers/reset   — Reset all circuit breakers to CLOSED
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy import asc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.embedding.factory import EmbeddingProviderFactory
from app.core.resilience import CircuitBreakerRegistry
from app.infrastructure.database.models import AuditLog, KBChunk, Tool
from app.infrastructure.database.session import get_db
from app.tools.registry import count_tools_by_domain

router = APIRouter(prefix="/api", tags=["observability"])


@router.get("/sessions/{session_id}/trace")
async def get_session_trace(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    Return the structured execution trace for a session, including retrieved
    tool candidates, retrieval/execution latencies, HITL decisions, and LangSmith status.
    """
    settings = get_settings()
    stmt = (
        select(AuditLog)
        .where(AuditLog.session_id == session_id)
        .order_by(asc(AuditLog.created_at))
    )
    rows = (await db.execute(stmt)).scalars().all()

    traces = []
    for idx, log in enumerate(rows, start=1):
        payload: Dict[str, Any] = log.payload or {}
        traces.append(
            {
                "step": idx,
                "trace_id": payload.get("trace_id"),
                "action": log.action,
                "domain": log.domain,
                "tool_name": log.tool_name,
                "user_message": payload.get("user_message"),
                "extracted_params": payload.get("params", {}),
                "candidates_considered": payload.get("candidates", []),
                "retrieval_latency_ms": payload.get("retrieval_latency_ms"),
                "execution_ms": payload.get("execution_ms"),
                "circuit_open": payload.get("circuit_open", False),
                "result_summary": log.result_summary,
                "timestamp": log.created_at.isoformat() if log.created_at else None,
            }
        )

    langsmith_enabled = bool(settings.langchain_tracing_v2 and settings.langchain_api_key)
    return {
        "session_id": session_id,
        "total_events": len(traces),
        "langsmith": {
            "enabled": langsmith_enabled,
            "project": settings.langchain_project,
            "endpoint": settings.langchain_endpoint,
        },
        "traces": traces,
    }


@router.get("/system/observability")
async def get_system_observability(db: AsyncSession = Depends(get_db)):
    """Global system health, Tool RAG registry stats, audit counts, and circuit breakers."""
    settings = get_settings()
    provider = EmbeddingProviderFactory.get_provider()

    domain_counts = await count_tools_by_domain(db, active_only=True)
    kb_count_res = await db.execute(select(func.count(KBChunk.id)))
    kb_chunks = int(kb_count_res.scalar() or 0)

    audit_res = await db.execute(
        select(AuditLog.action, func.count(AuditLog.id)).group_by(AuditLog.action)
    )
    audit_counts = {row[0]: int(row[1]) for row in audit_res.fetchall()}

    return {
        "tool_registry": {
            "total_active_tools": sum(domain_counts.values()),
            "domains": domain_counts,
        },
        "knowledge_base": {
            "total_chunks": kb_chunks,
        },
        "audit_summary": audit_counts,
        "embedding": {
            "configured_provider": settings.embedding_provider,
            "active_model": provider.model_name,
            "target_dimension": settings.embedding_dimension,
        },
        "langsmith": {
            "enabled": bool(settings.langchain_tracing_v2 and settings.langchain_api_key),
            "project": settings.langchain_project,
        },
        "circuit_breakers": CircuitBreakerRegistry.all_statuses(),
    }


@router.post("/system/circuit-breakers/reset")
async def reset_circuit_breakers():
    """Reset all service circuit breakers back to CLOSED."""
    CircuitBreakerRegistry.reset_all()
    return {
        "status": "reset",
        "circuit_breakers": CircuitBreakerRegistry.all_statuses(),
    }

