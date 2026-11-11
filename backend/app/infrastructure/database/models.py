"""
models.py — SQLAlchemy ORM models for ProcureIQ Agent.

Tables:
  tools                   — Tool Registry (name, domain, description, embedding, schema)
  kb_chunks               — Multi-tenant Knowledge Base chunks for the RAG Tool
  sessions                — Multi-tenant Chat session metadata
  audit_log               — Multi-tenant Immutable record of every agent action
  agent_checkpoints       — Durable LangGraph state checkpoints
  agent_checkpoint_blobs  — Durable LangGraph channel value blobs
  agent_checkpoint_writes — Durable LangGraph pending channel writes
"""
import uuid
from sqlalchemy import (
    Column, String, Text, Boolean, DateTime, Integer, LargeBinary, func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import HALFVEC
from app.infrastructure.database.session import Base


class Tool(Base):
    """
    One row per tool/API action available to the agent.
    The `embedding` column enables semantic tool retrieval.
    """
    __tablename__ = "tools"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(128), nullable=False, unique=True)
    domain = Column(String(64), nullable=False, index=True)   # e.g. "payments"
    description = Column(Text, nullable=False)                 # embedded for search
    schema = Column(JSONB, nullable=False, default={})         # JSON Schema for params
    endpoint = Column(String(512), nullable=True)              # API url or function ref
    is_active = Column(Boolean, default=True, nullable=False)
    # pgvector HALFVEC(2560) for Qwen3-Embedding-4B (required for dims > 2000 in pgvector >= 0.7)
    embedding = Column(HALFVEC(2560), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class KBChunk(Base):
    """
    Knowledge base document chunks, used by the RAG Tool.
    Mirrors a simplified version of RAG-Entreprise's `chunks` table.
    """
    __tablename__ = "kb_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String(64), nullable=False, default="default", server_default="default", index=True)
    document_name = Column(String(256), nullable=False)
    section_title = Column(String(256), nullable=True)
    text = Column(Text, nullable=False)
    page = Column(Integer, default=1)
    embedding = Column(HALFVEC(2560), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    """Chat session — one row per unique user/session."""
    __tablename__ = "sessions"

    id = Column(String(64), primary_key=True)              # supplied by caller
    tenant_id = Column(String(64), nullable=False, default="default", server_default="default", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    metadata_ = Column("metadata", JSONB, default={})


class AuditLog(Base):
    """Immutable append-only record of every agent action."""
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String(64), nullable=False, default="default", server_default="default", index=True)
    session_id = Column(String(64), nullable=False, index=True)
    action = Column(String(128), nullable=False)   # e.g. "tool_called", "rag_query"
    domain = Column(String(64), nullable=True)
    tool_name = Column(String(128), nullable=True)
    payload = Column(JSONB, default={})
    result_summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AgentCheckpoint(Base):
    """Durable LangGraph checkpoint record (survives server restarts & multi-worker setups)."""
    __tablename__ = "agent_checkpoints"

    thread_id = Column(String(128), primary_key=True)
    checkpoint_ns = Column(String(128), primary_key=True, default="", server_default="")
    checkpoint_id = Column(String(128), primary_key=True)
    parent_checkpoint_id = Column(String(128), nullable=True)
    type = Column(String(64), nullable=False)
    checkpoint = Column(LargeBinary, nullable=False)
    metadata_type = Column(String(64), nullable=False)
    metadata_blob = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AgentCheckpointBlob(Base):
    """Durable LangGraph channel value blob storage."""
    __tablename__ = "agent_checkpoint_blobs"

    thread_id = Column(String(128), primary_key=True)
    checkpoint_ns = Column(String(128), primary_key=True, default="", server_default="")
    channel = Column(String(128), primary_key=True)
    version = Column(String(128), primary_key=True)
    type = Column(String(64), nullable=False)
    blob = Column(LargeBinary, nullable=True)


class AgentCheckpointWrite(Base):
    """Durable LangGraph pending writes storage (for interrupts & parallel branches)."""
    __tablename__ = "agent_checkpoint_writes"

    thread_id = Column(String(128), primary_key=True)
    checkpoint_ns = Column(String(128), primary_key=True, default="", server_default="")
    checkpoint_id = Column(String(128), primary_key=True)
    task_id = Column(String(128), primary_key=True)
    idx = Column(Integer, primary_key=True)
    channel = Column(String(128), nullable=False)
    type = Column(String(64), nullable=True)
    blob = Column(LargeBinary, nullable=False)
    task_path = Column(String(256), nullable=False, default="", server_default="")
