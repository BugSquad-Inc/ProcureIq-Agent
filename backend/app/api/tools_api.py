"""
tools_api.py — Tool Registry & Knowledge Base REST API endpoints.

GET    /api/tools            — List tools (filter by domain, search, include_inactive)
GET    /api/tools/{name}     — Inspect a single tool schema & metadata
POST   /api/tools            — Register a new tool (with auto-embedding)
DELETE /api/tools/{name}     — Soft-deactivate a tool
POST   /api/tools/retrieve   — Semantic Tool RAG retrieval with explainable scores
POST   /api/kb/upload        — Upload a document to the knowledge base
"""
from __future__ import annotations

import io
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.config import get_settings
from app.core.embedding.base import align_embedding_dimension
from app.core.embedding.factory import EmbeddingProviderFactory
from app.core.security import AuthContext, assert_roles, get_auth_context
from app.infrastructure.database.models import KBChunk
from app.infrastructure.database.session import get_db
from app.tools.registry import (
    count_tools_by_domain,
    deactivate_tool,
    get_tool_by_name,
    list_tools,
    register_tool,
)
from app.tools.retriever import ToolRetriever

router = APIRouter(prefix="/api", tags=["tools", "knowledge-base"])
logger = structlog.get_logger("procureiq.api.tools")


ALLOWED_KB_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".csv", ".json", ".log"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
_TOOL_NAME_RE = re.compile(r"^[a-z0-9_]{2,128}$")
_DOMAIN_RE = re.compile(r"^[a-z0-9_-]{2,64}$")


# ── Pydantic models ───────────────────────────────────────────────────────────

class ToolCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=2, max_length=128)
    domain: str = Field(..., min_length=2, max_length=64)
    description: str = Field(..., min_length=5, max_length=2000)
    tool_schema: Dict[str, Any] = Field(default_factory=dict, alias="schema")
    endpoint: Optional[str] = None
    upsert: bool = False

    @field_validator("name")
    @classmethod
    def _validate_tool_name(cls, v: str) -> str:
        cleaned = (v or "").strip()
        if not _TOOL_NAME_RE.match(cleaned):
            raise ValueError("Tool name must use 2-128 lowercase letters, digits, or underscores.")
        return cleaned

    @field_validator("domain")
    @classmethod
    def _validate_domain(cls, v: str) -> str:
        cleaned = (v or "").strip().lower()
        if not _DOMAIN_RE.match(cleaned):
            raise ValueError("Domain must use 2-64 lowercase alphanumeric, '_' or '-' characters.")
        return cleaned

    @field_validator("description")
    @classmethod
    def _validate_description(cls, v: str) -> str:
        cleaned = (v or "").strip()
        if len(cleaned) < 5:
            raise ValueError("Tool description must be at least 5 non-whitespace characters.")
        return cleaned


class ToolRetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    domain: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def _clean_query(cls, v: str) -> str:
        cleaned = (v or "").strip()
        if not cleaned:
            raise ValueError("Query cannot be empty or whitespace.")
        return cleaned


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/tools")
async def list_all_tools(
    domain: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, description="Substring filter on name or description"),
    include_inactive: bool = Query(default=False),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """List tools in the registry with optional domain/keyword filters and domain counts."""
    tools = await list_tools(
        session,
        domain=domain,
        active_only=not include_inactive,
        search=q,
    )
    domain_counts = await count_tools_by_domain(session, active_only=not include_inactive)
    return {
        "total": len(tools),
        "domains": domain_counts,
        "tools": [
            {
                "id": str(t.id),
                "name": t.name,
                "domain": t.domain,
                "description": t.description,
                "schema": t.schema,
                "endpoint": t.endpoint,
                "is_active": t.is_active,
            }
            for t in tools
        ],
    }


