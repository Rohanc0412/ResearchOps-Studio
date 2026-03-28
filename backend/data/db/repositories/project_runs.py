from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, and_, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from db.models import ProjectRow, RunEventRow, RunRow
from db.models.run_budget_limits import RunBudgetLimitRow
from db.models.run_events import RunEventLevelDb
from db.models.run_status_transitions import RunStatusTransitionRow
from db.models.run_usage_metrics import RunUsageMetricRow
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
    row = ProjectRow(
        tenant_id=tenant_id,
        name=name,
        description=description,
        created_by=created_by,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        raise ValueError("project name already exists for tenant") from exc
    return row


def list_projects(*, session: Session, tenant_id: UUID, limit: int = 200) -> list[ProjectRow]:
    stmt = (
        select(ProjectRow)
        .where(ProjectRow.tenant_id == tenant_id)
        .order_by(ProjectRow.updated_at.desc(), ProjectRow.created_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def list_projects_for_user(
    *, session: Session, tenant_id: UUID, created_by: str, limit: int = 200
) -> list[ProjectRow]:
    stmt = (
        select(ProjectRow)
        .where(ProjectRow.tenant_id == tenant_id, ProjectRow.created_by == created_by)
        .order_by(ProjectRow.updated_at.desc(), ProjectRow.created_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def get_project(*, session: Session, tenant_id: UUID, project_id: UUID) -> ProjectRow | None:
    stmt = select(ProjectRow).where(ProjectRow.tenant_id == tenant_id, ProjectRow.id == project_id)
    return session.execute(stmt).scalar_one_or_none()


def get_project_for_user(
    *, session: Session, tenant_id: UUID, project_id: UUID, created_by: str
) -> ProjectRow | None:
    stmt = select(ProjectRow).where(
        ProjectRow.tenant_id == tenant_id,
        ProjectRow.id == project_id,
        ProjectRow.created_by == created_by,
    )
    return session.execute(stmt).scalar_one_or_none()


def replace_run_budget_limits(run: RunRow, budgets: dict | None) -> None:
    rows = [
        RunBudgetLimitRow(
            tenant_id=run.tenant_id,
            run_id=run.id,
            budget_name=str(key),
            limit_value=int(value),
        )
        for key, value in (budgets or {}).items()
        if value is not None
    ]
    run.budget_limits = rows


def get_run_budget_limits(run: RunRow) -> dict[str, int]:
    return {row.budget_name: int(row.limit_value) for row in run.budget_limits}


def replace_run_usage_metrics(run: RunRow, usage: dict | None) -> None:
    rows: list[RunUsageMetricRow] = []
    for key, value in (usage or {}).items():
        metric = RunUsageMetricRow(tenant_id=run.tenant_id, run_id=run.id, metric_name=str(key))
        if isinstance(value, bool):
            metric.metric_text = "true" if value else "false"
        elif isinstance(value, int):
            metric.metric_number = value
        elif value is not None:
            metric.metric_text = str(value)
        rows.append(metric)
    run.usage_metrics = rows


def patch_run_usage_metrics(run: RunRow, updates: dict | None) -> None:
    payload = get_run_usage_metrics(run)
    payload.update(updates or {})
    replace_run_usage_metrics(run, payload)


def get_run_usage_metrics(run: RunRow) -> dict[str, object]:
    payload: dict[str, object] = {}
    for row in run.usage_metrics:
        if row.metric_text is not None:
            if row.metric_text == "true":
                payload[row.metric_name] = True
            elif row.metric_text == "false":
                payload[row.metric_name] = False
            else:
                payload[row.metric_name] = row.metric_text
        elif row.metric_number is not None:
            payload[row.metric_name] = int(row.metric_number)
    return payload


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
    budgets: dict | None = None,
    usage: dict | None = None,
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
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    session.flush()
    replace_run_budget_limits(run, budgets or {})
    replace_run_usage_metrics(run, usage or {})
    # Consult the module-level cache first so the DB introspection only fires once per
    # engine lifetime, not on every create_run call.
    _engine_id = id(session.connection().engine)
    _has_transitions = (
        _table_existence_cache.get(_engine_id, {}).get("run_status_transitions")
        or _table_exists(session, "run_status_transitions")
    )
    if _has_transitions:
        _record_status_transition(
            session=session,
            tenant_id=tenant_id,
            run=run,
            from_status=None,
            to_status=run.status.value,
            stage=current_stage,
        )
    _touch_project_from_run(
        session=session, project_id=project_id, tenant_id=tenant_id, now=now
    )
    return run


def get_run(*, session: Session, tenant_id: UUID, run_id: UUID) -> RunRow | None:
    stmt = select(RunRow).where(RunRow.tenant_id == tenant_id, RunRow.id == run_id)
    return session.execute(stmt).scalar_one_or_none()


def get_run_for_user(
    *, session: Session, tenant_id: UUID, run_id: UUID, created_by: str
) -> RunRow | None:
    stmt = (
        select(RunRow)
        .join(
            ProjectRow,
            and_(
                ProjectRow.tenant_id == RunRow.tenant_id,
                ProjectRow.id == RunRow.project_id,
            ),
        )
        .where(
            RunRow.tenant_id == tenant_id,
            RunRow.id == run_id,
            ProjectRow.created_by == created_by,
        )
    )
    return session.execute(stmt).scalar_one_or_none()


def get_latest_report_title(
    *, session: Session, tenant_id: UUID, project_id: UUID
) -> str | None:
    stmt = (
        select(RunRow.report_title)
        .where(
            RunRow.tenant_id == tenant_id,
            RunRow.project_id == project_id,
            RunRow.status == RunStatusDb.succeeded,
            RunRow.report_title.isnot(None),
        )
        .order_by(RunRow.finished_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


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
    # Use WITH FOR UPDATE to serialise concurrent event appends to the same run,
    # preventing two workers from reading the same MAX(event_number) before either inserts.
    _lock_stmt = (
        select(RunRow)
        .where(RunRow.tenant_id == tenant_id, RunRow.id == run_id)
        .with_for_update()
    )
    run = session.execute(_lock_stmt).scalar_one_or_none()
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
        session=session, project_id=run.project_id, tenant_id=tenant_id, now=now
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
    stmt: Select[tuple[RunEventRow]] = select(RunEventRow).where(
        RunEventRow.tenant_id == tenant_id, RunEventRow.run_id == run_id
    )
    if after_event_number is not None:
        stmt = stmt.where(RunEventRow.event_number > after_event_number)
    stmt = stmt.order_by(RunEventRow.event_number.asc()).limit(limit)
    return list(session.execute(stmt).scalars().all())


def _touch_project_from_run(
    *, session: Session, tenant_id: UUID, project_id: UUID, now: datetime
) -> None:
    session.execute(
        update(ProjectRow)
        .where(ProjectRow.tenant_id == tenant_id, ProjectRow.id == project_id)
        .values(updated_at=now)
    )


def _record_status_transition(
    *,
    session: Session,
    tenant_id: UUID,
    run: RunRow,
    from_status: str | None,
    to_status: str,
    stage: str | None,
    reason: str | None = None,
) -> None:
    session.add(
        RunStatusTransitionRow(
            tenant_id=tenant_id,
            run_id=run.id,
            from_status=from_status,
            to_status=to_status,
            stage=stage,
            reason=reason,
        )
    )


# Cache: engine_id → {table_name → exists}.  Only True results are cached because
# a table that exists will never disappear at runtime (no DROP TABLE in prod).
_table_existence_cache: dict[int, dict[str, bool]] = {}


def _table_exists(session: Session, table_name: str) -> bool:
    conn = session.connection()
    if conn is None:
        return False
    engine_id = id(conn.engine)
    engine_cache = _table_existence_cache.setdefault(engine_id, {})
    if table_name in engine_cache:
        return engine_cache[table_name]
    result = conn.dialect.has_table(conn, table_name)
    if result:
        engine_cache[table_name] = True
    return result


__all__ = [
    "append_run_event",
    "create_project",
    "create_run",
    "get_latest_report_title",
    "get_project",
    "get_project_for_user",
    "get_run",
    "get_run_budget_limits",
    "get_run_by_client_request_id",
    "get_run_for_user",
    "get_run_usage_metrics",
    "list_projects",
    "list_projects_for_user",
    "list_run_events",
    "patch_run_usage_metrics",
    "replace_run_budget_limits",
    "replace_run_usage_metrics",
]
