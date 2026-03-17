from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.sources import SourceRow


class SourceAuthorRow(Base):
    __tablename__ = "source_authors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_id", "author_order", name="uq_source_authors_order"),
        Index("ix_source_authors_tenant_source", "tenant_id", "source_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    author_order: Mapped[int] = mapped_column(Integer(), nullable=False)
    author_name: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source: Mapped[SourceRow] = relationship("SourceRow", back_populates="authors")


SourceAuthorRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "source_id"],
        ["sources.tenant_id", "sources.id"],
        ondelete="CASCADE",
        name="fk_source_authors_source",
    )
)
