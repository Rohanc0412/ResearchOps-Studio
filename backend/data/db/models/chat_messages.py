from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
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
    from db.models.chat_conversations import ChatConversationRow


class ChatMessageRow(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_chat_messages_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "client_message_id",
            name="uq_chat_messages_client_message_id",
        ),
        Index(
            "ix_chat_messages_tenant_conversation_created_at",
            "tenant_id",
            "conversation_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    conversation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    content_text: Mapped[str] = mapped_column(Text(), nullable=False)
    content_json: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    client_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    conversation: Mapped[ChatConversationRow] = relationship(
        "ChatConversationRow",
        back_populates="messages",
        primaryjoin="and_(ChatMessageRow.tenant_id==ChatConversationRow.tenant_id, "
        "ChatMessageRow.conversation_id==ChatConversationRow.id)",
        foreign_keys="[ChatMessageRow.tenant_id, ChatMessageRow.conversation_id]",
    )


ChatMessageRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "conversation_id"],
        ["chat_conversations.tenant_id", "chat_conversations.id"],
        ondelete="CASCADE",
        name="fk_chat_messages_tenant_conversation",
    )
)
