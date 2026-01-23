from __future__ import annotations

import enum
from typing import TYPE_CHECKING
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import JSON

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.runs import RunRow


class RunEventLevelDb(str, enum.Enum):
    debug = "debug"
    info = "info"
    warn = "warn"
    error = "error"


class RunEventRow(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_run_events_tenant_id_id"),
        Index("ix_run_events_tenant_run_ts", "tenant_id", "run_id", "ts"),
        Index("ix_run_events_tenant_run_event_number", "tenant_id", "run_id", "event_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    event_number: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    stage: Mapped[str | None] = mapped_column(String(200), nullable=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, server_default="log")
    level: Mapped[RunEventLevelDb] = mapped_column(
        Enum(RunEventLevelDb, name="run_event_level"), nullable=False
    )
    message: Mapped[str] = mapped_column(Text(), nullable=False)
    payload_json: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict, server_default="{}"
    )

    run: Mapped[RunRow] = relationship("RunRow", back_populates="events")


RunEventRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "run_id"],
        ["runs.tenant_id", "runs.id"],
        ondelete="CASCADE",
        name="fk_run_events_tenant_run",
    )
)
