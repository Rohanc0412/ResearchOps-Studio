from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, and_, select
from sqlalchemy.orm import Session

from db.models import ArtifactRow, ProjectRow
from db.repositories.project_runs import get_project, get_run


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


def get_artifact_for_user(
    *,
    session: Session,
    tenant_id: UUID,
    artifact_id: UUID,
    created_by: str,
) -> ArtifactRow | None:
    stmt = (
        select(ArtifactRow)
        .join(
            ProjectRow,
            and_(
                ProjectRow.tenant_id == ArtifactRow.tenant_id,
                ProjectRow.id == ArtifactRow.project_id,
            ),
        )
        .where(
            ArtifactRow.id == artifact_id,
            ArtifactRow.tenant_id == tenant_id,
            ProjectRow.created_by == created_by,
        )
    )
    return session.execute(stmt).scalar_one_or_none()


__all__ = ["create_artifact", "get_artifact_for_user", "list_artifacts"]
