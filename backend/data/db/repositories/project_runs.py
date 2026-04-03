from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, and_, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, attributes, selectinload

from db.models import ProjectRow, RunEventRow, RunRow
from db.models.run_budget_limits import RunBudgetLimitRow
from db.models.run_checkpoints import RunCheckpointRow
from db.models.run_events import RunEventAudienceDb, RunEventLevelDb
from db.models.run_status_transitions import RunStatusTransitionRow
from db.models.run_usage_metrics import RunUsageMetricRow
from db.models.runs import RunStatusDb


def _now_utc() -> datetime:
    return datetime.now(UTC)


async def create_project(
    *,
    session: AsyncSession,
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
    # Pre-initialize the `runs` collection so that accessing `last_run_id` etc. via
    # pydantic model_validate doesn't trigger an implicit lazy load in async context.
    attributes.set_committed_value(row, "runs", [])
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ValueError("project name already exists for tenant") from exc
    return row


async def list_projects(*, session: AsyncSession, tenant_id: UUID, limit: int = 200) -> list[ProjectRow]:
    stmt = (
        select(ProjectRow)
        .where(ProjectRow.tenant_id == tenant_id)
        .options(selectinload(ProjectRow.runs))
        .order_by(ProjectRow.updated_at.desc(), ProjectRow.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_projects_for_user(
    *, session: AsyncSession, tenant_id: UUID, created_by: str, limit: int = 200
) -> list[ProjectRow]:
    stmt = (
        select(ProjectRow)
        .where(ProjectRow.tenant_id == tenant_id, ProjectRow.created_by == created_by)
        .options(selectinload(ProjectRow.runs))
        .order_by(ProjectRow.updated_at.desc(), ProjectRow.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_project(*, session: AsyncSession, tenant_id: UUID, project_id: UUID) -> ProjectRow | None:
    stmt = (
        select(ProjectRow)
        .where(ProjectRow.tenant_id == tenant_id, ProjectRow.id == project_id)
        .options(selectinload(ProjectRow.runs))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_project_for_user(
    *, session: AsyncSession, tenant_id: UUID, project_id: UUID, created_by: str
) -> ProjectRow | None:
    stmt = (
        select(ProjectRow)
        .where(
            ProjectRow.tenant_id == tenant_id,
            ProjectRow.id == project_id,
            ProjectRow.created_by == created_by,
        )
        .options(selectinload(ProjectRow.runs))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


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
    # Use set_committed_value to avoid lazy-loading the existing collection in async context.
    attributes.set_committed_value(run, "budget_limits", [])
    run.budget_limits = rows


def get_run_budget_limits(run: RunRow) -> dict[str, int]:
    return {row.budget_name: int(row.limit_value) for row in run.budget_limits}


def replace_run_usage_metrics(run: RunRow, usage: dict | None) -> None:
    existing = {row.metric_name: row for row in run.usage_metrics}
    retained_names: set[str] = set()

    for key, value in (usage or {}).items():
        name = str(key)
        metric = existing.get(name)
        if metric is None:
            metric = RunUsageMetricRow(tenant_id=run.tenant_id, run_id=run.id, metric_name=name)
            run.usage_metrics.append(metric)

        metric.metric_text = None
        metric.metric_number = None
        if isinstance(value, bool):
            metric.metric_text = "true" if value else "false"
        elif isinstance(value, int):
            metric.metric_number = value
        elif value is not None:
            metric.metric_text = str(value)
        retained_names.add(name)

    for name, metric in list(existing.items()):
        if name not in retained_names and metric in run.usage_metrics:
            run.usage_metrics.remove(metric)


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


async def create_run(
    *,
    session: AsyncSession,
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
    project = await get_project(session=session, tenant_id=tenant_id, project_id=project_id)
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
    await session.flush()
    # Pre-initialize relationship collections as empty so that replace_* helpers
    # can assign to them without triggering lazy-load SELECTs in async context.
    attributes.set_committed_value(run, "budget_limits", [])
    attributes.set_committed_value(run, "usage_metrics", [])
    replace_run_budget_limits(run, budgets or {})
    replace_run_usage_metrics(run, usage or {})
    # Consult the module-level cache first so the DB introspection only fires once per
    # engine lifetime, not on every create_run call.
    conn = await session.connection()
    _engine_id = id(conn.engine)
    _has_transitions = (
        _table_existence_cache.get(_engine_id, {}).get("run_status_transitions")
        or await _table_exists(session, "run_status_transitions")
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
    await _touch_project_from_run(
        session=session, project_id=project_id, tenant_id=tenant_id, now=now
    )
    return run


def _run_eager_options():
    """Return selectinload options for RunRow relationships used by run_to_web."""
    return [
        selectinload(RunRow.budget_limits),
        selectinload(RunRow.usage_metrics),
    ]


async def get_run(*, session: AsyncSession, tenant_id: UUID, run_id: UUID) -> RunRow | None:
    stmt = (
        select(RunRow)
        .where(RunRow.tenant_id == tenant_id, RunRow.id == run_id)
        .options(*_run_eager_options())
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_run_for_user(
    *, session: AsyncSession, tenant_id: UUID, run_id: UUID, created_by: str
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
        .options(*_run_eager_options())
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_latest_report_title(
    *, session: AsyncSession, tenant_id: UUID, project_id: UUID
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
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_run_by_client_request_id(
    *, session: AsyncSession, tenant_id: UUID, project_id: UUID, client_request_id: str
) -> RunRow | None:
    stmt = select(RunRow).where(
        RunRow.tenant_id == tenant_id,
        RunRow.project_id == project_id,
        RunRow.client_request_id == client_request_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def append_run_event(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    run_id: UUID,
    level: RunEventLevelDb,
    message: str,
    audience: RunEventAudienceDb = RunEventAudienceDb.diagnostic,
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
    run = (await session.execute(_lock_stmt)).scalar_one_or_none()
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
        (
            await session.execute(
                select(func.coalesce(func.max(RunEventRow.event_number), 0) + 1).where(
                    RunEventRow.tenant_id == tenant_id,
                    RunEventRow.run_id == run_id,
                )
            )
        ).scalar_one()
        or 1
    )
    row = RunEventRow(
        tenant_id=tenant_id,
        run_id=run_id,
        audience=audience,
        event_number=int(next_event_number),
        ts=now,
        stage=stage,
        event_type=event_type,
        level=level,
        message=message,
        payload_json=payload_json or {},
    )
    session.add(row)

    if event_type == "stage_start" and stage:
        run.current_stage = stage
        run.updated_at = now

    await _touch_project_from_run(
        session=session, project_id=run.project_id, tenant_id=tenant_id, now=now
    )
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# Sync variant for orchestrator nodes (receive a sync sqlalchemy.orm.Session)
# ---------------------------------------------------------------------------

def append_run_event_sync(
    *,
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    level: RunEventLevelDb,
    message: str,
    audience: RunEventAudienceDb = RunEventAudienceDb.progress,
    stage: str | None = None,
    event_type: str = "log",
    payload_json: dict | None = None,
    allow_finished: bool = False,
) -> RunEventRow:
    """Synchronous counterpart of append_run_event for use inside sync orchestrator nodes."""
    from sqlalchemy.orm import Session  # noqa: F401 – used in type hint

    run = session.execute(
        select(RunRow).where(RunRow.tenant_id == tenant_id, RunRow.id == run_id)
    ).scalar_one_or_none()
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
        audience=audience,
        event_number=int(next_event_number),
        ts=now,
        stage=stage,
        event_type=event_type,
        level=level,
        message=message,
        payload_json=payload_json or {},
    )
    session.add(row)

    if event_type == "stage_start" and stage:
        run.current_stage = stage
        run.updated_at = now

    session.execute(
        update(ProjectRow)
        .where(ProjectRow.tenant_id == tenant_id, ProjectRow.id == run.project_id)
        .values(updated_at=now)
    )
    session.flush()
    return row


async def list_run_events(
    *,
    session: AsyncSession,
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
    return list((await session.execute(stmt)).scalars().all())


async def write_run_checkpoint(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    run_id: UUID,
    node_name: str,
    iteration_count: int = 0,
    state_payload: dict | None = None,
    summary_payload: dict | None = None,
    checkpoint_version: int = 1,
) -> RunCheckpointRow:
    row = RunCheckpointRow(
        tenant_id=tenant_id,
        run_id=run_id,
        checkpoint_version=checkpoint_version,
        node_name=node_name,
        iteration_count=iteration_count,
        stage=node_name,
        payload_json=state_payload or {},
        summary_json=summary_payload or {},
    )
    session.add(row)
    await session.flush()
    return row


async def _touch_project_from_run(
    *, session: AsyncSession, tenant_id: UUID, project_id: UUID, now: datetime
) -> None:
    await session.execute(
        update(ProjectRow)
        .where(ProjectRow.tenant_id == tenant_id, ProjectRow.id == project_id)
        .values(updated_at=now)
    )


def _record_status_transition(
    *,
    session: AsyncSession,
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


async def _table_exists(session: AsyncSession, table_name: str) -> bool:
    conn = await session.connection()
    if conn is None:
        return False
    engine_id = id(conn.engine)
    engine_cache = _table_existence_cache.setdefault(engine_id, {})
    if table_name in engine_cache:
        return engine_cache[table_name]
    result = await conn.run_sync(
        lambda sync_conn: sync_conn.dialect.has_table(sync_conn, table_name)
    )
    if result:
        engine_cache[table_name] = True
    return result


__all__ = [
    "append_run_event",
    "append_run_event_sync",
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
    "write_run_checkpoint",
    "patch_run_usage_metrics",
    "replace_run_budget_limits",
    "replace_run_usage_metrics",
]
