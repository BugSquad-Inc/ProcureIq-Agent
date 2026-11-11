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
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.config import get_settings
from app.core.embedding.base import align_embedding_dimension
from app.core.embedding.factory import EmbeddingProviderFactory
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


# ── Pydantic models ───────────────────────────────────────────────────────────

class ToolCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=128)
    domain: str = Field(..., min_length=1, max_length=64)
    description: str = Field(..., min_length=1)
    tool_schema: Dict[str, Any] = Field(default_factory=dict, alias="schema")
    endpoint: Optional[str] = None
    upsert: bool = False


class ToolRetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1)
    domain: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=50)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/tools")
async def list_all_tools(
    domain: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, description="Substring filter on name or description"),
    include_inactive: bool = Query(default=False),
    session: AsyncSession = Depends(get_db),
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
async def get_tool(name: str, session: AsyncSession = Depends(get_db)):
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
async def retrieve_tools(req: ToolRetrieveRequest, session: AsyncSession = Depends(get_db)):
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
async def create_tool(tool: ToolCreate, session: AsyncSession = Depends(get_db)):
    """Register a new tool in the registry with auto-generated embedding."""
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
async def remove_tool(name: str, session: AsyncSession = Depends(get_db)):
    """Soft-deactivate a tool in the registry."""
    deactivated = await deactivate_tool(session, name)
    if not deactivated:
        raise HTTPException(status_code=404, detail=f"Active tool '{name}' not found.")
    return {"name": name, "is_active": False}


@router.post("/kb/upload", status_code=201)
async def upload_document(file: UploadFile = File(...), session: AsyncSession = Depends(get_db)):
    """
    Upload a document to the knowledge base for RAG queries.
    Supports PDF, DOCX, and plain text files.
    """
    content = await file.read()
    filename = file.filename or "document.txt"
    text = _extract_text(filename, content)
    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from file.")

    chunks = _simple_chunk(text, chunk_size=400)
    settings = get_settings()
    provider = EmbeddingProviderFactory.get_provider()
    raw_embeddings = await provider.embed_texts([c["text"] for c in chunks])
    embeddings = [
        align_embedding_dimension(vec, settings.embedding_dimension)
        for vec in raw_embeddings
    ]

    for chunk, emb in zip(chunks, embeddings):
        session.add(
            KBChunk(
                id=uuid.uuid4(),
                document_name=filename,
                section_title=chunk.get("section"),
                text=chunk["text"],
                page=chunk.get("page", 1),
                embedding=emb,
            )
        )

    await session.commit()
    logger.info("kb_document_ingested", filename=filename, chunks=len(chunks))
    return {"filename": filename, "chunks_created": len(chunks)}


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
