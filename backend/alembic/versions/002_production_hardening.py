"""
002_production_hardening.py — Alembic migration: multi-tenancy + durable LangGraph checkpointer tables.

Adds:
  - tenant_id column & indexes on kb_chunks, sessions, audit_log (default='default')
  - agent_checkpoints, agent_checkpoint_blobs, agent_checkpoint_writes tables
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    # ── Multi-tenant columns & indexes (idempotent for existing deployments) ───
    op.execute(
        "ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS "
        "tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_kb_chunks_tenant_id ON kb_chunks (tenant_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kb_chunks_tenant_doc ON kb_chunks (tenant_id, document_name)"
    )

    op.execute(
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS "
        "tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_sessions_tenant_id ON sessions (tenant_id)")

    op.execute(
        "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS "
        "tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_tenant_id ON audit_log (tenant_id)")

    # ── Durable LangGraph checkpointer tables ─────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_checkpoints (
            thread_id VARCHAR(128) NOT NULL,
            checkpoint_ns VARCHAR(128) NOT NULL DEFAULT '',
            checkpoint_id VARCHAR(128) NOT NULL,
            parent_checkpoint_id VARCHAR(128),
            type VARCHAR(64) NOT NULL,
            checkpoint BYTEA NOT NULL,
            metadata_type VARCHAR(64) NOT NULL,
            metadata_blob BYTEA NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_checkpoint_blobs (
            thread_id VARCHAR(128) NOT NULL,
            checkpoint_ns VARCHAR(128) NOT NULL DEFAULT '',
            channel VARCHAR(128) NOT NULL,
            version VARCHAR(128) NOT NULL,
            type VARCHAR(64) NOT NULL,
            blob BYTEA,
            PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_checkpoint_writes (
            thread_id VARCHAR(128) NOT NULL,
            checkpoint_ns VARCHAR(128) NOT NULL DEFAULT '',
            checkpoint_id VARCHAR(128) NOT NULL,
            task_id VARCHAR(128) NOT NULL,
            idx INTEGER NOT NULL,
            channel VARCHAR(128) NOT NULL,
            type VARCHAR(64),
            blob BYTEA NOT NULL,
            task_path VARCHAR(256) NOT NULL DEFAULT '',
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
        )
        """
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS agent_checkpoint_writes")
    op.execute("DROP TABLE IF EXISTS agent_checkpoint_blobs")
    op.execute("DROP TABLE IF EXISTS agent_checkpoints")
    op.execute("DROP INDEX IF EXISTS ix_audit_log_tenant_id")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS tenant_id")
    op.execute("DROP INDEX IF EXISTS ix_sessions_tenant_id")
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS tenant_id")
    op.execute("DROP INDEX IF EXISTS ix_kb_chunks_tenant_doc")
    op.execute("DROP INDEX IF EXISTS ix_kb_chunks_tenant_id")
    op.execute("ALTER TABLE kb_chunks DROP COLUMN IF EXISTS tenant_id")

