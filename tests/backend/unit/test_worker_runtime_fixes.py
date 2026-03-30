from __future__ import annotations

import os
import sys
import types
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.modules.setdefault(
    "bcrypt",
    types.SimpleNamespace(
        gensalt=lambda rounds=12: b"salt",
        hashpw=lambda password, salt: b"hash",
        checkpw=lambda password, hashed: True,
    ),
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend", "data"))

import db.models  # noqa: F401
from db.models.jobs import JobRow, JobStatusDb
from db.models.projects import ProjectRow
from db.models.run_events import RunEventLevelDb
from db.models.runs import RunRow, RunStatusDb
from db.models.roles import RoleRow
from db.models.base import Base
from services.workers import main as worker_main
from libs.core.pipeline_events import events as pipeline_events


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)
    db = Session()
    for name in ("owner", "admin", "researcher", "viewer"):
        db.add(RoleRow(name=name, description=f"Built-in {name}"))
    db.flush()
    try:
        yield db
    finally:
        db.close()


def _make_project(session):
    tenant_id = uuid4()
    project = ProjectRow(tenant_id=tenant_id, name=f"proj-{uuid4()}", created_by="tester")
    session.add(project)
    session.flush()
    return tenant_id, project


def test_recover_orphaned_jobs_marks_running_jobs_and_runs_failed(session):
    tenant_id, project = _make_project(session)
    run = RunRow(
        tenant_id=tenant_id,
        project_id=project.id,
        status=RunStatusDb.running,
        current_stage="retrieve",
        question="stuck run",
    )
    session.add(run)
    session.flush()
    job = JobRow(
        tenant_id=tenant_id,
        run_id=run.id,
        job_type="research.run",
        status=JobStatusDb.running,
        attempts=1,
    )
    session.add(job)
    session.flush()

    recovered = worker_main.recover_orphaned_jobs(session)
    session.flush()

    refreshed_run = session.execute(select(RunRow).where(RunRow.id == run.id)).scalar_one()
    refreshed_job = session.execute(select(JobRow).where(JobRow.id == job.id)).scalar_one()

    assert recovered == 1
    assert refreshed_job.status == JobStatusDb.failed
    assert refreshed_job.last_error is not None
    assert "orphaned" in refreshed_job.last_error.lower()
    assert refreshed_run.status == RunStatusDb.failed
    assert refreshed_run.error_code == "stale_running_recovered"
    assert refreshed_run.failure_reason is not None
    assert "orphaned" in refreshed_run.failure_reason.lower()


def test_stage_start_event_updates_run_current_stage(session):
    tenant_id, project = _make_project(session)
    run = RunRow(
        tenant_id=tenant_id,
        project_id=project.id,
        status=RunStatusDb.running,
        current_stage="retrieve",
        question="advance stages",
    )
    session.add(run)
    session.flush()

    pipeline_events.emit_run_event(
        session=session,
        tenant_id=tenant_id,
        run_id=run.id,
        event_type="stage_start",
        stage="outline",
        message="Starting stage: outline",
        data={"iteration": 0},
    )
    session.flush()

    refreshed_run = session.execute(select(RunRow).where(RunRow.id == run.id)).scalar_one()
    assert refreshed_run.current_stage == "outline"

