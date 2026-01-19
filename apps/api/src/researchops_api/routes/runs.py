"""Run management endpoints with production-grade lifecycle and SSE streaming."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from researchops_api.middlewares.auth import IdentityDep
from researchops_api.schemas.truth import (
    ArtifactOut,
    ClaimMapCreate,
    ClaimMapOut,
    RunEventCreate,
    RunEventOut,
    RunUpdateStatus,
)
from researchops_core.runs import (
    RunNotFoundError,
    RunTransitionError,
    check_cancel_requested,
    emit_run_event,
    request_cancel,
    retry_run,
)
from researchops_core.audit.logger import write_audit_log
from researchops_core.auth.identity import Identity
from researchops_core.auth.rbac import require_roles
from researchops_core.tenancy import tenant_uuid
from researchops_observability.logging import bind_log_context
from researchops_orchestrator import HELLO_JOB_TYPE, enqueue_hello_run, enqueue_run_job

from db.models.run_events import RunEventLevelDb
from db.models.runs import RunStatusDb
from db.services.truth import (
    append_run_event,
    create_claim_map_entries,
    get_run,
    list_artifacts,
    list_claims,
    list_run_events,
    update_run_status,
)
from db.session import session_scope

router = APIRouter(prefix="/runs", tags=["runs"])


def _tenant_uuid(identity: Identity) -> UUID:
    return tenant_uuid(identity.tenant_id)


class OkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True


class WebRunOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: UUID
    status: str
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


def _run_to_web(run) -> WebRunOut:
    return WebRunOut(
        id=run.id,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        status=run.status.value,
        current_stage=run.current_stage,
        created_at=run.created_at,
        updated_at=run.updated_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        cancel_requested_at=run.cancel_requested_at,
        retry_count=run.retry_count,
        error_message=run.failure_reason,
        error_code=run.error_code,
        budgets=run.budgets_json or {},
        usage=run.usage_json or {},
    )


_ALLOWED_STAGES = {"retrieve", "ingest", "outline", "draft", "validate", "factcheck", "export"}


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
    return f"id: {event.event_number}\nevent: run_event\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


@router.post("/hello")
def hello_run(request: Request, identity: Identity = IdentityDep) -> dict[str, str]:
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    bind_log_context(tenant_id_value=identity.tenant_id, run_id_value=None)

    with session_scope(SessionLocal) as session:
        run_id = enqueue_hello_run(session=session, tenant_id=_tenant_uuid(identity))
        write_audit_log(
            db=session,
            identity=identity,
            action="run.enqueue",
            target_type="run",
            target_id=str(run_id),
            metadata={"job_type": "hello.run"},
            request=request,
        )
    return {"run_id": str(run_id)}


@router.get("/{run_id}")
def get_run_by_id(request: Request, run_id: UUID, identity: Identity = IdentityDep) -> WebRunOut:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        run = get_run(session=session, tenant_id=_tenant_uuid(identity), run_id=run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return _run_to_web(run)


@router.patch("/{run_id}", response_model=WebRunOut)
def patch_run(
    request: Request,
    run_id: UUID,
    body: RunUpdateStatus,
    identity: Identity = IdentityDep,
) -> WebRunOut:
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        try:
            run = update_run_status(
                session=session,
                tenant_id=_tenant_uuid(identity),
                run_id=run_id,
                status=RunStatusDb(body.status),
                current_stage=body.current_stage,
                failure_reason=body.failure_reason,
                error_code=body.error_code,
                started_at=body.started_at,
                finished_at=body.finished_at,
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return _run_to_web(run)


@router.post("/{run_id}/events", response_model=RunEventOut)
def post_run_event(
    request: Request, run_id: UUID, body: RunEventCreate, identity: Identity = IdentityDep
) -> RunEventOut:
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        try:
            ev = append_run_event(
                session=session,
                tenant_id=_tenant_uuid(identity),
                run_id=run_id,
                level=RunEventLevelDb(body.level),
                message=body.message,
                stage=body.stage,
                event_type=getattr(body, "event_type", "log"),
                payload_json=body.payload_json,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return RunEventOut.model_validate(ev)


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
        data: {"id": <event_number>, "ts": "...", "level": "...", "stage": "...", "message": "...", ...}

    """
    accept = request.headers.get("accept", "")
    SessionLocal = request.app.state.SessionLocal
    tenant_id = _tenant_uuid(identity)

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

                    # Check if run is terminal
                    run = get_run(session=session, tenant_id=tenant_id, run_id=run_id)
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
        try:
            run = request_cancel(
                session=session,
                tenant_id=_tenant_uuid(identity),
                run_id=run_id,
                force_immediate=False,
            )
            write_audit_log(
                db=session,
                identity=identity,
                action="run.cancel",
                target_type="run",
                target_id=str(run_id),
                metadata={"status": run.status.value},
                request=request,
            )
        except RunNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

        return OkResponse()


