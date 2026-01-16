from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import (
    ArtifactRow,
    ClaimMapRow,
    ProjectRow,
    RunEventRow,
    RunRow,
    SnapshotRow,
    SnippetEmbeddingRow,
    SnippetRow,
    SourceRow,
)
from db.models.claim_map import ClaimVerdictDb
from db.models.projects import ProjectLastRunStatusDb
from db.models.run_events import RunEventLevelDb
from db.models.runs import RunStatusDb


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _claim_hash(text: str) -> str:
    return _sha256_hex(text.strip())


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


def list_runs_for_project(
    *, session: Session, tenant_id: UUID, project_id: UUID, limit: int = 200
) -> list[RunRow]:
    stmt = (
        select(RunRow)
        .where(RunRow.tenant_id == tenant_id, RunRow.project_id == project_id)
        .order_by(RunRow.created_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def get_run(*, session: Session, tenant_id: UUID, run_id: UUID) -> RunRow | None:
    stmt = select(RunRow).where(RunRow.tenant_id == tenant_id, RunRow.id == run_id)
    return session.execute(stmt).scalar_one_or_none()


def update_run_status(
    *,
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    status: RunStatusDb,
    current_stage: str | None = None,
    failure_reason: str | None = None,
    error_code: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> RunRow:
    run = get_run(session=session, tenant_id=tenant_id, run_id=run_id)
    if run is None:
        raise ValueError("run not found")

    now = _now_utc()
    run.status = status
    run.current_stage = current_stage
    run.failure_reason = failure_reason
    run.error_code = error_code
    run.started_at = started_at or run.started_at
    run.finished_at = finished_at or run.finished_at
    run.updated_at = now

    _touch_project_from_run(
        session=session, project_id=run.project_id, tenant_id=tenant_id, run=run, now=now
    )
    session.flush()
    return run


def append_run_event(
    *,
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    level: RunEventLevelDb,
    message: str,
    stage: str | None = None,
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
    row = RunEventRow(
        tenant_id=tenant_id,
        run_id=run_id,
        ts=now,
        stage=stage,
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
    *, session: Session, tenant_id: UUID, run_id: UUID, limit: int = 1000
) -> list[RunEventRow]:
    stmt = (
        select(RunEventRow)
        .where(RunEventRow.tenant_id == tenant_id, RunEventRow.run_id == run_id)
        .order_by(RunEventRow.ts.asc(), RunEventRow.id.asc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def upsert_source(
    *,
    session: Session,
    tenant_id: UUID,
    canonical_id: str,
    source_type: str,
    title: str | None = None,
    authors_json: list | None = None,
    year: int | None = None,
    url: str | None = None,
    metadata_json: dict | None = None,
) -> SourceRow:
    row = session.execute(
        select(SourceRow).where(
            SourceRow.tenant_id == tenant_id, SourceRow.canonical_id == canonical_id
        )
    ).scalar_one_or_none()
    if row is None:
        row = SourceRow(
            tenant_id=tenant_id,
            canonical_id=canonical_id,
            source_type=source_type,
            title=title,
            authors_json=authors_json or [],
            year=year,
            url=url,
            metadata_json=metadata_json or {},
        )
        session.add(row)
        session.flush()
        return row

    row.source_type = source_type
    row.title = title
    row.authors_json = authors_json or []
    row.year = year
    row.url = url
    row.metadata_json = metadata_json or {}
    row.updated_at = _now_utc()
    session.flush()
    return row


def create_snapshot(
    *,
    session: Session,
    tenant_id: UUID,
    source_id: UUID,
    content_type: str | None,
    blob_ref: str,
    sha256: str,
    size_bytes: int | None = None,
    metadata_json: dict | None = None,
) -> SnapshotRow:
    source = session.execute(
        select(SourceRow).where(SourceRow.tenant_id == tenant_id, SourceRow.id == source_id)
    ).scalar_one_or_none()
    if source is None:
        raise ValueError("source not found")

    next_version = session.execute(
        select(func.coalesce(func.max(SnapshotRow.snapshot_version), 0) + 1).where(
            SnapshotRow.tenant_id == tenant_id, SnapshotRow.source_id == source_id
        )
    ).scalar_one()

    row = SnapshotRow(
        tenant_id=tenant_id,
        source_id=source_id,
        snapshot_version=int(next_version),
        content_type=content_type,
        blob_ref=blob_ref,
        sha256=sha256,
        size_bytes=size_bytes,
        metadata_json=metadata_json or {},
    )
    session.add(row)
    session.flush()
    return row


def create_snippets(
    *,
    session: Session,
    tenant_id: UUID,
    snapshot_id: UUID,
    snippets: list[dict],
) -> list[SnippetRow]:
    snapshot = session.execute(
        select(SnapshotRow).where(SnapshotRow.tenant_id == tenant_id, SnapshotRow.id == snapshot_id)
    ).scalar_one_or_none()
    if snapshot is None:
        raise ValueError("snapshot not found")

    start_index = session.execute(
        select(func.coalesce(func.max(SnippetRow.snippet_index), -1) + 1).where(
            SnippetRow.tenant_id == tenant_id, SnippetRow.snapshot_id == snapshot_id
        )
    ).scalar_one()
    start_index_int = int(start_index)

    out: list[SnippetRow] = []
    for offset, item in enumerate(snippets):
        text = str(item["text"])
        sha256 = item.get("sha256") or _sha256_hex(text)
        row = SnippetRow(
            tenant_id=tenant_id,
            snapshot_id=snapshot_id,
            snippet_index=start_index_int + offset,
            text=text,
            char_start=item.get("char_start"),
            char_end=item.get("char_end"),
            token_count=item.get("token_count"),
            sha256=sha256,
            risk_flags_json=item.get("risk_flags_json") or {},
        )
        session.add(row)
        out.append(row)
    session.flush()
    return out


def list_snippets(
    *, session: Session, tenant_id: UUID, snapshot_id: UUID, limit: int = 1000
) -> list[SnippetRow]:
    stmt = (
        select(SnippetRow)
        .where(SnippetRow.tenant_id == tenant_id, SnippetRow.snapshot_id == snapshot_id)
        .order_by(SnippetRow.snippet_index.asc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def write_snippet_embedding(
    *,
    session: Session,
    tenant_id: UUID,
    snippet_id: UUID,
    embedding_model: str,
    dims: int,
    embedding: list[float],
) -> SnippetEmbeddingRow:
    if dims != len(embedding):
        raise ValueError("dims does not match embedding length")

    snippet = session.execute(
        select(SnippetRow).where(SnippetRow.tenant_id == tenant_id, SnippetRow.id == snippet_id)
    ).scalar_one_or_none()
    if snippet is None:
        raise ValueError("snippet not found")

    row = session.execute(
        select(SnippetEmbeddingRow).where(
            SnippetEmbeddingRow.tenant_id == tenant_id,
            SnippetEmbeddingRow.snippet_id == snippet_id,
            SnippetEmbeddingRow.embedding_model == embedding_model,
        )
    ).scalar_one_or_none()
    if row is None:
        row = SnippetEmbeddingRow(
            tenant_id=tenant_id,
            snippet_id=snippet_id,
            embedding_model=embedding_model,
            dims=dims,
            embedding=embedding,
        )
        session.add(row)
        session.flush()
        return row

    row.dims = dims
    row.embedding = embedding
    session.flush()
    return row


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


def create_claim_map_entries(
    *,
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    entries: list[dict],
) -> list[ClaimMapRow]:
    run = get_run(session=session, tenant_id=tenant_id, run_id=run_id)
    if run is None:
        raise ValueError("run not found")

    out: list[ClaimMapRow] = []
    for entry in entries:
        claim_text = str(entry["claim_text"])
        claim_hash = entry.get("claim_hash") or _claim_hash(claim_text)
        verdict = ClaimVerdictDb(str(entry["verdict"]))
        row = ClaimMapRow(
            tenant_id=tenant_id,
            project_id=run.project_id,
            run_id=run_id,
            claim_text=claim_text,
            claim_hash=claim_hash,
            snippet_ids_json=entry.get("snippet_ids_json") or [],
            verdict=verdict,
            explanation=entry.get("explanation"),
            metadata_json=entry.get("metadata_json") or {},
        )
        session.add(row)
        out.append(row)
    session.flush()
    return out


def list_claims(
    *, session: Session, tenant_id: UUID, run_id: UUID, limit: int = 500
) -> list[ClaimMapRow]:
    stmt = (
        select(ClaimMapRow)
        .where(ClaimMapRow.tenant_id == tenant_id, ClaimMapRow.run_id == run_id)
        .order_by(ClaimMapRow.created_at.desc())
        .limit(limit)
    )
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
