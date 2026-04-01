from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from db.models.projects import ProjectRow
from db.models.runs import RunRow, RunStatusDb
from db.repositories.project_runs import (
    create_project,
    create_run,
    get_project_for_user,
    get_run_for_user,
    list_projects_for_user,
)

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/researchops_test",
)
_TEST_ASYNC_DATABASE_URL = _TEST_DATABASE_URL.replace(
    "postgresql+psycopg://", "postgresql+asyncpg://"
)


@pytest.mark.asyncio
async def test_project_and_run_visibility_is_scoped_to_creator() -> None:
    import db.models  # noqa: F401 — registers all models with Base.metadata
    from db.init_db import init_db as _init_db

    engine = create_async_engine(_TEST_ASYNC_DATABASE_URL, future=True)
    await _init_db(engine)

    AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")

    async with AsyncSessionLocal() as session:
        p_u1 = await create_project(
            session=session,
            tenant_id=tenant_id,
            name="u1 project",
            description=None,
            created_by="user-1",
        )
        p_u2 = await create_project(
            session=session,
            tenant_id=tenant_id,
            name="u2 project",
            description=None,
            created_by="user-2",
        )

        r_u1 = await create_run(session=session, tenant_id=tenant_id, project_id=p_u1.id, status=RunStatusDb.queued)
        r_u2 = await create_run(session=session, tenant_id=tenant_id, project_id=p_u2.id, status=RunStatusDb.queued)
        await session.commit()

        rows = await list_projects_for_user(session=session, tenant_id=tenant_id, created_by="user-1", limit=200)
        assert [r.id for r in rows] == [p_u1.id]

        assert (
            await get_project_for_user(
                session=session,
                tenant_id=tenant_id,
                project_id=p_u1.id,
                created_by="user-1",
            )
            is not None
        )
        assert (
            await get_project_for_user(
                session=session,
                tenant_id=tenant_id,
                project_id=p_u2.id,
                created_by="user-1",
            )
            is None
        )

        assert (
            await get_run_for_user(
                session=session,
                tenant_id=tenant_id,
                run_id=r_u1.id,
                created_by="user-1",
            )
            is not None
        )
        assert (
            await get_run_for_user(
                session=session,
                tenant_id=tenant_id,
                run_id=r_u2.id,
                created_by="user-1",
            )
            is None
        )

    await engine.dispose()
