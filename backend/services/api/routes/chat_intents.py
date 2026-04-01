from __future__ import annotations

import re
from uuid import UUID

from db.models.chat_messages import ChatMessageRow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _normalize_text(message: str) -> str:
    text = (message or "").strip().lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    return " ".join(text.split())


def _is_generic_pipeline_trigger(message: str) -> bool:
    text = _normalize_text(message)
    if not text:
        return False

    generic_triggers = {
        "yes",
        "yeah",
        "yep",
        "sure",
        "ok",
        "okay",
        "do it",
        "go ahead",
        "proceed",
        "run it",
        "run it now",
        "run now",
        "run report",
        "run the report",
        "run the report now",
        "run research report",
        "run the research report",
        "run the research report now",
        "start report",
        "start the report",
        "start research",
        "start the research",
        "start the research report",
        "start the research report now",
        "create the research report now",
        "create the detailed research report now",
        "generate the research report now",
    }
    return text in generic_triggers


def _is_greeting(message: str) -> bool:
    text = _normalize_text(message)
    if not text:
        return False

    greetings = {
        "hi",
        "hello",
        "hey",
        "hi there",
        "hello there",
        "hey there",
        "yo",
        "sup",
        "good morning",
        "good afternoon",
        "good evening",
    }
    return text in greetings


def _greeting_response() -> str:
    return "Hi! How can I help you today?"


def _is_substantive_prompt_candidate(message: str) -> bool:
    text = _normalize_text(message)
    if not text or _is_greeting(text) or _is_generic_pipeline_trigger(text):
        return False

    dismissive_replies = {
        "thanks",
        "thank you",
        "sounds good",
        "looks good",
        "got it",
        "cool",
        "nice",
    }
    if text in dismissive_replies:
        return False

    return len(text.split()) >= 6


async def _latest_prior_research_prompt(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    conversation_id: UUID,
    exclude_message_id: UUID,
) -> str | None:
    stmt = (
        select(ChatMessageRow)
        .where(
            ChatMessageRow.tenant_id == tenant_id,
            ChatMessageRow.conversation_id == conversation_id,
            ChatMessageRow.role == "user",
            ChatMessageRow.type == "chat",
            ChatMessageRow.id != exclude_message_id,
        )
        .order_by(ChatMessageRow.created_at.desc(), ChatMessageRow.id.desc())
        .limit(12)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    for row in rows:
        candidate = (row.content_text or "").strip()
        if not _is_substantive_prompt_candidate(candidate):
            continue
        return candidate
    return None


async def _resolve_force_pipeline_prompt(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    conversation_id: UUID,
    user_message: ChatMessageRow,
) -> str:
    prompt = (user_message.content_text or "").strip()
    if not _is_generic_pipeline_trigger(prompt):
        return prompt

    prior_prompt = await _latest_prior_research_prompt(
        session=session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        exclude_message_id=user_message.id,
    )
    return prior_prompt or prompt


async def _recent_chat_history(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    conversation_id: UUID,
    limit: int = 6,
    exclude_message_id: UUID | None = None,
) -> list[ChatMessageRow]:
    stmt = (
        select(ChatMessageRow)
        .where(
            ChatMessageRow.tenant_id == tenant_id,
            ChatMessageRow.conversation_id == conversation_id,
            ChatMessageRow.type == "chat",
            ChatMessageRow.role.in_(["user", "assistant"]),
        )
        .order_by(ChatMessageRow.created_at.desc())
        .limit(limit)
    )
    if exclude_message_id is not None:
        stmt = stmt.where(ChatMessageRow.id != exclude_message_id)
    rows = list((await session.execute(stmt)).scalars().all())
    return list(reversed(rows))


def _build_prompt(history: list[ChatMessageRow], message: str) -> str:
    if not history:
        return message

    lines = ["Conversation so far:"]
    for row in history:
        prefix = "User" if row.role == "user" else "Assistant"
        lines.append(f"{prefix}: {row.content_text}")
    lines.append(f"User: {message}")
    lines.append("Assistant:")
    return "\n".join(lines)
