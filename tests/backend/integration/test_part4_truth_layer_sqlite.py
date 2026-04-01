from __future__ import annotations

from uuid import UUID

import pytest
from db.models.base import Base
from db.models.run_events import RunEventLevelDb
from db.repositories.project_runs import append_run_event, create_project, create_run, list_projects
from db.session import create_sessionmaker, session_scope


async def _init_sqlite(engine) -> None:
    """Initialize SQLite schema for tests using async engine."""
    import db.models  # noqa: F401 - registers all models

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.mark.asyncio
async def test_part4_truth_layer_updates_project_last_activity(sqlite_engine) -> None:
    await _init_sqlite(sqlite_engine)
    SessionLocal = create_sessionmaker(sqlite_engine)

    tenant_id = UUID("00000000-0000-0000-0000-00000000abcd")

    async with session_scope(SessionLocal) as session:
        project = await create_project(
            session=session,
            tenant_id=tenant_id,
            name="Project A",
            description=None,
            created_by="user_1",
        )
        run = await create_run(session=session, tenant_id=tenant_id, project_id=project.id)
        await append_run_event(
            session=session,
            tenant_id=tenant_id,
            run_id=run.id,
            level=RunEventLevelDb.info,
            message="stage started",
            stage="stage_1",
        )

    async with session_scope(SessionLocal) as session:
        projects = await list_projects(session=session, tenant_id=tenant_id)
        assert len(projects) == 1
        assert projects[0].last_run_id is not None
        assert projects[0].last_activity_at is not None
        assert projects[0].last_activity_at >= projects[0].created_at
