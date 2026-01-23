"""
Checkpoint storage for LangGraph using PostgreSQL.

Stores graph state snapshots for replay/resume functionality.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy import Column, DateTime, String, Text, create_engine
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

Base = declarative_base()


class CheckpointRow(Base):
    """Database model for checkpoints."""

    __tablename__ = "orchestrator_checkpoints"

    checkpoint_id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True)
    run_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True)
    thread_id = Column(String(255), nullable=False, index=True)
    checkpoint_ns = Column(String(255), nullable=False, default="")
    step = Column(String(255), nullable=False)
    state_data = Column(Text, nullable=False)  # JSON
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return f"<Checkpoint {self.checkpoint_id} run={self.run_id} step={self.step}>"


class PostgresCheckpointSaver(BaseCheckpointSaver):
    """
    Checkpoint saver using PostgreSQL.

    Stores graph state in database for replay/resume.
    """

    def __init__(self, session: Session, tenant_id: UUID, run_id: UUID):
        """
        Initialize checkpoint saver.

        Args:
            session: SQLAlchemy session
            tenant_id: Tenant ID
            run_id: Run ID
        """
        self.session = session
        self.tenant_id = tenant_id
        self.run_id = run_id

    def put(
        self,
        config: dict[str, Any],
        checkpoint: dict[str, Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Save a checkpoint.

        Args:
            config: Configuration (contains thread_id)
            checkpoint: State snapshot
            metadata: Additional metadata

        Returns:
            Saved configuration
        """
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")

        # Serialize state
        state_data = json.dumps(checkpoint)

        # Create checkpoint record
        checkpoint_record = CheckpointRow(
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            thread_id=thread_id,
            checkpoint_ns=checkpoint_ns,
            step=metadata.get("step", "unknown"),
            state_data=state_data,
        )

        self.session.add(checkpoint_record)
        self.session.flush()

        return config

    def get(
        self, config: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """
        Retrieve the latest checkpoint.

        Args:
            config: Configuration (contains thread_id)

        Returns:
            Tuple of (checkpoint, metadata) or (None, None)
        """
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")

        # Get latest checkpoint
        checkpoint_record = (
            self.session.query(CheckpointRow)
            .filter(
                CheckpointRow.tenant_id == self.tenant_id,
                CheckpointRow.run_id == self.run_id,
                CheckpointRow.thread_id == thread_id,
                CheckpointRow.checkpoint_ns == checkpoint_ns,
            )
            .order_by(CheckpointRow.created_at.desc())
            .first()
        )

        if not checkpoint_record:
            return (None, None)

        # Deserialize state
        checkpoint = json.loads(checkpoint_record.state_data)
        metadata = {
            "step": checkpoint_record.step,
            "created_at": checkpoint_record.created_at.isoformat(),
        }

        return (checkpoint, metadata)

    def list(
        self, config: dict[str, Any], limit: int = 10
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """
        List recent checkpoints.

        Args:
            config: Configuration (contains thread_id)
            limit: Maximum number to return

        Returns:
            List of (checkpoint, metadata) tuples
        """
        thread_id = config.get("configurable", {}).get("thread_id", "default")

        checkpoint_records = (
            self.session.query(CheckpointRow)
            .filter(
                CheckpointRow.tenant_id == self.tenant_id,
                CheckpointRow.run_id == self.run_id,
                CheckpointRow.thread_id == thread_id,
            )
            .order_by(CheckpointRow.created_at.desc())
            .limit(limit)
            .all()
        )

        results = []
        for record in checkpoint_records:
            checkpoint = json.loads(record.state_data)
            metadata = {
                "step": record.step,
                "created_at": record.created_at.isoformat(),
            }
            results.append((checkpoint, metadata))

        return results


def init_checkpoint_table(engine):
    """
    Initialize checkpoint table.

    Args:
        engine: SQLAlchemy engine
    """
    Base.metadata.create_all(engine, tables=[CheckpointRow.__table__])
