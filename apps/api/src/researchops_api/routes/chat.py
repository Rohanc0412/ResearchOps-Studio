from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from researchops_api.middlewares.auth import IdentityDep
from researchops_api.services.chat_router import classify_chat_intent, parse_consent_reply
from researchops_core.audit.logger import write_audit_log
from researchops_core.auth.identity import Identity
from researchops_core.auth.rbac import require_roles
from researchops_core.tenancy import tenant_uuid
from researchops_llm import LLMError, get_llm_client
from researchops_orchestrator import RESEARCH_JOB_TYPE, enqueue_run_job

from db.models.chat_messages import ChatMessageRow
from db.models.runs import RunStatusDb
from db.services.chat import (
    create_conversation,
    create_message,
    get_conversation,
    get_message_by_client_id,
    get_message_by_id,
    list_conversations,
    list_messages,
)
from db.services.truth import create_run, get_project
from db.session import session_scope

router = APIRouter(prefix="/chat", tags=["chat"])

logger = logging.getLogger(__name__)

ACTION_PREFIX = "__ACTION__:"
ACTION_RUN_PIPELINE = "run_pipeline"
ACTION_QUICK_ANSWER = "quick_answer"


def _tenant_uuid(identity: Identity) -> UUID:
    return tenant_uuid(identity.tenant_id)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _hash_action(prompt: str) -> str:
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return digest


def _encode_cursor(ts: datetime, row_id: UUID) -> str:
    return f"{ts.isoformat()}|{row_id}"


def _decode_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    if not cursor:
        return None
    try:
        ts_str, id_str = cursor.split("|", 1)
        return datetime.fromisoformat(ts_str), UUID(id_str)
    except Exception:
        return None


def _message_out(row: ChatMessageRow) -> "ChatMessageOut":
    return ChatMessageOut(
        id=row.id,
        role=row.role,
        type=row.type,
        content_text=row.content_text,
        content_json=row.content_json,
        created_at=row.created_at,
    )


def _action_label(action_id: str) -> str:
    if action_id == ACTION_RUN_PIPELINE:
        return "Run research report"
    if action_id == ACTION_QUICK_ANSWER:
        return "Quick answer"
    return action_id.replace("_", " ").title()


def _action_id_from_message(message: str) -> str | None:
    if not message.startswith(ACTION_PREFIX):
        return None
    action = message[len(ACTION_PREFIX) :].strip().lower()
    return action or None


def _title_from_message(message: str) -> str:
    text = " ".join(message.split())
    return (text[:30] + ("..." if len(text) > 30 else "")).strip()


def _pending_action_payload(
    *,
    prompt: str,
    llm_provider: str | None,
    llm_model: str | None,
    created_at: datetime,
    ambiguous_count: int = 0,
) -> dict:
    payload = {
        "type": "start_research_run",
        "prompt": prompt,
        "created_at": created_at.isoformat(),
        "ambiguous_count": ambiguous_count,
    }
    if llm_provider:
        payload["llm_provider"] = llm_provider
    if llm_model:
        payload["llm_model"] = llm_model
    return payload


def _extract_pending(conversation) -> dict | None:
    pending = conversation.pending_action_json
    return pending if isinstance(pending, dict) else None


def _recent_chat_history(
    *, session, tenant_id: UUID, conversation_id: UUID, limit: int = 6
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
    rows = list(session.execute(stmt).scalars().all())
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


def _generate_quick_answer(
    *,
    session,
    tenant_id: UUID,
    conversation_id: UUID,
    message: str,
    llm_provider: str | None,
    llm_model: str | None,
) -> str:
    try:
        client = get_llm_client(llm_provider, llm_model)
    except LLMError as exc:
        logger.warning("chat_llm_unavailable", extra={"error": str(exc)})
        return "I am not configured to generate a response right now."
    if client is None:
        return "I am not configured to generate a response right now."

    history = _recent_chat_history(
        session=session, tenant_id=tenant_id, conversation_id=conversation_id, limit=6
    )
    prompt = _build_prompt(history, message)
    system = "You are a helpful assistant. Provide a concise response without citations."
    try:
        return client.generate(prompt, system=system, max_tokens=512, temperature=0.4)
    except LLMError as exc:
        logger.warning("chat_llm_failed", extra={"error": str(exc)})
        return "I am having trouble generating a response right now."


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID | None = None
    title: str | None = Field(default=None, max_length=200)


class ConversationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    title: str | None = None
    created_at: datetime
    last_message_at: datetime | None = None


class ConversationListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ConversationOut]
    next_cursor: str | None = None


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    role: str
    type: str
    content_text: str
    content_json: dict | None = None
    created_at: datetime


class ChatMessageListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ChatMessageOut]
    next_cursor: str | None = None


class ChatSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    project_id: UUID | None = None
    message: str = Field(min_length=1)
    client_message_id: str = Field(min_length=1, max_length=200)
    llm_provider: str | None = Field(default=None, pattern="^(hosted)$")
    llm_model: str | None = Field(default=None, min_length=1)


class ChatSendResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    user_message: ChatMessageOut
    assistant_message: ChatMessageOut | None = None
    pending_action: dict | None = None
    idempotent_replay: bool = False


@router.post("/conversations", response_model=ConversationOut)
def post_conversation(
    request: Request, body: ConversationCreate, identity: Identity = IdentityDep
) -> ConversationOut:
    SessionLocal = request.app.state.SessionLocal
    tenant_id = _tenant_uuid(identity)

    with session_scope(SessionLocal) as session:
        if body.project_id is not None:
            if (
                get_project(session=session, tenant_id=tenant_id, project_id=body.project_id)
                is None
            ):
                raise HTTPException(status_code=404, detail="project not found")
        convo = create_conversation(
            session=session,
            tenant_id=tenant_id,
            project_id=body.project_id,
            created_by_user_id=identity.user_id,
            title=body.title,
        )
        return ConversationOut(
            conversation_id=convo.id,
            title=convo.title,
            created_at=convo.created_at,
            last_message_at=convo.last_message_at,
        )


@router.get("/conversations", response_model=ConversationListOut)
def get_conversations(
    request: Request,
    project_id: UUID | None = None,
    cursor: str | None = None,
    limit: int = 50,
    identity: Identity = IdentityDep,
) -> ConversationListOut:
    SessionLocal = request.app.state.SessionLocal
    tenant_id = _tenant_uuid(identity)
    limit = max(1, min(200, limit))
    decoded = _decode_cursor(cursor)

    with session_scope(SessionLocal) as session:
        rows = list_conversations(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            limit=limit + 1,
            cursor=decoded,
        )
        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            sort_ts = last.last_message_at or last.created_at
            next_cursor = _encode_cursor(sort_ts, last.id)
        return ConversationListOut(
            items=[
                ConversationOut(
                    conversation_id=row.id,
                    title=row.title,
                    created_at=row.created_at,
                    last_message_at=row.last_message_at,
                )
                for row in items
            ],
            next_cursor=next_cursor,
        )


@router.get("/conversations/{conversation_id}/messages", response_model=ChatMessageListOut)
def get_conversation_messages(
    request: Request,
    conversation_id: UUID,
    cursor: str | None = None,
    limit: int = 100,
    identity: Identity = IdentityDep,
) -> ChatMessageListOut:
    SessionLocal = request.app.state.SessionLocal
    tenant_id = _tenant_uuid(identity)
    limit = max(1, min(500, limit))
    decoded = _decode_cursor(cursor)

    with session_scope(SessionLocal) as session:
        convo = get_conversation(
            session=session, tenant_id=tenant_id, conversation_id=conversation_id
        )
        if convo is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        rows = list_messages(
            session=session,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            limit=limit + 1,
            cursor=decoded,
        )
        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = _encode_cursor(last.created_at, last.id)
        return ChatMessageListOut(
            items=[_message_out(row) for row in items],
            next_cursor=next_cursor,
        )


