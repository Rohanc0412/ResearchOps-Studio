from __future__ import annotations

import os
import sys
import types
from uuid import UUID

import pytest
from app_services.project_runs import ACTIVE_RESEARCH_RUN_MESSAGE
from core.auth.config import get_auth_config
from core.settings import get_settings
from db.models.jobs import JobRow
from db.models.runs import RunRow, RunStatusDb
from db.repositories.project_runs import create_run
from db.session import session_scope
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.fixture()
def api_client(tmp_path):
    db_path = tmp_path / "project-runs.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["AUTH_REQUIRED"] = "false"
    os.environ["DEV_BYPASS_AUTH"] = "true"
    os.environ["LLM_PROVIDER"] = "none"
    sys.modules.setdefault(
        "bcrypt",
        types.SimpleNamespace(
            gensalt=lambda rounds=12: b"salt",
            hashpw=lambda password, salt: b"hash",
            checkpw=lambda password, hashed: True,
        ),
    )
    from app import create_app

    get_auth_config.cache_clear()
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        yield client, app


def _create_project(client: TestClient, name: str = "Concurrency Project") -> str:
    resp = client.post("/projects", json={"name": name})
    assert resp.status_code == 200
    return resp.json()["id"]


def _seed_running_run(app, project_id: str) -> None:
    SessionLocal = app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        create_run(
            session=session,
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            project_id=UUID(project_id),
            status=RunStatusDb.running,
            current_stage="retrieve",
            question="Existing active run",
            usage={"job_type": "research.run", "user_query": "Existing active run"},
        )


def test_project_run_is_blocked_when_another_research_run_is_active(api_client) -> None:
    client, app = api_client
    project_id = _create_project(client)
    _seed_running_run(app, project_id)

    resp = client.post(
        f"/projects/{project_id}/runs",
        json={"question": "Start a new research run"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "blocked"

    SessionLocal = app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        run = session.execute(
            select(RunRow)
            .where(RunRow.project_id == UUID(project_id), RunRow.question == "Start a new research run")
        ).scalar_one()
        assert run.status == RunStatusDb.blocked
        assert run.failure_reason == ACTIVE_RESEARCH_RUN_MESSAGE
        assert run.error_code == "research_run_active"
        job = session.execute(select(JobRow).where(JobRow.run_id == run.id)).scalar_one_or_none()
        assert job is None


def test_retry_blocked_run_stays_blocked_while_active_run_exists(api_client) -> None:
    client, app = api_client
    project_id = _create_project(client)
    _seed_running_run(app, project_id)

    blocked_resp = client.post(
        f"/projects/{project_id}/runs",
        json={"question": "Blocked until retry"},
    )
    blocked_run_id = blocked_resp.json()["run_id"]

    retry_resp = client.post(f"/runs/{blocked_run_id}/retry", json={})

    assert retry_resp.status_code == 200
    assert retry_resp.json()["status"] == "blocked"

    SessionLocal = app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        run = session.execute(select(RunRow).where(RunRow.id == UUID(blocked_run_id))).scalar_one()
        assert run.status == RunStatusDb.blocked
        assert run.retry_count == 0
        job = session.execute(select(JobRow).where(JobRow.run_id == run.id)).scalar_one_or_none()
        assert job is None


def test_retry_blocked_run_queues_once_active_run_has_finished(api_client) -> None:
    client, app = api_client
    project_id = _create_project(client)
    _seed_running_run(app, project_id)

    blocked_resp = client.post(
        f"/projects/{project_id}/runs",
        json={"question": "Retry me later"},
    )
    blocked_run_id = blocked_resp.json()["run_id"]

    SessionLocal = app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        active = session.execute(
            select(RunRow).where(RunRow.project_id == UUID(project_id), RunRow.status == RunStatusDb.running)
        ).scalar_one()
        active.status = RunStatusDb.succeeded
        active.finished_at = active.updated_at
        active.current_stage = "export"
        session.flush()

    retry_resp = client.post(f"/runs/{blocked_run_id}/retry", json={})

    assert retry_resp.status_code == 200
    assert retry_resp.json()["status"] == "queued"

    with session_scope(SessionLocal) as session:
        run = session.execute(select(RunRow).where(RunRow.id == UUID(blocked_run_id))).scalar_one()
        assert run.status == RunStatusDb.queued
        assert run.retry_count == 1
        job = session.execute(select(JobRow).where(JobRow.run_id == run.id)).scalar_one_or_none()
        assert job is not None
