from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import AsyncGenerator as _AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app_services.chat_router import classify_chat_intent, parse_consent_reply
from app_services.project_runs import ACTIVE_RESEARCH_RUN_MESSAGE, create_research_run
from core.audit.logger import write_audit_log
from core.auth.identity import Identity
from core.auth.rbac import require_roles
from core.env import now_utc
from core.tenancy import get_tenant_id
from db.models.chat_messages import ChatMessageRow
from db.models.runs import RunStatusDb
from db.repositories.chat import (
    clear_pending_action,
    create_conversation,
    create_message,
    get_conversation_for_user,
    get_last_action,
    get_message_by_client_id,
    get_message_by_id,
    get_pending_action,
    list_conversations_for_user,
    list_messages,
    record_last_action,
    set_pending_action,
)
from db.repositories.project_runs import get_project_for_user
from db.session import session_scope
from deps import DBDep
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse as _StreamingResponse
from llm import LLMError, explain_llm_error, get_llm_client
from middlewares.auth import IdentityDep
from routes.chat_intents import (
    _build_prompt,
    _greeting_response,
    _is_greeting,
    _recent_chat_history,
    _resolve_force_pipeline_prompt,
)
from routes.chat_schemas import (
    ChatMessageListOut,
    ChatMessageOut,
    ChatSendRequest,
    ChatSendResponse,
    ConversationCreate,
    ConversationListOut,
    ConversationOut,
)
from routes.chat_titles import _maybe_update_title
from search.tavily import search

router = APIRouter(prefix="/chat", tags=["chat"])


WEB_SEARCH_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for current information. Use when the question requires "
            "up-to-date facts, recent events, or information beyond your training data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
            },
            "required": ["query"],
        },
    },
}


