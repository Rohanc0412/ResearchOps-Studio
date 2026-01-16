from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from db.init_db import init_db
from db.models import ArtifactRow, JobRow, RunRow
from db.models.jobs import JobStatusDb
from db.models.runs import RunStatusDb
from db.session import create_sessionmaker
from researchops_orchestrator.hello import enqueue_hello_run, process_hello_run


def test_orchestrator_hello_creates_artifact(sqlite_engine) -> None:
    init_db(sqlite_engine)
    SessionLocal = create_sessionmaker(sqlite_engine)

    with SessionLocal() as session:
        run_id = enqueue_hello_run(session=session, tenant_id="tenant_test")
        session.commit()

    with SessionLocal() as session:
        process_hello_run(session=session, run_id=run_id, tenant_id="tenant_test")
        session.commit()

    with SessionLocal() as session:
        run = session.execute(select(RunRow).where(RunRow.id == run_id)).scalar_one()
        assert run.status == RunStatusDb.succeeded
        artifacts = session.execute(select(ArtifactRow).where(ArtifactRow.run_id == run_id)).scalars().all()
        assert len(artifacts) == 1
        assert artifacts[0].artifact_type == "hello"
        assert artifacts[0].payload_json["message"] == "hello"

