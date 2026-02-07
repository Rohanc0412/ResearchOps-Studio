from __future__ import annotations

from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from db.models.base import Base
from db.models.projects import ProjectRow
from db.models.runs import RunRow, RunStatusDb
from db.services.truth import (
    create_project,
    create_run,
    get_project_for_user,
    get_run_for_user,
    list_projects_for_user,
)


def test_project_and_run_visibility_is_scoped_to_creator() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[ProjectRow.__table__, RunRow.__table__])

    SessionLocal = sessionmaker(bind=engine, future=True)
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")

    with SessionLocal() as session:  # type: Session
        p_u1 = create_project(
            session=session,
            tenant_id=tenant_id,
            name="u1 project",
            description=None,
            created_by="user-1",
        )
        p_u2 = create_project(
            session=session,
            tenant_id=tenant_id,
            name="u2 project",
            description=None,
            created_by="user-2",
        )

        r_u1 = create_run(session=session, tenant_id=tenant_id, project_id=p_u1.id, status=RunStatusDb.queued)
        r_u2 = create_run(session=session, tenant_id=tenant_id, project_id=p_u2.id, status=RunStatusDb.queued)
        session.commit()

        rows = list_projects_for_user(session=session, tenant_id=tenant_id, created_by="user-1", limit=200)
        assert [r.id for r in rows] == [p_u1.id]

        assert (
            get_project_for_user(
                session=session,
                tenant_id=tenant_id,
                project_id=p_u1.id,
                created_by="user-1",
            )
            is not None
        )
        assert (
            get_project_for_user(
                session=session,
                tenant_id=tenant_id,
                project_id=p_u2.id,
                created_by="user-1",
            )
            is None
        )

        assert (
            get_run_for_user(
                session=session,
                tenant_id=tenant_id,
                run_id=r_u1.id,
                created_by="user-1",
            )
            is not None
        )
        assert (
            get_run_for_user(
                session=session,
                tenant_id=tenant_id,
                run_id=r_u2.id,
                created_by="user-1",
            )
            is None
        )