@router.post("/{run_id}/retry", response_model=WebRunOut)
def retry_run_endpoint(
    request: Request, run_id: UUID, identity: Identity = IdentityDep
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
        try:
            run = retry_run(
                session=session,
                tenant_id=_tenant_uuid(identity),
                run_id=run_id,
            )
            enqueue_run_job(
                session=session,
                tenant_id=_tenant_uuid(identity),
                run_id=run.id,
                job_type=HELLO_JOB_TYPE,
            )
            write_audit_log(
                db=session,
                identity=identity,
                action="run.retry",
                target_type="run",
                target_id=str(run_id),
                metadata={"retry_count": run.retry_count},
                request=request,
            )

        except (RunNotFoundError, RunTransitionError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        return _run_to_web(run)


@router.get("/{run_id}/artifacts", response_model=list[ArtifactOut])
def get_artifacts_for_run(
    request: Request, run_id: UUID, identity: Identity = IdentityDep
) -> list[ArtifactOut]:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        rows = list_artifacts(session=session, tenant_id=_tenant_uuid(identity), run_id=run_id)
        return [
            ArtifactOut(
                id=a.id,
                tenant_id=a.tenant_id,
                project_id=a.project_id,
                run_id=a.run_id,
                type=a.artifact_type,
                blob_ref=a.blob_ref,
                mime_type=a.mime_type,
                size_bytes=a.size_bytes,
                metadata_json=a.metadata_json,
                created_at=a.created_at,
            )
            for a in rows
        ]


@router.post("/{run_id}/claims", response_model=list[ClaimMapOut])
def post_claims(
    request: Request,
    run_id: UUID,
    body: list[ClaimMapCreate],
    identity: Identity = IdentityDep,
) -> list[ClaimMapOut]:
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        try:
            rows = create_claim_map_entries(
                session=session,
                tenant_id=_tenant_uuid(identity),
                run_id=run_id,
                entries=[
                    {
                        "claim_text": c.claim_text,
                        "snippet_ids_json": [str(sid) for sid in c.snippet_ids],
                        "verdict": c.verdict,
                        "explanation": c.explanation,
                        "metadata_json": c.metadata_json,
                    }
                    for c in body
                ],
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

        return [
            ClaimMapOut(
                id=r.id,
                tenant_id=r.tenant_id,
                project_id=r.project_id,
                run_id=r.run_id,
                claim_text=r.claim_text,
                claim_hash=r.claim_hash,
                snippet_ids=[UUID(s) for s in (r.snippet_ids_json or [])],
                verdict=r.verdict.value,
                explanation=r.explanation,
                metadata_json=r.metadata_json,
                created_at=r.created_at,
            )
            for r in rows
        ]


@router.get("/{run_id}/claims", response_model=list[ClaimMapOut])
def get_claims(
    request: Request, run_id: UUID, identity: Identity = IdentityDep
) -> list[ClaimMapOut]:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        rows = list_claims(session=session, tenant_id=_tenant_uuid(identity), run_id=run_id)
        return [
            ClaimMapOut(
                id=r.id,
                tenant_id=r.tenant_id,
                project_id=r.project_id,
                run_id=r.run_id,
                claim_text=r.claim_text,
                claim_hash=r.claim_hash,
                snippet_ids=[UUID(s) for s in (r.snippet_ids_json or [])],
                verdict=r.verdict.value,
                explanation=r.explanation,
                metadata_json=r.metadata_json,
                created_at=r.created_at,
            )
            for r in rows
        ]
