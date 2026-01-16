from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from db.models import ArtifactRow, RunRow
from db.models.runs import RunStatusDb
from db.session import session_scope

from researchops_api.middlewares.auth import get_identity
from researchops_core.audit.logger import write_audit_log
from researchops_core.auth.identity import Identity
from researchops_core.auth.rbac import require_roles
from researchops_core.models import ArtifactResponse, RunResponse, RunStatus
from researchops_observability.logging import bind_log_context
from researchops_orchestrator import enqueue_hello_run

router = APIRouter(prefix="/runs", tags=["runs"])


def _to_run_status(status: RunStatusDb) -> RunStatus:
    return RunStatus(status.value)


@router.post("/hello")
def hello_run(request: Request, identity: Identity = Depends(get_identity)) -> dict[str, str]:
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    bind_log_context(tenant_id_value=identity.tenant_id, run_id_value=None)

    with session_scope(SessionLocal) as session:
        run_id = enqueue_hello_run(session=session, tenant_id=identity.tenant_id)
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
def get_run(request: Request, run_id: UUID, identity: Identity = Depends(get_identity)) -> RunResponse:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        run = session.execute(
            select(RunRow).where(RunRow.id == run_id, RunRow.tenant_id == identity.tenant_id)
        ).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        artifacts = (
            session.execute(
                select(ArtifactRow).where(
                    ArtifactRow.run_id == run_id,
                    ArtifactRow.tenant_id == identity.tenant_id,
                )
            )
            .scalars()
            .all()
        )

    return RunResponse(
        id=run.id,
        tenant_id=run.tenant_id,
        status=_to_run_status(run.status),
        created_at=run.created_at,
        updated_at=run.updated_at,
        error_message=run.error_message,
        artifacts=[ArtifactResponse(id=a.id, artifact_type=a.artifact_type, created_at=a.created_at) for a in artifacts],
    )
