"""Run management endpoints with production-grade lifecycle and SSE streaming."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime
from uuid import UUID

from app_services.evaluation_runner import EvaluationRunner
from app_services.project_runs import (
    cancel_user_run,
    get_user_run_or_404,
    list_user_run_artifacts,
    list_user_run_snippets,
    retry_user_run,
    run_to_web,
)
from core.auth.identity import Identity
from core.auth.rbac import require_roles
from core.evaluation import METRIC_EVAL_GROUNDING_PCT, METRIC_EVAL_STATUS
from core.tenancy import get_tenant_id
from db.models.run_sections import RunSectionRow
from db.models.runs import RunStatusDb
from db.models.section_reviews import SectionReviewRow
from db.repositories.evaluation_history import list_evaluation_pass_history
from db.repositories.project_runs import get_run_usage_metrics, list_run_events
from db.session import session_scope
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from middlewares.auth import IdentityDep
from pydantic import BaseModel, ConfigDict, Field
from schemas.truth import ArtifactOut, RunEventOut

router = APIRouter(prefix="/runs", tags=["runs"])


class OkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True


class WebRunOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: UUID
    status: str
    question: str | None = None
    current_stage: str | None = None
    project_id: UUID | None = None
    tenant_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    retry_count: int = 0
    error_message: str | None = None
    error_code: str | None = None
    budgets: dict = Field(default_factory=dict)
    usage: dict = Field(default_factory=dict)

_ALLOWED_STAGES = {
    "retrieve", "ingest", "outline", "evidence_pack", "draft",
    "evaluate", "validate", "repair", "factcheck", "export",
}


def _event_to_sse(event) -> str:
    """Convert RunEventRow to SSE format.

    SSE format:
    id: <event_number>
    event: run_event
    data: {...}

    """
    level = event.level.value
    if level == "debug":
        level = "info"
    if level not in {"info", "warn", "error"}:
        level = "info"

    stage = (event.stage or "retrieve").strip().lower() if event.stage else None
    if stage and stage not in _ALLOWED_STAGES:
        stage = "retrieve"

    payload = event.payload_json or {}
    data = {
        "id": event.event_number,
        "ts": event.ts.isoformat(),
        "level": level,
        "stage": stage,
        "event_type": event.event_type,
        "message": event.message,
        "payload": payload,
    }

    # SSE format requires:
    # id: <event_number>
    # event: <event_type>
    # data: <json>
    # <blank line>
    body = json.dumps(data, separators=(",", ":"))
    return f"id: {event.event_number}\nevent: run_event\ndata: {body}\n\n"


@router.get("/{run_id}")
def get_run_by_id(request: Request, run_id: UUID, identity: Identity = IdentityDep) -> WebRunOut:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        run = get_user_run_or_404(
            session=session,
            tenant_id=get_tenant_id(identity),
            run_id=run_id,
            user_id=identity.user_id,
        )
        return WebRunOut.model_validate(run_to_web(run))


@router.get("/{run_id}/events")
def get_run_events(
    request: Request,
    run_id: UUID,
    identity: Identity = IdentityDep,
    after_id: int | None = None,
):
    """Get run events as JSON list or SSE stream.

    Query parameters:
        after_id: Only return events with event_number > this value (for SSE reconnect)

    Headers:
        Accept: text/event-stream - Enable SSE streaming mode
        Last-Event-ID: <event_number> - Resume from this event (SSE reconnect)

    SSE event format:
        id: <event_number>
        event: run_event
        data: {"id": <event_number>, "ts": "...", "level": "...", ...}

    """
    accept = request.headers.get("accept", "")
    SessionLocal = request.app.state.SessionLocal
    tenant_id = get_tenant_id(identity)

    # Handle Last-Event-ID header for SSE reconnect
    last_event_id_header = request.headers.get("last-event-id")
    if last_event_id_header:
        try:
            after_id = int(last_event_id_header)
        except ValueError:
            pass  # Ignore invalid Last-Event-ID

    if "text/event-stream" in accept:
        # SSE streaming mode
        async def _gen():
            last_event_number = after_id or 0
            poll_interval = 0.5  # 500ms polling
            terminal_states = {RunStatusDb.succeeded, RunStatusDb.failed, RunStatusDb.canceled}
            grace_polls_after_terminal = 2  # Poll 2 more times after terminal state
            polls_since_terminal = 0
            keepalive_every = 10  # send keepalive every ~5s during idle
            keepalive_counter = 0

            while True:
                with session_scope(SessionLocal) as session:
                    try:
                        run = get_user_run_or_404(
                            session=session,
                            tenant_id=tenant_id,
                            run_id=run_id,
                            user_id=identity.user_id,
                        )
                    except HTTPException:
                        yield ": run not found\n\n"
                        break

                    # Get new events
                    events = list_run_events(
                        session=session,
                        tenant_id=tenant_id,
                        run_id=run_id,
                        after_event_number=last_event_number,
                        limit=200,
                    )

                    # Stream new events
                    for event in events:
                        yield _event_to_sse(event)
                        last_event_number = event.event_number

                    if run and run.status in terminal_states:
                        if len(events) == 0:
                            polls_since_terminal += 1
                            if polls_since_terminal >= grace_polls_after_terminal:
                                # Send final keepalive comment and close stream
                                yield ": stream complete\n\n"
                                break
                        else:
                            # Reset counter if we got new events
                            polls_since_terminal = 0
                        keepalive_counter = 0
                    else:
                        polls_since_terminal = 0
                        if len(events) == 0:
                            keepalive_counter += 1
                            if keepalive_counter >= keepalive_every:
                                yield ": keepalive\n\n"
                                keepalive_counter = 0
                        else:
                            keepalive_counter = 0

                # Wait before next poll
                await asyncio.sleep(poll_interval)

        return StreamingResponse(_gen(), media_type="text/event-stream")

    # JSON mode: return all events (or events after after_id)
    with session_scope(SessionLocal) as session:
        get_user_run_or_404(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
            user_id=identity.user_id,
        )
        rows = list_run_events(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
            after_event_number=after_id,
            limit=1000,
        )
        return [RunEventOut.model_validate(r) for r in rows]


@router.post("/{run_id}/cancel", response_model=OkResponse)
def cancel_run(request: Request, run_id: UUID, identity: Identity = IdentityDep) -> OkResponse:
    """Request cancellation of a run.

    If the run is queued, it will be canceled immediately.
    If the run is running, the cancel flag will be set for cooperative cancellation
    (the worker will check the flag between stages and stop execution).

    If the run is already in a terminal state (succeeded, failed, canceled),
    this endpoint returns success without making changes.
    """
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        cancel_user_run(
            request=request,
            session=session,
            tenant_id=get_tenant_id(identity),
            run_id=run_id,
            identity=identity,
        )
        return OkResponse()


class RetryRunBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    llm_model: str | None = Field(default=None, min_length=1)


@router.post("/{run_id}/retry", response_model=WebRunOut)
def retry_run_endpoint(
    request: Request, run_id: UUID, body: RetryRunBody = RetryRunBody(), identity: Identity = IdentityDep
) -> WebRunOut:
    """Retry a failed or blocked run.

    This endpoint:
    1. Validates the run is in a failed or blocked state
    2. Increments the retry counter
    3. Resets the run to queued status
    4. Clears failure info and cancel requests
    5. Re-enqueues the job for execution

    Only allowed for runs in 'failed' or 'blocked' status.
    """
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        run = retry_user_run(
            request=request,
            session=session,
            tenant_id=get_tenant_id(identity),
            run_id=run_id,
            identity=identity,
            llm_model=body.llm_model,
        )
        return WebRunOut.model_validate(run_to_web(run))


@router.get("/{run_id}/artifacts", response_model=list[ArtifactOut], response_model_by_alias=True)
def get_artifacts_for_run(
    request: Request, run_id: UUID, identity: Identity = IdentityDep
) -> list[ArtifactOut]:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        return list_user_run_artifacts(
            session=session,
            tenant_id=get_tenant_id(identity),
            run_id=run_id,
            user_id=identity.user_id,
        )


@router.get("/{run_id}/snippets")
def get_snippets_for_run(
    request: Request, run_id: UUID, identity: Identity = IdentityDep
) -> list[dict]:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        return list_user_run_snippets(
            session=session,
            tenant_id=get_tenant_id(identity),
            run_id=run_id,
            user_id=identity.user_id,
        )


@router.post("/{run_id}/evaluate")
def trigger_evaluation(
    request: Request, run_id: UUID, identity: Identity = IdentityDep
):
    """Trigger on-demand evaluation of a research report. Streams SSE events."""
    SessionLocal = request.app.state.SessionLocal
    tenant_id = get_tenant_id(identity)

    # Verify access
    with session_scope(SessionLocal) as session:
        run = get_user_run_or_404(
            session=session, tenant_id=tenant_id, run_id=run_id, user_id=identity.user_id
        )
        usage = get_run_usage_metrics(run)
        if usage.get(METRIC_EVAL_STATUS) == "running":
            raise HTTPException(status_code=409, detail="evaluation_already_running")

    async def _gen():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        sentinel = object()

        def _run_sync():
            try:
                with session_scope(SessionLocal) as session:
                    runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
                    for event in runner.run():
                        loop.call_soon_threadsafe(queue.put_nowait, event)
            except ValueError as exc:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "code": str(exc)})
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "code": "internal_error", "message": str(exc)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, sentinel)

        thread = threading.Thread(target=_run_sync, daemon=True)
        thread.start()

        while True:
            event = await queue.get()
            if event is sentinel:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.get("/{run_id}/evaluation")
def get_evaluation(
    request: Request, run_id: UUID, identity: Identity = IdentityDep
) -> dict:
    """Return stored evaluation results for a run."""
    SessionLocal = request.app.state.SessionLocal
    tenant_id = get_tenant_id(identity)

    with session_scope(SessionLocal) as session:
        run = get_user_run_or_404(
            session=session, tenant_id=tenant_id, run_id=run_id, user_id=identity.user_id
        )
        usage = get_run_usage_metrics(run)
        status = usage.get(METRIC_EVAL_STATUS, "none")
        history = list_evaluation_pass_history(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
            include_running=status == "running",
        )

        if status not in ("complete", "running") and not history:
            return {"status": "none"}
        if status not in ("complete", "running") and history:
            status = "complete"

        # Load section titles
        section_rows = (
            session.query(RunSectionRow)
            .filter(RunSectionRow.tenant_id == tenant_id, RunSectionRow.run_id == run_id)
            .order_by(RunSectionRow.section_order)
            .all()
        )
        titles = {r.section_id: r.title for r in section_rows}

        reviews = (
            session.query(SectionReviewRow)
            .filter(SectionReviewRow.tenant_id == tenant_id, SectionReviewRow.run_id == run_id)
            .all()
        )

        issues_by_type: dict[str, int] = {}
        latest_history = history[0] if history else None
        sections_out = []
        latest_history_sections = latest_history["sections"] if latest_history else []
        latest_scores = {
            section["section_id"]: section.get("grounding_score")
            for section in latest_history_sections
            if isinstance(section, dict)
        }
        if latest_history_sections:
            sections_out = [
                {
                    "section_id": section["section_id"],
                    "title": titles.get(section["section_id"], section.get("title") or section["section_id"]),
                    "grounding_score": section.get("grounding_score"),
                    "verdict": section.get("verdict"),
                    "issues": section.get("issues") or [],
                }
                for section in latest_history_sections
                if isinstance(section, dict) and isinstance(section.get("section_id"), str)
            ]
            issues_by_type = dict(latest_history.get("issues_by_type") or {})
        elif not (status == "running" and latest_history):
            for review in reviews:
                issues = review.issues_json or []
                for issue in issues:
                    p = issue.get("problem", "unknown")
                    issues_by_type[p] = issues_by_type.get(p, 0) + 1
                sections_out.append({
                    "section_id": review.section_id,
                    "title": titles.get(review.section_id, review.section_id),
                    "grounding_score": latest_scores.get(review.section_id),
                    "verdict": review.verdict,
                    "issues": issues,
                })

        if status == "running":
            grounding_pct = latest_history.get("grounding_pct") if latest_history else None
            faithfulness_pct = latest_history.get("faithfulness_pct") if latest_history else None
            sections_passed = latest_history.get("sections_passed") if latest_history else None
            sections_total = latest_history.get("sections_total") if latest_history else None
            evaluated_at = latest_history.get("evaluated_at") if latest_history else None
        else:
            grounding_pct = usage.get(METRIC_EVAL_GROUNDING_PCT)
            if grounding_pct is None and latest_history:
                grounding_pct = latest_history.get("grounding_pct")

            faithfulness_pct = usage.get("eval_faithfulness_pct")
            if faithfulness_pct is None and latest_history:
                faithfulness_pct = latest_history.get("faithfulness_pct")

            sections_passed = usage.get("eval_sections_passed")
            if sections_passed is None and latest_history:
                sections_passed = latest_history.get("sections_passed")
            sections_total = usage.get("eval_sections_total")
            if sections_total is None and latest_history:
                sections_total = latest_history.get("sections_total")
            evaluated_at = usage.get("eval_evaluated_at")
            if evaluated_at is None and latest_history:
                evaluated_at = latest_history.get("evaluated_at")

        if sections_passed is None and not (status == "running" and latest_history):
            sections_passed = sum(1 for r in reviews if r.verdict == "pass")
        if sections_total is None and not (status == "running" and latest_history):
            sections_total = len(reviews)

        return {
            "status": status,
            "evaluated_at": evaluated_at,
            "grounding_pct": grounding_pct,
            "faithfulness_pct": faithfulness_pct,
            "sections_passed": sections_passed,
            "sections_total": sections_total,
            "issues_by_type": issues_by_type,
            "sections": sections_out,
            "history": history,
        }
