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
from researchops_core.audit.logger import write_audit_log
from researchops_core.auth.identity import Identity
from researchops_core.auth.rbac import require_roles
from researchops_core.tenancy import tenant_uuid
from researchops_observability.logging import bind_log_context
from researchops_orchestrator import enqueue_hello_run

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
    project_id: UUID | None = None
    tenant_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    error_message: str | None = None
    budgets: dict = Field(default_factory=dict)


def _run_to_web(run) -> WebRunOut:
    return WebRunOut(
        id=run.id,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        status=run.status.value,
        created_at=run.created_at,
        updated_at=run.updated_at,
        error_message=run.failure_reason,
        budgets=run.budgets_json or {},
    )


_ALLOWED_STAGES = {"retrieve", "ingest", "outline", "draft", "validate", "factcheck", "export"}


def _event_to_sse(event) -> str:
    level = event.level.value
    if level == "debug":
        level = "info"
    if level not in {"info", "warn", "error"}:
        level = "info"
    stage = (event.stage or "retrieve").strip().lower()
    if stage not in _ALLOWED_STAGES:
        stage = "retrieve"
    payload = event.payload_json or {}
    data = {
        "ts": event.ts.isoformat(),
        "level": level,
        "stage": stage,
        "message": event.message,
        "payload": payload,
    }
    return f"event: message\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


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
                payload_json=body.payload_json,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return RunEventOut.model_validate(ev)


@router.get("/{run_id}/events")
def get_run_events(request: Request, run_id: UUID, identity: Identity = IdentityDep):
    accept = request.headers.get("accept", "")
    SessionLocal = request.app.state.SessionLocal

    if "text/event-stream" in accept:
        tenant_id = _tenant_uuid(identity)

        async def _gen():
            last_ts: datetime | None = None
            last_id: UUID | None = None
            while True:
                with session_scope(SessionLocal) as session:
                    rows = list_run_events(
                        session=session, tenant_id=tenant_id, run_id=run_id, limit=500
                    )
                    for row in rows:
                        if last_ts is not None:
                            if row.ts < last_ts:
                                continue
                            if row.ts == last_ts and last_id is not None and row.id <= last_id:
                                continue
                        yield _event_to_sse(row)
                        last_ts = row.ts
                        last_id = row.id
                await asyncio.sleep(1.0)

        return StreamingResponse(_gen(), media_type="text/event-stream")

    with session_scope(SessionLocal) as session:
        rows = list_run_events(session=session, tenant_id=_tenant_uuid(identity), run_id=run_id)
        return [RunEventOut.model_validate(r) for r in rows]


@router.post("/{run_id}/cancel", response_model=OkResponse)
def cancel_run(request: Request, run_id: UUID, identity: Identity = IdentityDep) -> OkResponse:
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        run = get_run(session=session, tenant_id=_tenant_uuid(identity), run_id=run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        if run.status in {RunStatusDb.failed, RunStatusDb.succeeded, RunStatusDb.canceled}:
            return OkResponse()
        update_run_status(
            session=session,
            tenant_id=_tenant_uuid(identity),
            run_id=run_id,
            status=RunStatusDb.canceled,
            finished_at=datetime.now(UTC),
        )
        return OkResponse()


@router.post("/{run_id}/retry", response_model=OkResponse)
def retry_run(request: Request, run_id: UUID, identity: Identity = IdentityDep) -> OkResponse:
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        run = get_run(session=session, tenant_id=_tenant_uuid(identity), run_id=run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        update_run_status(
            session=session,
            tenant_id=_tenant_uuid(identity),
            run_id=run_id,
            status=RunStatusDb.queued,
            current_stage=None,
            failure_reason=None,
            error_code=None,
            finished_at=None,
        )
        return OkResponse()


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
