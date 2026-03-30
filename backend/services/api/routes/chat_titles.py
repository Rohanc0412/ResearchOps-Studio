from __future__ import annotations

from uuid import UUID

from db.models.chat_messages import ChatMessageRow
from db.repositories.project_runs import get_latest_report_title
from llm import LLMError, get_llm_client
from routes.chat_intents import _recent_chat_history
from sqlalchemy import func, select


def _title_from_message(message: str) -> str:
    text = " ".join(message.split())
    return (text[:30] + ("..." if len(text) > 30 else "")).strip()


def _count_user_chat_messages(session, tenant_id: UUID, conversation_id: UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(ChatMessageRow)
        .where(
            ChatMessageRow.tenant_id == tenant_id,
            ChatMessageRow.conversation_id == conversation_id,
            ChatMessageRow.type == "chat",
            ChatMessageRow.role == "user",
        )
    )
    return session.execute(stmt).scalar_one() or 0


def _generate_title_with_llm(
    history: list[ChatMessageRow],
    report_title: str | None,
    llm_provider: str | None,
    llm_model: str | None,
) -> str | None:
    try:
        client = get_llm_client(llm_provider, llm_model)
    except LLMError:
        return None
    if client is None:
        return None

    lines = []
    if report_title:
        lines.append(f"Research topic: {report_title}")
    lines.append("Conversation:")
    for msg in history[-10:]:
        prefix = "User" if msg.role == "user" else "Assistant"
        text = (msg.content_text or "").strip()
        if text:
            lines.append(f"{prefix}: {text[:200]}")

    prompt = (
        "\n".join(lines)
        + "\n\nWrite a short title (5-8 words) for this conversation. "
        "Return only the title, no punctuation at the end."
    )
    try:
        title = client.generate(
            prompt,
            system="You generate concise conversation titles.",
            max_tokens=20,
            temperature=0.4,
        )
        title = title.strip().strip('"').strip("'")
        return title if title else None
    except LLMError:
        return None


def _maybe_update_title(
    *,
    session,
    tenant_id: UUID,
    convo,
    first_message: str,
    user_type: str,
    llm_provider: str | None,
    llm_model: str | None,
) -> None:
    if user_type != "chat":
        return

    count = _count_user_chat_messages(session, tenant_id, convo.id)

    if count < 4:
        if convo.title is None:
            report_title = (
                get_latest_report_title(
                    session=session, tenant_id=tenant_id, project_id=convo.project_id
                )
                if convo.project_id
                else None
            )
            convo.title = report_title or _title_from_message(first_message)
    elif count == 4:
        report_title = (
            get_latest_report_title(
                session=session, tenant_id=tenant_id, project_id=convo.project_id
            )
            if convo.project_id
            else None
        )
        history = _recent_chat_history(
            session=session, tenant_id=tenant_id, conversation_id=convo.id, limit=10
        )
        convo.title = _generate_title_with_llm(history, report_title, llm_provider, llm_model) or (
            convo.title or report_title or _title_from_message(first_message)
        )
