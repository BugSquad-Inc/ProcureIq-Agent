"""
postgres_checkpointer.py — Durable async PostgreSQL Checkpointer for LangGraph.

Implements `BaseCheckpointSaver` directly on top of SQLAlchemy AsyncSession + pg INSERT
ON CONFLICT semantics so multi-turn conversations and paused Human-in-the-Loop
(`interrupt()`) states survive FastAPI restarts, crashes, and multi-worker deployments
on both Windows (`asyncpg`) and Linux containers without `psycopg3` ProactorLoop issues.
"""
from __future__ import annotations

import random
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Tuple

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    SerializerProtocol,
    WRITES_IDX_MAP,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from sqlalchemy import delete, desc, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.infrastructure.database.models import (
    AgentCheckpoint,
    AgentCheckpointBlob,
    AgentCheckpointWrite,
)
from app.infrastructure.database.session import AsyncSessionLocal

logger = structlog.get_logger("procureiq.checkpointer")


class PostgresCheckpointSaver(BaseCheckpointSaver[str]):
    """Durable PostgreSQL-backed LangGraph checkpointer."""

    def __init__(
        self,
        session_factory=AsyncSessionLocal,
        serde: Optional[SerializerProtocol] = None,
    ) -> None:
        super().__init__(serde=serde)
        self.session_factory = session_factory

    def get_next_version(self, current: Optional[str], channel: None) -> str:
        """Generate monotonically sortable version string compatible with InMemorySaver."""
        if current is None:
            current_v = 0
        elif isinstance(current, int):
            current_v = current
        else:
            current_v = int(str(current).split(".")[0])
        next_v = current_v + 1
        return f"{next_v:032}.{random.random():016}"

    async def _load_blobs(
        self,
        session,
        thread_id: str,
        checkpoint_ns: str,
        versions: ChannelVersions,
    ) -> Dict[str, Any]:
        """Deserialize channel values referenced by `versions` from `agent_checkpoint_blobs`."""
        if not versions:
            return {}

        pairs = [(str(channel), str(version)) for channel, version in versions.items()]
        stmt = select(AgentCheckpointBlob).where(
            AgentCheckpointBlob.thread_id == thread_id,
            AgentCheckpointBlob.checkpoint_ns == checkpoint_ns,
            tuple_(AgentCheckpointBlob.channel, AgentCheckpointBlob.version).in_(pairs),
        )
        rows = (await session.execute(stmt)).scalars().all()
        values: Dict[str, Any] = {}
        for row in rows:
            if row.type != "empty" and row.blob is not None:
                values[row.channel] = self.serde.loads_typed((row.type, bytes(row.blob)))
        return values

    async def _row_to_tuple(self, session, row: AgentCheckpoint) -> CheckpointTuple:
        """Convert an `AgentCheckpoint` ORM row into a full `CheckpointTuple`."""
        checkpoint_: Checkpoint = self.serde.loads_typed((row.type, bytes(row.checkpoint)))
        metadata: CheckpointMetadata = self.serde.loads_typed(
            (row.metadata_type, bytes(row.metadata_blob))
        )
        channel_values = await self._load_blobs(
            session,
            row.thread_id,
            row.checkpoint_ns,
            checkpoint_.get("channel_versions", {}),
        )
        writes_stmt = (
            select(AgentCheckpointWrite)
            .where(
                AgentCheckpointWrite.thread_id == row.thread_id,
                AgentCheckpointWrite.checkpoint_ns == row.checkpoint_ns,
                AgentCheckpointWrite.checkpoint_id == row.checkpoint_id,
            )
            .order_by(AgentCheckpointWrite.task_id, AgentCheckpointWrite.idx)
        )
        write_rows = (await session.execute(writes_stmt)).scalars().all()
        pending_writes = [
            (
                w.task_id,
                w.channel,
                self.serde.loads_typed((w.type or "json", bytes(w.blob))),
            )
            for w in write_rows
        ]
        parent_config: Optional[RunnableConfig] = (
            {
                "configurable": {
                    "thread_id": row.thread_id,
                    "checkpoint_ns": row.checkpoint_ns,
                    "checkpoint_id": row.parent_checkpoint_id,
                }
            }
            if row.parent_checkpoint_id
            else None
        )
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": row.thread_id,
                    "checkpoint_ns": row.checkpoint_ns,
                    "checkpoint_id": row.checkpoint_id,
                }
            },
            checkpoint={
                **checkpoint_,
                "channel_values": channel_values,
            },
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes,
        )

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Fetch either the exact requested checkpoint or latest checkpoint for a thread."""
        thread_id = str(config["configurable"]["thread_id"])
        checkpoint_ns = str(config["configurable"].get("checkpoint_ns", ""))
        checkpoint_id = get_checkpoint_id(config)

        async with self.session_factory() as session:
            stmt = select(AgentCheckpoint).where(
                AgentCheckpoint.thread_id == thread_id,
                AgentCheckpoint.checkpoint_ns == checkpoint_ns,
            )
            if checkpoint_id:
                stmt = stmt.where(AgentCheckpoint.checkpoint_id == checkpoint_id)
            else:
                stmt = stmt.order_by(desc(AgentCheckpoint.checkpoint_id)).limit(1)

            row = (await session.execute(stmt)).scalars().first()
            if row is None:
                return None
            return await self._row_to_tuple(session, row)

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """Iterate checkpoints in descending chronological order matching criteria."""
        async with self.session_factory() as session:
            stmt = select(AgentCheckpoint)
            if config:
                stmt = stmt.where(
                    AgentCheckpoint.thread_id == str(config["configurable"]["thread_id"])
                )
                if "checkpoint_ns" in config["configurable"]:
                    stmt = stmt.where(
                        AgentCheckpoint.checkpoint_ns
                        == str(config["configurable"]["checkpoint_ns"])
                    )
                if cfg_id := get_checkpoint_id(config):
                    stmt = stmt.where(AgentCheckpoint.checkpoint_id == cfg_id)

            if before and (before_id := get_checkpoint_id(before)):
                stmt = stmt.where(AgentCheckpoint.checkpoint_id < before_id)

            stmt = stmt.order_by(desc(AgentCheckpoint.checkpoint_id))
            rows = (await session.execute(stmt)).scalars().all()

            yielded = 0
            for row in rows:
                if limit is not None and yielded >= limit:
                    break
                metadata: CheckpointMetadata = self.serde.loads_typed(
                    (row.metadata_type, bytes(row.metadata_blob))
                )
                if filter and not all(
                    query_value == metadata.get(query_key)
                    for query_key, query_value in filter.items()
                ):
                    continue
                yielded += 1
                yield await self._row_to_tuple(session, row)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Persist a checkpoint and any updated channel blobs transactionally to PostgreSQL."""
        c = checkpoint.copy()
        thread_id = str(config["configurable"]["thread_id"])
        checkpoint_ns = str(config["configurable"].get("checkpoint_ns", ""))
        values: Dict[str, Any] = c.pop("channel_values", {})  # type: ignore[misc]
        parent_id = config["configurable"].get("checkpoint_id")

        cp_type, cp_bytes = self.serde.dumps_typed(c)
        md_type, md_bytes = self.serde.dumps_typed(
            get_checkpoint_metadata(config, metadata)
        )

        async with self.session_factory() as session:
            for channel, version in new_versions.items():
                if channel in values:
                    b_type, b_bytes = self.serde.dumps_typed(values[channel])
                else:
                    b_type, b_bytes = "empty", b""
                blob_stmt = (
                    pg_insert(AgentCheckpointBlob)
                    .values(
                        thread_id=thread_id,
                        checkpoint_ns=checkpoint_ns,
                        channel=str(channel),
                        version=str(version),
                        type=b_type,
                        blob=b_bytes,
                    )
                    .on_conflict_do_update(
                        index_elements=[
                            AgentCheckpointBlob.thread_id,
                            AgentCheckpointBlob.checkpoint_ns,
                            AgentCheckpointBlob.channel,
                            AgentCheckpointBlob.version,
                        ],
                        set_={"type": b_type, "blob": b_bytes},
                    )
                )
                await session.execute(blob_stmt)

            cp_stmt = (
                pg_insert(AgentCheckpoint)
                .values(
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=str(checkpoint["id"]),
                    parent_checkpoint_id=str(parent_id) if parent_id else None,
                    type=cp_type,
                    checkpoint=cp_bytes,
                    metadata_type=md_type,
                    metadata_blob=md_bytes,
                )
                .on_conflict_do_update(
                    index_elements=[
                        AgentCheckpoint.thread_id,
                        AgentCheckpoint.checkpoint_ns,
                        AgentCheckpoint.checkpoint_id,
                    ],
                    set_={
                        "parent_checkpoint_id": str(parent_id) if parent_id else None,
                        "type": cp_type,
                        "checkpoint": cp_bytes,
                        "metadata_type": md_type,
                        "metadata_blob": md_bytes,
                    },
                )
            )
            await session.execute(cp_stmt)
            await session.commit()

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Persist pending channel writes (e.g. interrupts or parallel node writes)."""
        thread_id = str(config["configurable"]["thread_id"])
        checkpoint_ns = str(config["configurable"].get("checkpoint_ns", ""))
        checkpoint_id = str(config["configurable"]["checkpoint_id"])

        async with self.session_factory() as session:
            for idx, (channel, value) in enumerate(writes):
                mapped_idx = WRITES_IDX_MAP.get(channel, idx)
                w_type, w_bytes = self.serde.dumps_typed(value)
                stmt = pg_insert(AgentCheckpointWrite).values(
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=checkpoint_id,
                    task_id=str(task_id),
                    idx=int(mapped_idx),
                    channel=str(channel),
                    type=w_type,
                    blob=w_bytes,
                    task_path=str(task_path or ""),
                )
                conflict_cols = [
                    AgentCheckpointWrite.thread_id,
                    AgentCheckpointWrite.checkpoint_ns,
                    AgentCheckpointWrite.checkpoint_id,
                    AgentCheckpointWrite.task_id,
                    AgentCheckpointWrite.idx,
                ]
                if mapped_idx >= 0:
                    stmt = stmt.on_conflict_do_nothing(index_elements=conflict_cols)
                else:
                    stmt = stmt.on_conflict_do_update(
                        index_elements=conflict_cols,
                        set_={
                            "channel": str(channel),
                            "type": w_type,
                            "blob": w_bytes,
                            "task_path": str(task_path or ""),
                        },
                    )
                await session.execute(stmt)
            await session.commit()

    async def adelete_thread(self, thread_id: str) -> None:
        """Delete all stored checkpoints, blobs, and pending writes for a thread ID."""
        tid = str(thread_id)
        async with self.session_factory() as session:
            await session.execute(
                delete(AgentCheckpointWrite).where(AgentCheckpointWrite.thread_id == tid)
            )
            await session.execute(
                delete(AgentCheckpointBlob).where(AgentCheckpointBlob.thread_id == tid)
            )
            await session.execute(
                delete(AgentCheckpoint).where(AgentCheckpoint.thread_id == tid)
            )
            await session.commit()

