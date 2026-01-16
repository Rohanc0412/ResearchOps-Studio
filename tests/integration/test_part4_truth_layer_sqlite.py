from __future__ import annotations

from uuid import UUID

from db.init_db import init_db
from db.models.run_events import RunEventLevelDb
from db.services.truth import append_run_event, create_project, create_run, list_projects
from db.session import create_sessionmaker, session_scope


def test_part4_truth_layer_updates_project_last_activity(sqlite_engine) -> None:
    init_db(sqlite_engine)
    SessionLocal = create_sessionmaker(sqlite_engine)

    tenant_id = UUID("00000000-0000-0000-0000-00000000abcd")

    with session_scope(SessionLocal) as session:
        project = create_project(
            session=session,
            tenant_id=tenant_id,
            name="Project A",
            description=None,
            created_by="user_1",
        )
        run = create_run(session=session, tenant_id=tenant_id, project_id=project.id)
        append_run_event(
            session=session,
            tenant_id=tenant_id,
            run_id=run.id,
            level=RunEventLevelDb.info,
            message="stage started",
            stage="stage_1",
        )

    with session_scope(SessionLocal) as session:
        projects = list_projects(session=session, tenant_id=tenant_id)
        assert len(projects) == 1
        assert projects[0].last_run_id is not None
        assert projects[0].last_activity_at is not None
        assert projects[0].last_activity_at >= projects[0].created_at