def _format_sse_event(event: str, data: dict) -> str:
    """Format a single SSE event string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@dataclass
class _QuickAnswerContext:
    session_local: object
    tenant_id: UUID
    conversation_id: UUID
    user_id: str
    user_message_id: UUID
    user_message_out: ChatMessageOut
    history: list
    message: str
    llm_provider: str | None
    llm_model: str | None
    metadata_json: dict | None


def _resolve_chat_model(llm_model: str | None) -> str | None:
    """Return CHAT_SEARCH_MODEL if set, else fall back to llm_model."""
    override = os.getenv("CHAT_SEARCH_MODEL", "").strip()
    return override or llm_model or None


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


def _message_out(row: ChatMessageRow) -> ChatMessageOut:
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


def _pending_action_payload(
    *,
    prompt: str,
    llm_provider: str | None,
    llm_model: str | None,
    created_at: datetime,
    ambiguous_count: int = 0,
    stage_models: dict[str, str | None] | None = None,
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
    if stage_models:
        payload["stage_models"] = stage_models
    return payload


def _extract_pending(conversation) -> dict | None:
    pending = get_pending_action(conversation)
    return pending if isinstance(pending, dict) else None


def _generate_quick_answer(
    *,
    history: list,
    tenant_id: UUID,
    conversation_id: UUID,
    message: str,
    llm_provider: str | None,
    llm_model: str | None,
):
    """Yield ("status", message) before web search and ("answer", text) at end."""
    _log_step("start", conversation_id=conversation_id, step="quick_answer")
    response_text: str | None = None

    resolved_model = _resolve_chat_model(llm_model)
    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
    use_tools = bool(tavily_key)

    try:
        client = get_llm_client(llm_provider, resolved_model)
    except LLMError as exc:
        response_text = explain_llm_error(str(exc))
        _log_step(
            "finish",
            conversation_id=conversation_id,
            step="quick_answer",
            extra={"chars": len(response_text)},
        )
        yield ("answer", response_text)
        return

    if client is None:
        response_text = "I am not configured to generate a response right now."
        _log_step(
            "finish",
            conversation_id=conversation_id,
            step="quick_answer",
            extra={"chars": len(response_text)},
        )
        yield ("answer", response_text)
        return

    prompt = _build_prompt(history, message)
    _log_llm_exchange("request", conversation_id, prompt)

    try:
        if use_tools:
            yield ("status", "Searching the web…")
            messages = [{"role": "user", "content": prompt}]
            first_message = client.generate_with_tools(
                messages, [WEB_SEARCH_TOOL], max_tokens=512, temperature=0.4
            )
            tool_calls = first_message.get("tool_calls") or []
            if tool_calls:
                tool_call = tool_calls[0]
                fn_args = tool_call.get("function", {})
                query = fn_args.get("arguments", {})
                if isinstance(query, str):
                    try:
                        query = json.loads(query)
                    except Exception:
                        query = {}
                query_text = query.get("query", message)
                try:
                    results = search(query_text, max_results=3)
                    snippets = [
                        f"[{i+1}] {r.get('title','')}: {r.get('content','')[:300]}"
                        for i, r in enumerate(results)
                    ]
                    tool_result = "\n\n".join(snippets) or "No results found."
                except Exception:
                    tool_result = "Web search unavailable."

                tool_call_id = tool_call.get("id", "call_0")
                messages.append(
                    {
                        "role": "assistant",
                        "content": first_message.get("content"),
                        "tool_calls": tool_calls,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": tool_result,
                    }
                )
                final_message = client.generate_with_tools(
                    messages, [WEB_SEARCH_TOOL], max_tokens=512, temperature=0.4
                )
                response_text = (final_message.get("content") or "").strip()
            else:
                response_text = (first_message.get("content") or "").strip()
        else:
            response_text = client.generate(
                prompt,
                system="You are a helpful research assistant. Answer concisely and helpfully.",
                max_tokens=512,
                temperature=0.4,
            ).strip()

        _log_llm_exchange("response", conversation_id, response_text or "")
        yield ("answer", response_text or "I am having trouble generating a response right now.")

    except LLMError as exc:
        response_text = explain_llm_error(str(exc))
        yield ("answer", response_text)
    finally:
        if response_text is not None:
            _log_step(
                "finish",
                conversation_id=conversation_id,
                step="quick_answer",
                extra={"chars": len(response_text)},
            )


async def _stream_quick_answer_body(
    ctx: _QuickAnswerContext,
) -> _AsyncGenerator[bytes, None]:
    """Async SSE generator: yields status event (if web search), then saves assistant
    message in a new DB session and yields the final answer event."""
    now = now_utc()
    answer: str = "I am having trouble generating a response right now."

    try:
        for event_type, event_data in _generate_quick_answer(
            history=ctx.history,
            tenant_id=ctx.tenant_id,
            conversation_id=ctx.conversation_id,
            message=ctx.message,
            llm_provider=ctx.llm_provider,
            llm_model=ctx.llm_model,
        ):
            if event_type == "status":
                yield _format_sse_event(
                    "status", {"type": "status", "message": event_data}
                ).encode()
            elif event_type == "answer":
                answer = event_data
    except Exception:
        logger.exception(
            "Error in quick answer stream",
            extra={"conversation_id": str(ctx.conversation_id)},
        )

    async with session_scope(ctx.session_local) as session:
        assistant_message = await create_message(
            session=session,
            tenant_id=ctx.tenant_id,
            conversation_id=ctx.conversation_id,
            role="assistant",
            message_type="chat",
            content_text=answer,
            content_json=None,
            client_message_id=None,
            metadata_json=ctx.metadata_json,
        )
        user_msg = await get_message_by_id(
            session=session,
            tenant_id=ctx.tenant_id,
            message_id=ctx.user_message_id,
        )
        if user_msg is not None:
            user_msg.metadata_json = {"reply_message_id": str(assistant_message.id)}

        convo = await get_conversation_for_user(
            session=session,
            tenant_id=ctx.tenant_id,
            conversation_id=ctx.conversation_id,
            created_by_user_id=ctx.user_id,
        )
        if convo is not None:
            convo.updated_at = now
            convo.last_message_at = assistant_message.created_at

        await session.flush()

        response_payload = ChatSendResponse(
            conversation_id=ctx.conversation_id,
            user_message=ctx.user_message_out,
            assistant_message=_message_out(assistant_message),
            pending_action=None,
            idempotent_replay=False,
        ).model_dump(mode="json")

    yield _format_sse_event("answer", response_payload).encode()


@router.post("/conversations", response_model=ConversationOut)
async def post_conversation(
    request: Request, body: ConversationCreate, session: DBDep, identity: Identity = IdentityDep
) -> ConversationOut:
    tenant_id = get_tenant_id(identity)

    if body.project_id is not None:
        if (
            await get_project_for_user(
                session=session,
                tenant_id=tenant_id,
                project_id=body.project_id,
                created_by=identity.user_id,
            )
            is None
        ):
            raise HTTPException(status_code=404, detail="project not found")
    convo = await create_conversation(
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
async def get_conversations(
    request: Request,
    session: DBDep,
    project_id: UUID | None = None,
    cursor: str | None = None,
    limit: int = 50,
    identity: Identity = IdentityDep,
) -> ConversationListOut:
    tenant_id = get_tenant_id(identity)
    limit = max(1, min(200, limit))
    decoded = _decode_cursor(cursor)

    if project_id is not None:
        project = await get_project_for_user(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            created_by=identity.user_id,
        )
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

    rows = await list_conversations_for_user(
        session=session,
        tenant_id=tenant_id,
        created_by_user_id=identity.user_id,
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
async def get_conversation_messages(
    request: Request,
    conversation_id: UUID,
    session: DBDep,
    cursor: str | None = None,
    limit: int = 100,
    identity: Identity = IdentityDep,
) -> ChatMessageListOut:
    tenant_id = get_tenant_id(identity)
    limit = max(1, min(500, limit))
    decoded = _decode_cursor(cursor)

    convo = await get_conversation_for_user(
        session=session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        created_by_user_id=identity.user_id,
    )
    if convo is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    rows = await list_messages(
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


@router.post("/send")
async def post_send_chat(
    request: Request, body: ChatSendRequest, session: DBDep, identity: Identity = IdentityDep
):
    SessionLocal = request.app.state.SessionLocal
    tenant_id = get_tenant_id(identity)
    qa_ctx: _QuickAnswerContext | None = None
    result: ChatSendResponse | None = None
    now = now_utc()
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

    convo = await get_conversation_for_user(
        session=session,
        tenant_id=tenant_id,
        conversation_id=body.conversation_id,
        created_by_user_id=identity.user_id,
        for_update=True,
    )
    if convo is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    if body.project_id is not None:
        project = await get_project_for_user(
            session=session,
            tenant_id=tenant_id,
            project_id=body.project_id,
            created_by=identity.user_id,
        )
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        if convo.project_id is None:
            convo.project_id = body.project_id
        elif convo.project_id != body.project_id:
            raise HTTPException(status_code=400, detail="conversation project mismatch")

    existing = await get_message_by_client_id(
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
                assistant = await get_message_by_id(
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

    user_message = await create_message(
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

    await _maybe_update_title(
        session=session,
        tenant_id=tenant_id,
        convo=convo,
        first_message=body.message,
        user_type=user_type,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
    )

    pending = _extract_pending(convo)
    assistant_message: ChatMessageRow | None = None
    pending_action = None
    llm_provider = body.llm_provider
    llm_model = body.llm_model
    decision_override = None
    if body.force_pipeline and action_id is None:
        _log_step("start", conversation_id=convo.id, step="force_pipeline")
        forced_prompt = await _resolve_force_pipeline_prompt(
            session=session,
            tenant_id=tenant_id,
            conversation_id=convo.id,
            user_message=user_message,
        )
        pending = _pending_action_payload(
            prompt=forced_prompt,
            llm_provider=llm_provider,
            llm_model=llm_model,
            created_at=now,
            stage_models=body.stage_models,
        )
        set_pending_action(convo, pending)
        decision_override = "yes"
        _log_step("finish", conversation_id=convo.id, step="force_pipeline")

    if pending and pending.get("type") == "start_research_run":
        _log_step("start", conversation_id=convo.id, step="consent_decision")
        pending_prompt = str(pending.get("prompt") or "").strip()
        pending_provider = pending.get("llm_provider") or llm_provider
        pending_model = pending.get("llm_model") or llm_model
        pending_stage_models = pending.get("stage_models") or body.stage_models
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
                last_action = get_last_action(convo) or {}
                last_started_at = last_action.get("started_at")
                last_hash = last_action.get("action_hash")
                last_run_id = last_action.get("run_id")
                if last_hash == action_hash and last_run_id and last_started_at:
                    try:
                        last_ts = datetime.fromisoformat(str(last_started_at))
                        if now - last_ts <= timedelta(seconds=10):
                            assistant_message = await create_message(
                                session=session,
                                tenant_id=tenant_id,
                                conversation_id=convo.id,
                                role="assistant",
                                message_type="run_started",
                                content_text="Research run already started.",
                                content_json={
                                    "run_id": last_run_id,
                                    "action_hash": action_hash,
                                    "question": pending_prompt,
                                },
                                client_message_id=None,
                                metadata_json=None,
                            )
                            clear_pending_action(convo)
                            pending_action = None
                        else:
                            last_run_id = None
                    except Exception:
                        last_run_id = None
                if assistant_message is None:
                    logger.info(
                        "Research pipeline request accepted from chat",
                        extra={
                            "event": "pipeline.request",
                            "conversation_id": str(convo.id),
                            "project_id": str(convo.project_id) if convo.project_id else None,
                            "prompt": pending_prompt,
                            "llm_provider": llm_provider,
                            "llm_model": llm_model,
                        },
                    )
                    run = await create_research_run(
                        session=session,
                        tenant_id=tenant_id,
                        project_id=convo.project_id,
                        question=pending_prompt,
                        client_request_id=None,
                        budgets={},
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        stage_models=json.dumps(pending_stage_models) if pending_stage_models else None,
                    )
                    logger.info(
                        "Research pipeline run created from chat",
                        extra={
                            "event": "pipeline.response",
                            "conversation_id": str(convo.id),
                            "project_id": str(convo.project_id) if convo.project_id else None,
                            "run_id": str(run.id),
                            "status": run.status.value,
                        },
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
                    record_last_action(
                        convo,
                        action_hash=action_hash,
                        run_id=run.id,
                        started_at=now,
                    )
                    clear_pending_action(convo)
                    pending_action = None
                    assistant_message = await create_message(
                        session=session,
                        tenant_id=tenant_id,
                        conversation_id=convo.id,
                        role="assistant",
                        message_type="run_started",
                        content_text=(
                            ACTIVE_RESEARCH_RUN_MESSAGE
                            if run.status == RunStatusDb.blocked
                            else "Starting a research run now."
                        ),
                        content_json={
                            "run_id": str(run.id),
                            "action_hash": action_hash,
                            "question": pending_prompt,
                            "status": run.status.value,
                        },
                        client_message_id=None,
                        metadata_json=None,
                    )
                    logger.info(
                        "Research pipeline chat response sent",
                        extra={
                            "event": "pipeline.response",
                            "conversation_id": str(convo.id),
                            "run_id": str(run.id),
                            "assistant_message": assistant_message.content_text,
                        },
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
                clear_pending_action(convo)
                pending_action = None
                assistant_message = await create_message(
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
                clear_pending_action(convo)
                pending_action = None
                assistant_message = await create_message(
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
            except Exception:
                pending_action = pending
                assistant_message = await create_message(
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
            clear_pending_action(convo)
            pending_action = None
            _qa_history = await _recent_chat_history(
                session=session,
                tenant_id=tenant_id,
                conversation_id=convo.id,
                limit=6,
                exclude_message_id=user_message.id,
            )
            qa_ctx = _QuickAnswerContext(
                session_local=SessionLocal,
                tenant_id=tenant_id,
                conversation_id=convo.id,
                user_id=identity.user_id,
                user_message_id=user_message.id,
                user_message_out=_message_out(user_message),
                history=_qa_history,
                message=pending_prompt,
                llm_provider=llm_provider,
                llm_model=llm_model,
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
                clear_pending_action(convo)
                pending_action = None
                _qa_history = await _recent_chat_history(
                    session=session,
                    tenant_id=tenant_id,
                    conversation_id=convo.id,
                    limit=6,
                    exclude_message_id=user_message.id,
                )
                qa_ctx = _QuickAnswerContext(
                    session_local=SessionLocal,
                    tenant_id=tenant_id,
                    conversation_id=convo.id,
                    user_id=identity.user_id,
                    user_message_id=user_message.id,
                    user_message_out=_message_out(user_message),
                    history=_qa_history,
                    message=pending_prompt,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                    metadata_json={"consent": "default_quick_answer"},
                )
            else:
                pending_action = _pending_action_payload(
                    prompt=pending_prompt,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                    created_at=now,
                    ambiguous_count=ambiguous_count + 1,
                    stage_models=body.stage_models,
                )
                set_pending_action(convo, pending_action)
                assistant_message = await create_message(
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
            clear_pending_action(convo)
            pending_action = None
            pending = None
            _log_step("finish", conversation_id=convo.id, step="consent_new_topic")

    if pending is None:
        if action_id == ACTION_RUN_PIPELINE:
            last_action = get_last_action(convo) or {}
            last_started_at = last_action.get("started_at")
            last_run_id = last_action.get("run_id")
            if last_started_at and last_run_id:
                try:
                    last_ts = datetime.fromisoformat(str(last_started_at))
                    if now - last_ts <= timedelta(seconds=10):
                        assistant_message = await create_message(
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
                assistant_message = await create_message(
                    session=session,
                    tenant_id=tenant_id,
                    conversation_id=convo.id,
                    role="assistant",
                    message_type="chat",
                    content_text=(
                        "There is no pending research offer. "
                        "Ask a new question to begin."
                    ),
                    content_json=None,
                    client_message_id=None,
                    metadata_json=None,
                )
        elif action_id == ACTION_QUICK_ANSWER:
            assistant_message = await create_message(
                session=session,
                tenant_id=tenant_id,
                conversation_id=convo.id,
                role="assistant",
                message_type="chat",
                content_text=(
                    "There is no pending research offer. "
                    "Ask a new question to begin."
                ),
                content_json=None,
                client_message_id=None,
                metadata_json=None,
            )
        else:
            if _is_greeting(body.message):
                _log_step("start", conversation_id=convo.id, step="greeting")
                assistant_message = await create_message(
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
                        stage_models=body.stage_models,
                    )
                    set_pending_action(convo, pending_action)
                    assistant_message = await create_message(
                        session=session,
                        tenant_id=tenant_id,
                        conversation_id=convo.id,
                        role="assistant",
                        message_type="pipeline_offer",
                        content_text=(
                            "This looks like a research-style request. "
                            "Do you want me to run the research pipeline "
                            "and generate a cited report?"
                        ),
                        content_json={
                            "offer": {
                                "prompt_preview": body.message[:160],
                                "actions": [
                                    {
                                        "id": ACTION_RUN_PIPELINE,
                                        "label": _action_label(ACTION_RUN_PIPELINE),
                                    },
                                    {
                                        "id": ACTION_QUICK_ANSWER,
                                        "label": _action_label(ACTION_QUICK_ANSWER),
                                    },
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
                    _qa_history = await _recent_chat_history(
                        session=session,
                        tenant_id=tenant_id,
                        conversation_id=convo.id,
                        limit=6,
                        exclude_message_id=user_message.id,
                    )
                    qa_ctx = _QuickAnswerContext(
                        session_local=SessionLocal,
                        tenant_id=tenant_id,
                        conversation_id=convo.id,
                        user_id=identity.user_id,
                        user_message_id=user_message.id,
                        user_message_out=_message_out(user_message),
                        history=_qa_history,
                        message=body.message,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        metadata_json={
                            "router": {
                                "mode": decision.mode,
                                "confidence": decision.confidence,
                                "reason": decision.reason,
                            }
                        },
                    )
                    _log_step("finish", conversation_id=convo.id, step="quick_answer_default")

    if qa_ctx is None:
        if assistant_message is None:
            assistant_message = await create_message(
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
        await session.flush()

        _log_step(
            "finish",
            conversation_id=convo.id,
            step="request",
            extra={
                "assistant_message_id": str(assistant_message.id),
                "assistant_type": assistant_message.type,
            },
        )
        result = ChatSendResponse(
            conversation_id=convo.id,
            user_message=_message_out(user_message),
            assistant_message=_message_out(assistant_message),
            pending_action=_extract_pending(convo),
            idempotent_replay=False,
        )

    if qa_ctx is not None:
        _log_step(
            "finish",
            conversation_id=qa_ctx.conversation_id,
            step="request",
            extra={"mode": "stream"},
        )
        # Commit the main session before starting the SSE stream so that the write
        # lock is released. The streaming generator opens its own session for the
        # assistant message, and SQLite requires the first writer to have committed
        # before a second writer can proceed.
        await session.commit()
        return _StreamingResponse(
            _stream_quick_answer_body(qa_ctx),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return result  # type: ignore[return-value]
