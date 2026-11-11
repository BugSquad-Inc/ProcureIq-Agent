"""
registry.py — Tool Registry service.

CRUD and batch operations for the Tool Registry (`tools` table):
  - Register / upsert tools with automatic embedding generation
  - Batch upsert with batched embedding computation (fast seeding at scale)
  - List / search / filter tools by domain or keyword
  - Deactivate tools without deletion
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.embedding.base import align_embedding_dimension
from app.core.embedding.factory import EmbeddingProviderFactory
from app.infrastructure.database.models import Tool

logger = structlog.get_logger("procureiq.registry")


def _tool_embedding_text(name: str, domain: str, description: str) -> str:
    """Format tool metadata for dense embedding (human-readable name + domain + description)."""
    readable_name = name.replace("_", " ")
    return f"{readable_name} ({domain}): {description}"


async def register_tool(
    session: AsyncSession,
    name: str,
    domain: str,
    description: str,
    schema: Dict[str, Any],
    endpoint: Optional[str] = None,
    upsert: bool = False,
) -> Tool:
    """
    Register a new tool and auto-generate its aligned embedding for semantic retrieval.
    If `upsert=True` and a tool with `name` exists, updates it in place.
    """
    settings = get_settings()
    provider = EmbeddingProviderFactory.get_provider()
    embed_text = _tool_embedding_text(name, domain, description)
    raw_vec = await provider.embed_query(embed_text)
    embedding = align_embedding_dimension(raw_vec, settings.embedding_dimension)

    existing = await get_tool_by_name(session, name)
    if existing is not None:
        if not upsert:
            raise ValueError(f"Tool '{name}' already exists.")
        existing.domain = domain
        existing.description = description
        existing.schema = schema
        existing.endpoint = endpoint
        existing.is_active = True
        existing.embedding = embedding
        await session.commit()
        await session.refresh(existing)
        logger.info("tool_updated", name=name, domain=domain)
        return existing

    tool = Tool(
        id=uuid.uuid4(),
        name=name,
        domain=domain,
        description=description,
        schema=schema,
        endpoint=endpoint,
        is_active=True,
        embedding=embedding,
    )
    session.add(tool)
    await session.commit()
    await session.refresh(tool)
    logger.info("tool_registered", name=name, domain=domain)
    return tool


async def upsert_tools_batch(
    session: AsyncSession,
    tools_data: List[Dict[str, Any]],
    overwrite_existing: bool = False,
) -> Dict[str, int]:
    """
    Batch-embed and insert/update tools in minimal database round-trips.
    Returns counts: {"created": int, "updated": int, "skipped": int}.
    """
    if not tools_data:
        return {"created": 0, "updated": 0, "skipped": 0}

    settings = get_settings()
    existing_res = await session.execute(select(Tool))
    existing_by_name = {t.name: t for t in existing_res.scalars().all()}

    to_create: List[Dict[str, Any]] = []
    to_update: List[Dict[str, Any]] = []
    skipped = 0

    for item in tools_data:
        if item["name"] in existing_by_name:
            if overwrite_existing:
                to_update.append(item)
            else:
                skipped += 1
        else:
            to_create.append(item)

    pending = to_create + to_update
    if not pending:
        return {"created": 0, "updated": 0, "skipped": skipped}

    provider = EmbeddingProviderFactory.get_provider()
    texts = [
        _tool_embedding_text(item["name"], item["domain"], item["description"])
        for item in pending
    ]
    raw_vectors = await provider.embed_texts(texts)
    aligned_vectors = [
        align_embedding_dimension(vec, settings.embedding_dimension)
        for vec in raw_vectors
    ]

    for item, emb in zip(pending, aligned_vectors):
        if item["name"] in existing_by_name:
            tool = existing_by_name[item["name"]]
            tool.domain = item["domain"]
            tool.description = item["description"]
            tool.schema = item.get("schema", {})
            tool.endpoint = item.get("endpoint")
            tool.is_active = True
            tool.embedding = emb
        else:
            session.add(
                Tool(
                    id=uuid.uuid4(),
                    name=item["name"],
                    domain=item["domain"],
                    description=item["description"],
                    schema=item.get("schema", {}),
                    endpoint=item.get("endpoint"),
                    is_active=True,
                    embedding=emb,
                )
            )

    await session.commit()
    logger.info(
        "tools_batch_upserted",
        created=len(to_create),
        updated=len(to_update),
        skipped=skipped,
    )
    return {"created": len(to_create), "updated": len(to_update), "skipped": skipped}


async def get_tool_by_name(session: AsyncSession, name: str) -> Optional[Tool]:
    stmt = select(Tool).where(Tool.name == name)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_tools(
    session: AsyncSession,
    domain: Optional[str] = None,
    active_only: bool = True,
    search: Optional[str] = None,
) -> List[Tool]:
    stmt = select(Tool)
    if domain:
        stmt = stmt.where(Tool.domain == domain)
    if active_only:
        stmt = stmt.where(Tool.is_active == True)  # noqa: E712
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(or_(Tool.name.ilike(pattern), Tool.description.ilike(pattern)))
    stmt = stmt.order_by(Tool.domain.asc(), Tool.name.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_tools_by_domain(session: AsyncSession, active_only: bool = True) -> Dict[str, int]:
    stmt = select(Tool.domain, func.count(Tool.id)).group_by(Tool.domain)
    if active_only:
        stmt = stmt.where(Tool.is_active == True)  # noqa: E712
    res = await session.execute(stmt)
    return {row[0]: int(row[1]) for row in res.fetchall()}


async def deactivate_tool(session: AsyncSession, name: str) -> bool:
    tool = await get_tool_by_name(session, name)
    if tool and tool.is_active:
        tool.is_active = False
        await session.commit()
        logger.info("tool_deactivated", name=name)
        return True
    return False
