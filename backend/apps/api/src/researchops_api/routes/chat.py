from __future__ import annotations

import hashlib
import logging
import re
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
from researchops_core.runs.lifecycle import emit_run_event
from researchops_core.tenancy import tenant_uuid
from researchops_llm import LLMError, get_llm_client
from researchops_orchestrator import RESEARCH_JOB_TYPE, enqueue_run_job

from db.models.chat_messages import ChatMessageRow
from db.models.run_events import RunEventLevelDb
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


ACTION_PREFIX = "__ACTION__:"
ACTION_RUN_PIPELINE = "run_pipeline"
ACTION_QUICK_ANSWER = "quick_answer"

logger = logging.getLogger(__name__)


def _truncate_for_log(text: str, limit: int = 400) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit].rstrip()}..."


def _log_llm_exchange(label: str, conversation_id: UUID, content: str) -> None:
    if not content:
        return
    message = "LLM request prepared" if label == "request" else "LLM response received"
    logger.info(
        message,
        extra={
            "event": "chat.llm",
            "label": label,
            "conversation_id": str(conversation_id),
            "chars": len(content),
            "preview": _truncate_for_log(content),
        },
    )


def _log_step(state: str, *, conversation_id: UUID, step: str, extra: dict | None = None) -> None:
    payload = {"conversation_id": str(conversation_id), "step": step, "state": state}
    if extra:
        payload.update(extra)
    logger.info(
        f"Chat step {state}: {step.replace('_', ' ')}",
        extra={"event": "chat.step", **payload},
    )


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


