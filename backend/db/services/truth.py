from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import ArtifactRow, ProjectRow, RunEventRow, RunRow
from db.models.projects import ProjectLastRunStatusDb
from db.models.run_events import RunEventLevelDb
from db.models.runs import RunStatusDb



def _now_utc() -> datetime:
    return datetime.now(UTC)


def create_project(
    *,
    session: Session,
    tenant_id: UUID,
    name: str,
    description: str | None,
    created_by: str,
) -> ProjectRow:
    now = _now_utc()
    row = ProjectRow(
        tenant_id=tenant_id,
        name=name,
        description=description,
        created_by=created_by,
        last_activity_at=now,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as e:
        raise ValueError("project name already exists for tenant") from e
    return row


def list_projects(*, session: Session, tenant_id: UUID, limit: int = 200) -> list[ProjectRow]:
    stmt = (
        select(ProjectRow)
        .where(ProjectRow.tenant_id == tenant_id)
        .order_by(func.coalesce(ProjectRow.last_activity_at, ProjectRow.created_at).desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def get_project(*, session: Session, tenant_id: UUID, project_id: UUID) -> ProjectRow | None:
    stmt = select(ProjectRow).where(ProjectRow.tenant_id == tenant_id, ProjectRow.id == project_id)
    return session.execute(stmt).scalar_one_or_none()


def create_run(
    *,
    session: Session,
    tenant_id: UUID,
    project_id: UUID,
    status: RunStatusDb = RunStatusDb.queued,
    current_stage: str | None = None,
    question: str | None = None,
    output_type: str = "report",
    client_request_id: str | None = None,
    budgets_json: dict | None = None,
) -> RunRow:
    project = get_project(session=session, tenant_id=tenant_id, project_id=project_id)
    if project is None:
        raise ValueError("project not found")

    now = _now_utc()
    run = RunRow(
        tenant_id=tenant_id,
        project_id=project_id,
        status=status,
        current_stage=current_stage,
        question=question,
        output_type=output_type,
        client_request_id=client_request_id,
        budgets_json=budgets_json or {},
        usage_json={},
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    session.flush()

    _touch_project_from_run(
        session=session, project_id=project_id, tenant_id=tenant_id, run=run, now=now
    )
    return run


def get_run(*, session: Session, tenant_id: UUID, run_id: UUID) -> RunRow | None:
    stmt = select(RunRow).where(RunRow.tenant_id == tenant_id, RunRow.id == run_id)
    run = session.execute(stmt).scalar_one_or_none()
    return run


def get_run_by_client_request_id(
    *, session: Session, tenant_id: UUID, project_id: UUID, client_request_id: str
) -> RunRow | None:
    stmt = select(RunRow).where(
        RunRow.tenant_id == tenant_id,
        RunRow.project_id == project_id,
        RunRow.client_request_id == client_request_id,
    )
    return session.execute(stmt).scalar_one_or_none()


def append_run_event(
    *,
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    level: RunEventLevelDb,
    message: str,
    stage: str | None = None,
    event_type: str = "log",
    payload_json: dict | None = None,
    allow_finished: bool = False,
) -> RunEventRow:
    run = get_run(session=session, tenant_id=tenant_id, run_id=run_id)
    if run is None:
        raise ValueError("run not found")
    if not allow_finished and run.status in {
        RunStatusDb.failed,
        RunStatusDb.succeeded,
        RunStatusDb.canceled,
    }:
        raise ValueError("cannot append events to a finished run")

    now = _now_utc()
    next_event_number = (
        session.execute(
            select(func.coalesce(func.max(RunEventRow.event_number), 0) + 1).where(
                RunEventRow.tenant_id == tenant_id,
                RunEventRow.run_id == run_id,
            )
        ).scalar_one()
        or 1
    )
    row = RunEventRow(
        tenant_id=tenant_id,
        run_id=run_id,
        event_number=int(next_event_number),
        ts=now,
        stage=stage,
        event_type=event_type,
        level=level,
        message=message,
        payload_json=payload_json or {},
    )
    session.add(row)

    _touch_project_from_run(
        session=session, project_id=run.project_id, tenant_id=tenant_id, run=run, now=now
    )
    session.flush()
    return row


def list_run_events(
    *,
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    limit: int = 1000,
    after_event_number: int | None = None,
) -> list[RunEventRow]:
    """List run events, optionally filtering by event_number for SSE streaming.

    Args:
        session: Database session
        tenant_id: Tenant ID
        run_id: Run ID
        limit: Maximum number of events to return
        after_event_number: If provided, only return events with event_number > this value

    Returns:
        List of RunEventRow ordered by event_number ascending
    """
    stmt = select(RunEventRow).where(RunEventRow.tenant_id == tenant_id, RunEventRow.run_id == run_id)

    if after_event_number is not None:
        stmt = stmt.where(RunEventRow.event_number > after_event_number)

    stmt = stmt.order_by(RunEventRow.event_number.asc()).limit(limit)

    rows = list(session.execute(stmt).scalars().all())
    return rows


def create_artifact(
    *,
    session: Session,
    tenant_id: UUID,
    project_id: UUID,
    run_id: UUID | None,
    artifact_type: str,
    blob_ref: str,
    mime_type: str,
    size_bytes: int | None = None,
    metadata_json: dict | None = None,
) -> ArtifactRow:
    project = get_project(session=session, tenant_id=tenant_id, project_id=project_id)
    if project is None:
        raise ValueError("project not found")

    if run_id is not None:
        run = get_run(session=session, tenant_id=tenant_id, run_id=run_id)
        if run is None:
            raise ValueError("run not found")
        if run.project_id != project_id:
            raise ValueError("run does not belong to project")

    row = ArtifactRow(
        tenant_id=tenant_id,
        project_id=project_id,
        run_id=run_id,
        artifact_type=artifact_type,
        blob_ref=blob_ref,
        mime_type=mime_type,
        size_bytes=size_bytes,
        metadata_json=metadata_json or {},
    )
    session.add(row)
    session.flush()
    return row


def list_artifacts(
    *,
    session: Session,
    tenant_id: UUID,
    project_id: UUID | None = None,
    run_id: UUID | None = None,
    limit: int = 200,
) -> list[ArtifactRow]:
    stmt: Select[tuple[ArtifactRow]] = select(ArtifactRow).where(ArtifactRow.tenant_id == tenant_id)
    if project_id is not None:
        stmt = stmt.where(ArtifactRow.project_id == project_id)
    if run_id is not None:
        stmt = stmt.where(ArtifactRow.run_id == run_id)
    stmt = stmt.order_by(ArtifactRow.created_at.desc()).limit(limit)
    return list(session.execute(stmt).scalars().all())


def _touch_project_from_run(
    *, session: Session, tenant_id: UUID, project_id: UUID, run: RunRow, now: datetime
) -> None:
    session.execute(
        update(ProjectRow)
        .where(ProjectRow.tenant_id == tenant_id, ProjectRow.id == project_id)
        .values(
            last_run_id=run.id,
            last_run_status=ProjectLastRunStatusDb(run.status.value),
            last_activity_at=now,
            updated_at=now,
        )
    )
