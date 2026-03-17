from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.snippets import SnippetRow


class SnippetFlagRow(Base):
    __tablename__ = "snippet_flags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "snippet_id", "flag_name", name="uq_snippet_flags_name"),
        Index("ix_snippet_flags_tenant_snippet", "tenant_id", "snippet_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    snippet_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    flag_name: Mapped[str] = mapped_column(String(100), nullable=False)
    flag_value: Mapped[str] = mapped_column(String(200), nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    snippet: Mapped[SnippetRow] = relationship("SnippetRow", back_populates="flags")


SnippetFlagRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "snippet_id"],
        ["snippets.tenant_id", "snippets.id"],
        ondelete="CASCADE",
        name="fk_snippet_flags_snippet",
    )
)
