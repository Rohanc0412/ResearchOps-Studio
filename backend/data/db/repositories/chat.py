from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models.chat_conversations import ChatConversationRow
from db.models.chat_messages import ChatMessageRow
from db.models.conversation_actions import ConversationActionRow


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _coerce_utc(value: datetime | None) -> datetime:
    if value is None:
        return _now_utc()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def create_conversation(
    *,
    session: AsyncSession,
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
        created_at=now,
        updated_at=now,
        last_message_at=None,
    )
    session.add(row)
    await session.flush()
    return row


async def get_conversation(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    conversation_id: UUID,
    for_update: bool = False,
) -> ChatConversationRow | None:
    stmt = (
        select(ChatConversationRow)
        .where(
            ChatConversationRow.tenant_id == tenant_id,
            ChatConversationRow.id == conversation_id,
        )
        .options(selectinload(ChatConversationRow.actions))
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_conversation_for_user(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    conversation_id: UUID,
    created_by_user_id: str,
    for_update: bool = False,
) -> ChatConversationRow | None:
    stmt = (
        select(ChatConversationRow)
        .where(
            ChatConversationRow.tenant_id == tenant_id,
            ChatConversationRow.id == conversation_id,
            ChatConversationRow.created_by_user_id == created_by_user_id,
        )
        .options(selectinload(ChatConversationRow.actions))
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_conversations(
    *,
    session: AsyncSession,
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
    return list((await session.execute(stmt)).scalars().all())


async def list_conversations_for_user(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    created_by_user_id: str,
    project_id: UUID | None,
    limit: int,
    cursor: tuple[datetime, UUID] | None,
) -> list[ChatConversationRow]:
    sort_ts = func.coalesce(ChatConversationRow.last_message_at, ChatConversationRow.created_at)
    stmt: Select[tuple[ChatConversationRow]] = select(ChatConversationRow).where(
        ChatConversationRow.tenant_id == tenant_id,
        ChatConversationRow.created_by_user_id == created_by_user_id,
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
    return list((await session.execute(stmt)).scalars().all())


async def list_messages(
    *,
    session: AsyncSession,
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
    stmt = stmt.order_by(ChatMessageRow.created_at.asc(), ChatMessageRow.role.desc(), ChatMessageRow.id.asc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def get_message_by_id(*, session: AsyncSession, tenant_id: UUID, message_id: UUID) -> ChatMessageRow | None:
    stmt = select(ChatMessageRow).where(
        ChatMessageRow.tenant_id == tenant_id, ChatMessageRow.id == message_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_message_by_client_id(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    conversation_id: UUID,
    client_message_id: str,
) -> ChatMessageRow | None:
    stmt = select(ChatMessageRow).where(
        ChatMessageRow.tenant_id == tenant_id,
        ChatMessageRow.conversation_id == conversation_id,
        ChatMessageRow.client_message_id == client_message_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_message(
    *,
    session: AsyncSession,
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
    await session.flush()
    return row


def get_pending_action(conversation: ChatConversationRow) -> dict | None:
    pending = [
        action
        for action in conversation.actions
        if action.action_kind == "pending" and action.resolved_at is None
    ]
    pending.sort(key=lambda row: row.created_at or datetime.min, reverse=True)
    action = pending[0] if pending else None
    if action is None:
        return None
    payload: dict[str, object] = {
        "type": action.action_type,
        "created_at": _coerce_utc(action.created_at).isoformat(),
    }
    if action.prompt:
        payload["prompt"] = action.prompt
    if action.llm_provider:
        payload["llm_provider"] = action.llm_provider
    if action.llm_model:
        payload["llm_model"] = action.llm_model
    if action.ambiguous_count is not None:
        payload["ambiguous_count"] = action.ambiguous_count
    return payload


def set_pending_action(conversation: ChatConversationRow, payload: dict | None) -> None:
    now = _now_utc()
    for action in conversation.actions:
        if action.action_kind == "pending" and action.resolved_at is None:
            action.resolved_at = now
    if not payload:
        return
    conversation.actions.append(
        ConversationActionRow(
            tenant_id=conversation.tenant_id,
            action_kind="pending",
            action_type=str(payload.get("type") or ""),
            prompt=str(payload.get("prompt") or "") or None,
            llm_provider=str(payload.get("llm_provider") or "") or None,
            llm_model=str(payload.get("llm_model") or "") or None,
            ambiguous_count=int(payload["ambiguous_count"]) if payload.get("ambiguous_count") is not None else None,
        )
    )


def clear_pending_action(conversation: ChatConversationRow) -> None:
    set_pending_action(conversation, None)


def get_last_action(conversation: ChatConversationRow) -> dict | None:
    rows = [action for action in conversation.actions if action.action_kind == "last"]
    rows.sort(key=lambda row: row.created_at or datetime.min, reverse=True)
    action = rows[0] if rows else None
    if action is None:
        return None
    payload: dict[str, object] = {
        "action_hash": action.action_type,
        "started_at": _coerce_utc(action.created_at).isoformat(),
        "completed_at": _coerce_utc(action.resolved_at).isoformat(),
    }
    if action.related_run_id:
        payload["run_id"] = str(action.related_run_id)
    if action.reply_message_id:
        payload["reply_message_id"] = str(action.reply_message_id)
    if action.consent:
        payload["consent"] = action.consent
    return payload


def record_last_action(
    conversation: ChatConversationRow,
    *,
    action_hash: str,
    run_id: UUID | None = None,
    reply_message_id: UUID | None = None,
    consent: str | None = None,
    started_at: datetime | None = None,
) -> None:
    conversation.actions.append(
        ConversationActionRow(
            tenant_id=conversation.tenant_id,
            action_kind="last",
            action_type=action_hash,
            related_run_id=run_id,
            reply_message_id=reply_message_id,
            consent=consent,
            created_at=_coerce_utc(started_at),
            resolved_at=_now_utc(),
        )
    )


__all__ = [
    "clear_pending_action",
    "create_conversation",
    "create_message",
    "get_conversation",
    "get_conversation_for_user",
    "get_last_action",
    "get_message_by_client_id",
    "get_message_by_id",
    "get_pending_action",
    "list_conversations",
    "list_conversations_for_user",
    "list_messages",
    "record_last_action",
    "set_pending_action",
]
