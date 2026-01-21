from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from db.models.chat_conversations import ChatConversationRow
from db.models.chat_messages import ChatMessageRow


def _now_utc() -> datetime:
    return datetime.now(UTC)


def create_conversation(
    *,
    session: Session,
    tenant_id: UUID,
    project_id: UUID | None,
    created_by_user_id: str,
    title: str | None,
) -> ChatConversationRow:
    now = _now_utc()
    row = ChatConversationRow(
        tenant_id=tenant_id,
        project_id=project_id,
        created_by_user_id=created_by_user_id,
        title=title,
        pending_action_json=None,
        last_action_json=None,
        created_at=now,
        updated_at=now,
        last_message_at=None,
    )
    session.add(row)
    session.flush()
    return row


def get_conversation(
    *,
    session: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    for_update: bool = False,
) -> ChatConversationRow | None:
    stmt = select(ChatConversationRow).where(
        ChatConversationRow.tenant_id == tenant_id,
        ChatConversationRow.id == conversation_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return session.execute(stmt).scalar_one_or_none()


def list_conversations(
    *,
    session: Session,
    tenant_id: UUID,
    project_id: UUID | None,
    limit: int,
    cursor: tuple[datetime, UUID] | None,
) -> list[ChatConversationRow]:
    sort_ts = func.coalesce(ChatConversationRow.last_message_at, ChatConversationRow.created_at)
    stmt: Select[tuple[ChatConversationRow]] = select(ChatConversationRow).where(
        ChatConversationRow.tenant_id == tenant_id
    )
    if project_id is not None:
        stmt = stmt.where(ChatConversationRow.project_id == project_id)
    if cursor is not None:
        cursor_ts, cursor_id = cursor
        stmt = stmt.where(
            (sort_ts < cursor_ts)
            | ((sort_ts == cursor_ts) & (ChatConversationRow.id < cursor_id))
        )
    stmt = stmt.order_by(sort_ts.desc(), ChatConversationRow.id.desc()).limit(limit)
    return list(session.execute(stmt).scalars().all())


def list_messages(
    *,
    session: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    limit: int,
    cursor: tuple[datetime, UUID] | None,
) -> list[ChatMessageRow]:
    stmt: Select[tuple[ChatMessageRow]] = select(ChatMessageRow).where(
        ChatMessageRow.tenant_id == tenant_id,
        ChatMessageRow.conversation_id == conversation_id,
    )
    if cursor is not None:
        cursor_ts, cursor_id = cursor
        stmt = stmt.where(
            (ChatMessageRow.created_at > cursor_ts)
            | ((ChatMessageRow.created_at == cursor_ts) & (ChatMessageRow.id > cursor_id))
        )
    stmt = stmt.order_by(ChatMessageRow.created_at.asc(), ChatMessageRow.id.asc()).limit(limit)
    return list(session.execute(stmt).scalars().all())


def get_message_by_id(
    *,
    session: Session,
    tenant_id: UUID,
    message_id: UUID,
) -> ChatMessageRow | None:
    stmt = select(ChatMessageRow).where(
        ChatMessageRow.tenant_id == tenant_id, ChatMessageRow.id == message_id
    )
    return session.execute(stmt).scalar_one_or_none()


def get_message_by_client_id(
    *,
    session: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    client_message_id: str,
) -> ChatMessageRow | None:
    stmt = select(ChatMessageRow).where(
        ChatMessageRow.tenant_id == tenant_id,
        ChatMessageRow.conversation_id == conversation_id,
        ChatMessageRow.client_message_id == client_message_id,
    )
    return session.execute(stmt).scalar_one_or_none()


def create_message(
    *,
    session: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    role: str,
    message_type: str,
    content_text: str,
    content_json: dict | None,
    client_message_id: str | None,
    metadata_json: dict | None,
    created_at: datetime | None = None,
) -> ChatMessageRow:
    row = ChatMessageRow(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role=role,
        type=message_type,
        content_text=content_text,
        content_json=content_json,
        client_message_id=client_message_id,
        metadata_json=metadata_json,
        created_at=created_at or _now_utc(),
    )
    session.add(row)
    session.flush()
    return row