@router.post("/send", response_model=ChatSendResponse)
def post_send_chat(
    request: Request, body: ChatSendRequest, identity: Identity = IdentityDep
) -> ChatSendResponse:
    SessionLocal = request.app.state.SessionLocal
    tenant_id = _tenant_uuid(identity)
    now = _now_utc()

    with session_scope(SessionLocal) as session:
        convo = get_conversation(
            session=session, tenant_id=tenant_id, conversation_id=body.conversation_id, for_update=True
        )
        if convo is None:
            raise HTTPException(status_code=404, detail="conversation not found")

        if body.project_id is not None:
            if convo.project_id is None:
                convo.project_id = body.project_id
            elif convo.project_id != body.project_id:
                raise HTTPException(status_code=400, detail="conversation project mismatch")

        existing = get_message_by_client_id(
            session=session,
            tenant_id=tenant_id,
            conversation_id=body.conversation_id,
            client_message_id=body.client_message_id,
        )
        if existing is not None:
            reply_id = None
            if isinstance(existing.metadata_json, dict):
                reply_id = existing.metadata_json.get("reply_message_id")
            assistant = None
            if reply_id:
                try:
                    assistant = get_message_by_id(
                        session=session, tenant_id=tenant_id, message_id=UUID(reply_id)
                    )
                except Exception:
                    assistant = None
            return ChatSendResponse(
                conversation_id=convo.id,
                user_message=_message_out(existing),
                assistant_message=_message_out(assistant) if assistant else None,
                pending_action=_extract_pending(convo),
                idempotent_replay=True,
            )

        action_id = _action_id_from_message(body.message)
        user_type = "action" if action_id else "chat"
        user_content_json = (
            {"action_id": action_id, "label": _action_label(action_id)} if action_id else None
        )

        user_message = create_message(
            session=session,
            tenant_id=tenant_id,
            conversation_id=convo.id,
            role="user",
            message_type=user_type,
            content_text=body.message,
            content_json=user_content_json,
            client_message_id=body.client_message_id,
            metadata_json=None,
            created_at=now,
        )

        if convo.title is None and user_type == "chat":
            convo.title = _title_from_message(body.message)

        pending = _extract_pending(convo)
        assistant_message: ChatMessageRow | None = None
        pending_action = None
        llm_provider = body.llm_provider
        llm_model = body.llm_model

        if pending and pending.get("type") == "start_research_run":
            pending_prompt = str(pending.get("prompt") or "").strip()
            pending_provider = pending.get("llm_provider") or llm_provider
            pending_model = pending.get("llm_model") or llm_model
            if pending_provider not in (None, "hosted"):
                pending_provider = None
            llm_provider = pending_provider
            llm_model = pending_model
            decision = parse_consent_reply(body.message, pending_prompt)

            if decision == "yes":
                try:
                    require_roles("researcher", "admin", "owner")(identity)
                    if convo.project_id is None:
                        raise ValueError("project_id required for research run")
                    action_hash = _hash_action(f"{pending_prompt}|report")
                    last_action = convo.last_action_json if isinstance(convo.last_action_json, dict) else {}
                    last_started_at = last_action.get("started_at")
                    last_hash = last_action.get("action_hash")
                    last_run_id = last_action.get("run_id")
                    if last_hash == action_hash and last_run_id and last_started_at:
                        try:
                            last_ts = datetime.fromisoformat(str(last_started_at))
                            if now - last_ts <= timedelta(seconds=10):
                                assistant_message = create_message(
                                    session=session,
                                    tenant_id=tenant_id,
                                    conversation_id=convo.id,
                                    role="assistant",
                                    message_type="run_started",
                                    content_text="Research run already started.",
                                    content_json={"run_id": last_run_id, "action_hash": action_hash},
                                    client_message_id=None,
                                    metadata_json=None,
                                )
                                convo.pending_action_json = None
                                pending_action = None
                            else:
                                last_run_id = None
                        except Exception:
                            last_run_id = None
                    if assistant_message is None:
                        run = create_run(
                            session=session,
                            tenant_id=tenant_id,
                            project_id=convo.project_id,
                            status=RunStatusDb.queued,
                            budgets_json={},
                        )
                        run.usage_json = {
                            "job_type": RESEARCH_JOB_TYPE,
                            "user_query": pending_prompt,
                            "output_type": "report",
                            "research_goal": "report",
                            "llm_provider": llm_provider,
                            "llm_model": llm_model,
                        }
                        enqueue_run_job(
                            session=session,
                            tenant_id=tenant_id,
                            run_id=run.id,
                            job_type=RESEARCH_JOB_TYPE,
                        )
                        convo.last_action_json = {
                            "action_hash": action_hash,
                            "run_id": str(run.id),
                            "started_at": now.isoformat(),
                        }
                        convo.pending_action_json = None
                        pending_action = None
                        assistant_message = create_message(
                            session=session,
                            tenant_id=tenant_id,
                            conversation_id=convo.id,
                            role="assistant",
                            message_type="run_started",
                            content_text="Starting a research run now.",
                            content_json={"run_id": str(run.id), "action_hash": action_hash},
                            client_message_id=None,
                            metadata_json=None,
                        )
                        write_audit_log(
                            db=session,
                            identity=identity,
                            action="chat.pipeline_accept",
                            target_type="conversation",
                            target_id=str(convo.id),
                            metadata={"project_id": str(convo.project_id), "run_id": str(run.id)},
                            request=request,
                        )
                        write_audit_log(
                            db=session,
                            identity=identity,
                            action="run.consent_enqueue",
                            target_type="run",
                            target_id=str(run.id),
                            metadata={"conversation_id": str(convo.id)},
                            request=request,
                        )
                except PermissionError:
                    convo.pending_action_json = None
                    pending_action = None
                    assistant_message = create_message(
                        session=session,
                        tenant_id=tenant_id,
                        conversation_id=convo.id,
                        role="assistant",
                        message_type="error",
                        content_text=(
                            "You do not have permission to start the research pipeline. "
                            "Want a quick chat answer instead?"
                        ),
                        content_json=None,
                        client_message_id=None,
                        metadata_json=None,
                    )
                except ValueError as exc:
                    convo.pending_action_json = None
                    pending_action = None
                    assistant_message = create_message(
                        session=session,
                        tenant_id=tenant_id,
                        conversation_id=convo.id,
                        role="assistant",
                        message_type="error",
                        content_text=str(exc),
                        content_json=None,
                        client_message_id=None,
                        metadata_json=None,
                    )
                except Exception as exc:
                    logger.exception("run_start_failed", extra={"error": str(exc)})
                    pending_action = pending
                    assistant_message = create_message(
                        session=session,
                        tenant_id=tenant_id,
                        conversation_id=convo.id,
                        role="assistant",
                        message_type="error",
                        content_text=(
                            "I could not start the research run due to an internal error. "
                            "Want a quick chat answer instead?"
                        ),
                        content_json=None,
                        client_message_id=None,
                        metadata_json=None,
                    )

            elif decision == "no":
                convo.pending_action_json = None
                pending_action = None
                answer = _generate_quick_answer(
                    session=session,
                    tenant_id=tenant_id,
                    conversation_id=convo.id,
                    message=pending_prompt,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                )
                assistant_message = create_message(
                    session=session,
                    tenant_id=tenant_id,
                    conversation_id=convo.id,
                    role="assistant",
                    message_type="chat",
                    content_text=answer,
                    content_json=None,
                    client_message_id=None,
                    metadata_json={"consent": "declined"},
                )
                write_audit_log(
                    db=session,
                    identity=identity,
                    action="chat.pipeline_decline",
                    target_type="conversation",
                    target_id=str(convo.id),
                    metadata={"project_id": str(convo.project_id)},
                    request=request,
                )

            elif decision == "ambiguous":
                ambiguous_count = int(pending.get("ambiguous_count") or 0)
                if ambiguous_count >= 1:
                    convo.pending_action_json = None
                    pending_action = None
                    answer = _generate_quick_answer(
                        session=session,
                        tenant_id=tenant_id,
                        conversation_id=convo.id,
                        message=pending_prompt,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                    )
                    assistant_message = create_message(
                        session=session,
                        tenant_id=tenant_id,
                        conversation_id=convo.id,
                        role="assistant",
                        message_type="chat",
                        content_text=answer,
                        content_json=None,
                        client_message_id=None,
                        metadata_json={"consent": "default_quick_answer"},
                    )
                else:
                    pending_action = _pending_action_payload(
                        prompt=pending_prompt,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        created_at=now,
                        ambiguous_count=ambiguous_count + 1,
                    )
                    convo.pending_action_json = pending_action
                    assistant_message = create_message(
                        session=session,
                        tenant_id=tenant_id,
                        conversation_id=convo.id,
                        role="assistant",
                        message_type="chat",
                        content_text=(
                            "Do you want the full cited research report, or a quick chat answer?"
                        ),
                        content_json=None,
                        client_message_id=None,
                        metadata_json={"consent": "clarify"},
                    )

            elif decision == "new_topic":
                convo.pending_action_json = None
                pending_action = None
                pending = None

        if pending is None:
            if action_id == ACTION_RUN_PIPELINE:
                last_action = convo.last_action_json if isinstance(convo.last_action_json, dict) else {}
                last_started_at = last_action.get("started_at")
                last_run_id = last_action.get("run_id")
                if last_started_at and last_run_id:
                    try:
                        last_ts = datetime.fromisoformat(str(last_started_at))
                        if now - last_ts <= timedelta(seconds=10):
                            assistant_message = create_message(
                                session=session,
                                tenant_id=tenant_id,
                                conversation_id=convo.id,
                                role="assistant",
                                message_type="run_started",
                                content_text="Research run already started.",
                                content_json={"run_id": last_run_id},
                                client_message_id=None,
                                metadata_json={"idempotent_replay": True},
                            )
                    except Exception:
                        assistant_message = None
                if assistant_message is None:
                    assistant_message = create_message(
                        session=session,
                        tenant_id=tenant_id,
                        conversation_id=convo.id,
                        role="assistant",
                        message_type="chat",
                        content_text="There is no pending research offer. Ask a new question to begin.",
                        content_json=None,
                        client_message_id=None,
                        metadata_json=None,
                    )
            elif action_id == ACTION_QUICK_ANSWER:
                assistant_message = create_message(
                    session=session,
                    tenant_id=tenant_id,
                    conversation_id=convo.id,
                    role="assistant",
                    message_type="chat",
                    content_text="There is no pending research offer. Ask a new question to begin.",
                    content_json=None,
                    client_message_id=None,
                    metadata_json=None,
                )
            else:
                decision = classify_chat_intent(body.message)
                if decision.mode == "offer_pipeline" and decision.confidence >= 0.75:
                    pending_action = _pending_action_payload(
                        prompt=body.message,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        created_at=now,
                    )
                    convo.pending_action_json = pending_action
                    assistant_message = create_message(
                        session=session,
                        tenant_id=tenant_id,
                        conversation_id=convo.id,
                        role="assistant",
                        message_type="pipeline_offer",
                        content_text=(
                            "This looks like a research-style request. "
                            "Do you want me to run the research pipeline and generate a cited report?"
                        ),
                        content_json={
                            "offer": {
                                "prompt_preview": body.message[:160],
                                "actions": [
                                    {"id": ACTION_RUN_PIPELINE, "label": _action_label(ACTION_RUN_PIPELINE)},
                                    {"id": ACTION_QUICK_ANSWER, "label": _action_label(ACTION_QUICK_ANSWER)},
                                ],
                            }
                        },
                        client_message_id=None,
                        metadata_json={
                            "router": {
                                "mode": decision.mode,
                                "confidence": decision.confidence,
                                "reason": decision.reason,
                            }
                        },
                    )
                    write_audit_log(
                        db=session,
                        identity=identity,
                        action="chat.pipeline_offer",
                        target_type="conversation",
                        target_id=str(convo.id),
                        metadata={
                            "project_id": str(convo.project_id) if convo.project_id else None,
                            "confidence": decision.confidence,
                        },
                        request=request,
                    )
                else:
                    answer = _generate_quick_answer(
                        session=session,
                        tenant_id=tenant_id,
                        conversation_id=convo.id,
                        message=body.message,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                    )
                    assistant_message = create_message(
                        session=session,
                        tenant_id=tenant_id,
                        conversation_id=convo.id,
                        role="assistant",
                        message_type="chat",
                        content_text=answer,
                        content_json=None,
                        client_message_id=None,
                        metadata_json={
                            "router": {
                                "mode": decision.mode,
                                "confidence": decision.confidence,
                                "reason": decision.reason,
                            }
                        },
                    )

        if assistant_message is None:
            assistant_message = create_message(
                session=session,
                tenant_id=tenant_id,
                conversation_id=convo.id,
                role="assistant",
                message_type="error",
                content_text="I could not process that message. Please try again.",
                content_json=None,
                client_message_id=None,
                metadata_json=None,
            )

        convo.updated_at = now
        convo.last_message_at = assistant_message.created_at
        user_message.metadata_json = {"reply_message_id": str(assistant_message.id)}
        session.flush()

        return ChatSendResponse(
            conversation_id=convo.id,
            user_message=_message_out(user_message),
            assistant_message=_message_out(assistant_message),
            pending_action=_extract_pending(convo),
            idempotent_replay=False,
        )
