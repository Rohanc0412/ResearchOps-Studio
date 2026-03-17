from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.chat_conversations import ChatConversationRow


class ConversationActionRow(Base):
    __tablename__ = "conversation_actions"
    __table_args__ = (
        Index("ix_conversation_actions_tenant_conversation", "tenant_id", "conversation_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    conversation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    action_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    action_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text(), nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ambiguous_count: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    related_run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    reply_message_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    consent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    conversation: Mapped[ChatConversationRow] = relationship(
        "ChatConversationRow", back_populates="actions"
    )


ConversationActionRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "conversation_id"],
        ["chat_conversations.tenant_id", "chat_conversations.id"],
        ondelete="CASCADE",
        name="fk_conversation_actions_conversation",
    )
)