def _normalize_text(message: str) -> str:
    text = (message or "").strip().lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    return " ".join(text.split())


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
    _log_step("start", conversation_id=conversation_id, step="quick_answer")
    response_text: str | None = None
    try:
        client = get_llm_client(llm_provider, llm_model)
    except LLMError as exc:
        response_text = "I am not configured to generate a response right now."
        _log_step(
            "finish",
            conversation_id=conversation_id,
            step="quick_answer",
            extra={"chars": len(response_text), "reason": "llm_unavailable"},
        )
        return response_text
    if client is None:
        response_text = "I am not configured to generate a response right now."
        _log_step(
            "finish",
            conversation_id=conversation_id,
            step="quick_answer",
            extra={"chars": len(response_text), "reason": "llm_missing"},
        )
        return response_text

    history = _recent_chat_history(
        session=session, tenant_id=tenant_id, conversation_id=conversation_id, limit=6
    )
    prompt = _build_prompt(history, message)
    system = "You are a helpful assistant. Provide a concise response without citations."
    try:
        _log_llm_exchange("request", conversation_id, prompt)
        response = client.generate(prompt, system=system, max_tokens=512, temperature=0.4)
        _log_llm_exchange("response", conversation_id, response)
        response_text = response
        return response
    except LLMError as exc:
        response_text = "I am having trouble generating a response right now."
        return response_text
    finally:
        if response_text is not None:
            _log_step(
                "finish",
                conversation_id=conversation_id,
                step="quick_answer",
                extra={"chars": len(response_text)},
            )


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
    force_pipeline: bool = False


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
        logger.info(
            "Conversation created",
            extra={
                "event": "chat.conversation.create",
                "conversation_id": str(convo.id),
                "project_id": str(convo.project_id) if convo.project_id else None,
                "title": convo.title,
            },
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
        logger.info(
            "Conversations listed",
            extra={
                "event": "chat.conversation.list",
                "project_id": str(project_id) if project_id else None,
                "count": len(items),
                "limit": limit,
                "has_more": has_more,
            },
        )
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
        logger.info(
            "Conversation messages listed",
            extra={
                "event": "chat.message.list",
                "conversation_id": str(conversation_id),
                "count": len(items),
                "limit": limit,
                "has_more": has_more,
            },
        )
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
    _log_step(
        "start",
        conversation_id=body.conversation_id,
        step="request",
        extra={
            "client_message_id": body.client_message_id,
            "message_len": len(body.message or ""),
            "force_pipeline": bool(body.force_pipeline),
        },
    )
    action_id = _action_id_from_message(body.message)
    logger.info(
        "Chat message received",
        extra={
            "event": "chat.message.receive",
            "conversation_id": str(body.conversation_id),
            "client_message_id": body.client_message_id,
            "message_len": len(body.message or ""),
            "message_preview": _truncate_for_log(body.message),
            "project_id": str(body.project_id) if body.project_id else None,
            "force_pipeline": bool(body.force_pipeline),
            "action_id": action_id,
        },
    )

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
            logger.info(
                "Chat message replayed from cache",
                extra={
                    "event": "chat.message.replay",
                    "conversation_id": str(convo.id),
                    "client_message_id": body.client_message_id,
                },
            )
            return ChatSendResponse(
                conversation_id=convo.id,
                user_message=_message_out(existing),
                assistant_message=_message_out(assistant) if assistant else None,
                pending_action=_extract_pending(convo),
                idempotent_replay=True,
            )

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
        logger.info(
            "User message stored",
            extra={
                "event": "chat.message.store",
                "conversation_id": str(convo.id),
                "message_id": str(user_message.id),
                "message_type": user_message.type,
            },
        )

        if convo.title is None and user_type == "chat":
            convo.title = _title_from_message(body.message)

        pending = _extract_pending(convo)
        assistant_message: ChatMessageRow | None = None
        pending_action = None
        llm_provider = body.llm_provider
        llm_model = body.llm_model
        decision_override = None
        if body.force_pipeline and action_id is None:
            _log_step("start", conversation_id=convo.id, step="force_pipeline")
            pending = _pending_action_payload(
                prompt=body.message,
                llm_provider=llm_provider,
                llm_model=llm_model,
                created_at=now,
            )
            convo.pending_action_json = pending
            decision_override = "yes"
            _log_step("finish", conversation_id=convo.id, step="force_pipeline")

        if pending and pending.get("type") == "start_research_run":
            _log_step("start", conversation_id=convo.id, step="consent_decision")
            pending_prompt = str(pending.get("prompt") or "").strip()
            pending_provider = pending.get("llm_provider") or llm_provider
            pending_model = pending.get("llm_model") or llm_model
            if pending_provider not in (None, "hosted"):
                pending_provider = None
            llm_provider = pending_provider
            llm_model = pending_model
            decision = decision_override or parse_consent_reply(body.message, pending_prompt)
            _log_step("finish", conversation_id=convo.id, step="consent_decision")

            if decision == "yes":
                _log_step("start", conversation_id=convo.id, step="start_research_run")
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
                            current_stage="retrieve",
                            question=pending_prompt,
                            output_type="report",
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
                        emit_run_event(
                            session=session,
                            tenant_id=tenant_id,
                            run_id=run.id,
                            event_type="run.created",
                            level=RunEventLevelDb.info,
                            message="Run created",
                            stage="retrieve",
                            payload={"run_id": str(run.id)},
                        )
                        emit_run_event(
                            session=session,
                            tenant_id=tenant_id,
                            run_id=run.id,
                            event_type="run.queued",
                            level=RunEventLevelDb.info,
                            message="Run queued",
                            stage="retrieve",
                            payload={"run_id": str(run.id)},
                        )
                        enqueue_run_job(
                            session=session,
                            tenant_id=tenant_id,
                            run_id=run.id,
                            job_type=RESEARCH_JOB_TYPE,
                        )
                        logger.info(
                            "Research run queued from chat",
                            extra={
                                "event": "chat.run.queue",
                                "conversation_id": str(convo.id),
                                "run_id": str(run.id),
                                "project_id": str(convo.project_id) if convo.project_id else None,
                            },
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
                _log_step("finish", conversation_id=convo.id, step="start_research_run")

            elif decision == "no":
                _log_step("start", conversation_id=convo.id, step="quick_answer_declined")
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
                _log_step("finish", conversation_id=convo.id, step="quick_answer_declined")

            elif decision == "ambiguous":
                _log_step("start", conversation_id=convo.id, step="consent_ambiguous")
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
                _log_step("finish", conversation_id=convo.id, step="consent_ambiguous")

            elif decision == "new_topic":
                _log_step("start", conversation_id=convo.id, step="consent_new_topic")
                convo.pending_action_json = None
                pending_action = None
                pending = None
                _log_step("finish", conversation_id=convo.id, step="consent_new_topic")

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
                if _is_greeting(body.message):
                    _log_step("start", conversation_id=convo.id, step="greeting")
                    assistant_message = create_message(
                        session=session,
                        tenant_id=tenant_id,
                        conversation_id=convo.id,
                        role="assistant",
                        message_type="chat",
                        content_text=_greeting_response(),
                        content_json=None,
                        client_message_id=None,
                        metadata_json={"fast_path": "greeting"},
                    )
                    _log_step("finish", conversation_id=convo.id, step="greeting")
                else:
                    decision = classify_chat_intent(body.message)
                    logger.info(
                        "Chat routing decision made",
                        extra={
                            "event": "chat.route.decision",
                            "conversation_id": str(convo.id),
                            "mode": decision.mode,
                            "confidence": decision.confidence,
                            "reason": decision.reason,
                        },
                    )
                    if decision.mode == "offer_pipeline" and decision.confidence >= 0.75:
                        _log_step("start", conversation_id=convo.id, step="offer_pipeline")
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
                        _log_step("finish", conversation_id=convo.id, step="offer_pipeline")
                    else:
                        _log_step("start", conversation_id=convo.id, step="quick_answer_default")
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
                        _log_step("finish", conversation_id=convo.id, step="quick_answer_default")

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

        _log_step(
            "finish",
            conversation_id=convo.id,
            step="request",
            extra={
                "assistant_message_id": str(assistant_message.id),
                "assistant_type": assistant_message.type,
            },
        )
        return ChatSendResponse(
            conversation_id=convo.id,
            user_message=_message_out(user_message),
            assistant_message=_message_out(assistant_message),
            pending_action=_extract_pending(convo),
            idempotent_replay=False,
        )
