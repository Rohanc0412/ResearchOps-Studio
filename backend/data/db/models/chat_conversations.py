from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.chat_messages import ChatMessageRow
    from db.models.conversation_actions import ConversationActionRow


class ChatConversationRow(Base):
    __tablename__ = "chat_conversations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_chat_conversations_tenant_id_id"),
        Index("ix_chat_conversations_tenant_project_id", "tenant_id", "project_id"),
        Index("ix_chat_conversations_tenant_created_by", "tenant_id", "created_by_user_id"),
        Index("ix_chat_conversations_tenant_last_message_at", "tenant_id", "last_message_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    project_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    created_by_user_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    messages: Mapped[list[ChatMessageRow]] = relationship(
        "ChatMessageRow", back_populates="conversation", cascade="all, delete-orphan"
    )
    actions: Mapped[list[ConversationActionRow]] = relationship(
        "ConversationActionRow", back_populates="conversation", cascade="all, delete-orphan"
    )

    @staticmethod
    def _coerce_utc(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _latest_action(self, kind: str):
        matches = [action for action in self.actions if action.action_kind == kind]
        matches.sort(key=lambda row: row.created_at or datetime.min, reverse=True)
        return matches[0] if matches else None

    @property
    def pending_action_json(self) -> dict | None:
        action = self._latest_action("pending")
        if action is None or action.resolved_at is not None:
            return None
        payload: dict[str, object] = {}
        if action.action_type:
            payload["type"] = action.action_type
        if action.prompt:
            payload["prompt"] = action.prompt
        if action.llm_provider:
            payload["llm_provider"] = action.llm_provider
        if action.llm_model:
            payload["llm_model"] = action.llm_model
        if action.ambiguous_count is not None:
            payload["ambiguous_count"] = action.ambiguous_count
        payload["created_at"] = self._coerce_utc(action.created_at).isoformat()
        return payload

    @pending_action_json.setter
    def pending_action_json(self, value: dict | None) -> None:
        from db.models.conversation_actions import ConversationActionRow

        for action in self.actions:
            if action.action_kind == "pending" and action.resolved_at is None:
                action.resolved_at = datetime.now(UTC)
        if not value:
            return
        self.actions.append(
            ConversationActionRow(
                tenant_id=self.tenant_id,
                action_kind="pending",
                action_type=str(value.get("type") or ""),
                prompt=str(value.get("prompt") or "") or None,
                llm_provider=str(value.get("llm_provider") or "") or None,
                llm_model=str(value.get("llm_model") or "") or None,
                ambiguous_count=int(value["ambiguous_count"]) if value.get("ambiguous_count") is not None else None,
            )
        )

    @property
    def last_action_json(self) -> dict | None:
        action = self._latest_action("last")
        if action is None:
            return None
        payload: dict[str, object] = {}
        if action.action_type:
            payload["id"] = action.action_type
            payload["action_hash"] = action.action_type
        if action.related_run_id:
            payload["run_id"] = str(action.related_run_id)
        if action.reply_message_id:
            payload["reply_message_id"] = str(action.reply_message_id)
        if action.consent:
            payload["consent"] = action.consent
        action_ts = self._coerce_utc(action.created_at or action.resolved_at)
        payload["started_at"] = action_ts.isoformat()
        payload["completed_at"] = self._coerce_utc(action.resolved_at or action_ts).isoformat()
        return payload

    @last_action_json.setter
    def last_action_json(self, value: dict | None) -> None:
        from db.models.conversation_actions import ConversationActionRow

        if not value:
            return
        run_id = value.get("run_id")
        reply_message_id = value.get("reply_message_id")
        started_at = value.get("started_at")
        created_at = None
        if started_at:
            try:
                created_at = datetime.fromisoformat(str(started_at))
            except ValueError:
                created_at = None
        action_type = value.get("id") or value.get("action_hash")
        self.actions.append(
            ConversationActionRow(
                tenant_id=self.tenant_id,
                action_kind="last",
                action_type=str(action_type or ""),
                related_run_id=UUID(str(run_id)) if run_id else None,
                reply_message_id=UUID(str(reply_message_id)) if reply_message_id else None,
                consent=str(value.get("consent") or "") or None,
                created_at=created_at or datetime.now(UTC),
                resolved_at=datetime.now(UTC),
            )
        )
