"""
001_initial_schema.py — Alembic migration: ProcureIQ initial database schema.
Run with: alembic upgrade head
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── tools table ───────────────────────────────────────────────────────────
    op.create_table(
        "tools",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("schema", JSONB, nullable=False, server_default="{}"),
        sa.Column("endpoint", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("embedding", sa.Text, nullable=True),  # stored as text, cast to vector
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tools_domain", "tools", ["domain"])
    # Qwen3-Embedding-4B = 2560 dimensions; halfvec used for >2000 dims (pgvector ≥0.7)
    # We store as halfvec to stay within pgvector's index limits.
    op.execute("ALTER TABLE tools ALTER COLUMN embedding TYPE halfvec(2560) USING embedding::halfvec(2560)")
    # Full-text search index (weighted over name, domain, and description)
    op.execute(
        "CREATE INDEX ix_tools_fts ON tools USING GIN "
        "(to_tsvector('english', name || ' ' || domain || ' ' || description))"
    )
    # HNSW vector index (halfvec cosine)
    op.execute(
        "CREATE INDEX ix_tools_embedding_hnsw ON tools USING hnsw (embedding halfvec_cosine_ops)"
    )

    # ── kb_chunks table ───────────────────────────────────────────────────────
    op.create_table(
        "kb_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("document_name", sa.String(256), nullable=False),
        sa.Column("section_title", sa.String(256), nullable=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("page", sa.Integer, server_default="1"),
        sa.Column("embedding", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute("ALTER TABLE kb_chunks ALTER COLUMN embedding TYPE halfvec(2560) USING embedding::halfvec(2560)")
    op.execute(
        "CREATE INDEX ix_kb_chunks_embedding_hnsw ON kb_chunks USING hnsw (embedding halfvec_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX ix_kb_chunks_fts ON kb_chunks USING GIN (to_tsvector('english', text))"
    )

    # ── sessions table ────────────────────────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column("metadata", JSONB, server_default="{}"),
    )

    # ── audit_log table ───────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("domain", sa.String(64), nullable=True),
        sa.Column("tool_name", sa.String(128), nullable=True),
        sa.Column("payload", JSONB, server_default="{}"),
        sa.Column("result_summary", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_log_session_id", "audit_log", ["session_id"])


def downgrade():
    op.drop_table("audit_log")
    op.drop_table("sessions")
    op.drop_table("kb_chunks")
    op.drop_table("tools")