@router.get("/tools/{name}")
async def get_tool(
    name: str,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """Fetch a single tool definition by exact name."""
    tool = await get_tool_by_name(session, name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found.")
    return {
        "id": str(tool.id),
        "name": tool.name,
        "domain": tool.domain,
        "description": tool.description,
        "schema": tool.schema,
        "endpoint": tool.endpoint,
        "is_active": tool.is_active,
    }


@router.post("/tools/retrieve")
async def retrieve_tools(
    req: ToolRetrieveRequest,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Semantic Tool Retrieval — the core Dynamic Tool RAG endpoint.
    Combines pgvector cosine search, OR-BM25 lexical search, RRF fusion, and
    reranking to return the top-k tools with explainable per-stage scores.
    """
    retriever = ToolRetriever(session=session)
    result = await retriever.retrieve(
        query_text=req.query,
        domain=req.domain,
        top_k=req.top_k,
    )
    return result.to_dict()


@router.post("/tools", status_code=201)
async def create_tool(
    tool: ToolCreate,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """Register a new tool in the registry with auto-generated embedding."""
    assert_roles(auth, ("operator", "finance_vp", "admin"), "create_tool")
    try:
        created = await register_tool(
            session=session,
            name=tool.name,
            domain=tool.domain,
            description=tool.description,
            schema=tool.tool_schema,
            endpoint=tool.endpoint,
            upsert=tool.upsert,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "id": str(created.id),
        "name": created.name,
        "domain": created.domain,
        "is_active": created.is_active,
    }


@router.delete("/tools/{name}")
async def remove_tool(
    name: str,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """Soft-deactivate a tool in the registry (requires finance_vp or admin)."""
    assert_roles(auth, ("finance_vp", "admin"), "delete_tool")
    deactivated = await deactivate_tool(session, name)
    if not deactivated:
        raise HTTPException(status_code=404, detail=f"Active tool '{name}' not found.")
    return {"name": name, "is_active": False}


@router.post("/kb/upload", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Upload a tenant-scoped document to the knowledge base for RAG queries.
    Supports PDF, DOCX, and plain text files.
    """
    assert_roles(auth, ("operator", "finance_vp", "admin"), "upload_kb_document")
    filename = os.path.basename(file.filename or "document.txt")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_KB_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{ext or 'unknown'}'. "
                f"Allowed formats: {', '.join(sorted(ALLOWED_KB_EXTENSIONS))}."
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail=f"Uploaded file '{filename}' is empty (0 bytes).")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Uploaded file '{filename}' exceeds 25 MB limit ({len(content)} bytes).",
        )

    text = _extract_text(filename, content)
    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail=f"Could not extract readable text from '{filename}'. Ensure PDF/DOCX is not encrypted or image-only.",
        )

    chunks = _simple_chunk(text, chunk_size=400)
    settings = get_settings()
    provider = EmbeddingProviderFactory.get_provider()
    raw_embeddings = await provider.embed_texts([c["text"] for c in chunks])
    embeddings = [
        align_embedding_dimension(vec, settings.embedding_dimension)
        for vec in raw_embeddings
    ]

    # Replace existing chunks ONLY for this tenant + filename
    await session.execute(
        delete(KBChunk).where(
            KBChunk.tenant_id == auth.tenant_id,
            KBChunk.document_name == filename,
        )
    )

    for chunk, emb in zip(chunks, embeddings):
        session.add(
            KBChunk(
                id=uuid.uuid4(),
                tenant_id=auth.tenant_id,
                document_name=filename,
                section_title=chunk.get("section"),
                text=chunk["text"],
                page=chunk.get("page", 1),
                embedding=emb,
            )
        )

    await session.commit()
    logger.info(
        "kb_document_ingested",
        filename=filename,
        tenant_id=auth.tenant_id,
        chunks=len(chunks),
    )
    return {"filename": filename, "tenant_id": auth.tenant_id, "chunks_created": len(chunks)}


@router.get("/kb/documents")
async def list_kb_documents(
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """List all uploaded knowledge base documents for the current tenant."""
    stmt = (
        select(
            KBChunk.document_name,
            func.count(KBChunk.id).label("chunks"),
            func.max(KBChunk.created_at).label("uploaded_at"),
        )
        .where(KBChunk.tenant_id == auth.tenant_id)
        .group_by(KBChunk.document_name)
        .order_by(func.max(KBChunk.created_at).desc())
    )
    rows = (await session.execute(stmt)).fetchall()
    return {
        "tenant_id": auth.tenant_id,
        "total_documents": len(rows),
        "documents": [
            {
                "document_name": r.document_name,
                "chunks": int(r.chunks),
                "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None,
            }
            for r in rows
        ],
    }


@router.delete("/kb/documents/{document_name}")
async def delete_kb_document(
    document_name: str,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """Delete all indexed chunks for a tenant's uploaded knowledge base document."""
    assert_roles(auth, ("operator", "finance_vp", "admin"), "delete_kb_document")
    res = await session.execute(
        delete(KBChunk).where(
            KBChunk.tenant_id == auth.tenant_id,
            KBChunk.document_name == document_name,
        )
    )
    await session.commit()
    if res.rowcount == 0:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{document_name}' not found in tenant '{auth.tenant_id}'.",
        )
    return {
        "document_name": document_name,
        "tenant_id": auth.tenant_id,
        "chunks_deleted": int(res.rowcount),
    }


def _extract_text(filename: str, content: bytes) -> str:
    """Extract text from PDF, DOCX, or plain text."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        try:
            import pymupdf
            doc = pymupdf.open(stream=content, filetype="pdf")
            return "\n".join(page.get_text() for page in doc)
        except Exception:
            return ""
    elif lower.endswith(".docx"):
        try:
            from docx import Document
            doc = Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception:
            return ""
    return content.decode("utf-8", errors="ignore")


def _simple_chunk(text: str, chunk_size: int = 400) -> List[Dict[str, Any]]:
    """Simple sentence-boundary chunker."""
    import re

    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip())
    chunks: List[Dict[str, Any]] = []
    current: List[str] = []
    tokens = 0
    for sent in sentences:
        t = max(1, len(sent) // 4)
        if tokens + t > chunk_size and current:
            chunks.append({"text": " ".join(current), "page": 1})
            current, tokens = [sent], t
        else:
            current.append(sent)
            tokens += t
    if current:
        chunks.append({"text": " ".join(current), "page": 1})
    return chunks
