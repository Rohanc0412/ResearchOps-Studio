from __future__ import annotations

import asyncio
import os
import sys
import types
from contextlib import asynccontextmanager
from uuid import UUID

import pytest
from db.models.run_sections import RunSectionRow
from db.repositories.evaluation_history import (
    create_evaluation_pass,
    finalize_evaluation_pass,
    list_evaluation_pass_history,
    record_evaluation_section_result,
)
from db.repositories.project_runs import create_project, create_run, patch_run_usage_metrics
from db.session import session_scope
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.modules.setdefault(
    "bcrypt",
    types.SimpleNamespace(
        gensalt=lambda rounds=12: b"salt",
        hashpw=lambda password, salt: b"hash",
        checkpw=lambda password, hashed: True,
    ),
)

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/researchops_test",
)
_TEST_ASYNC_DATABASE_URL = _TEST_DATABASE_URL.replace(
    "postgresql+psycopg://", "postgresql+asyncpg://"
)


@asynccontextmanager
async def _fresh_session_scope():
    engine = create_async_engine(_TEST_ASYNC_DATABASE_URL, future=True)
    session_local = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        async with session_scope(session_local) as session:
            yield session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_evaluation_history_is_append_only_across_passes() -> None:
    from db.init_db import init_db as _init_db
    from db.models.runs import RunStatusDb

    engine = create_async_engine(_TEST_ASYNC_DATABASE_URL, future=True)
    await _init_db(engine)
    AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")

    async with AsyncSessionLocal() as session:
        project = await create_project(
            session=session,
            tenant_id=tenant_id,
            name="Eval History",
            description=None,
            created_by="user-1",
        )
        run = await create_run(
            session=session,
            tenant_id=tenant_id,
            project_id=project.id,
            status=RunStatusDb.succeeded,
            question="Why did evaluation change?",
        )

        pass_one = await create_evaluation_pass(
            session=session,
            tenant_id=tenant_id,
            run_id=run.id,
            scope="pipeline",
        )
        await record_evaluation_section_result(
            session=session,
            tenant_id=tenant_id,
            evaluation_pass_id=pass_one.id,
            section_id="intro",
            section_title="Introduction",
            section_order=1,
            quality_score=45,
            claims=[{"claim_index": 0, "claim_text": "AI is used widely.", "verdict": "unsupported", "citations": [], "notes": "Missing evidence"}],
        )
        await record_evaluation_section_result(
            session=session,
            tenant_id=tenant_id,
            evaluation_pass_id=pass_one.id,
            section_id="results",
            section_title="Results",
            section_order=2,
            quality_score=88,
            claims=[],
        )
        await finalize_evaluation_pass(
            session=session,
            tenant_id=tenant_id,
            evaluation_pass_id=pass_one.id,
            quality_pct=67,
            hallucination_rate=20,
            issues_by_type={"unsupported": 1},
        )

        pass_two = await create_evaluation_pass(
            session=session,
            tenant_id=tenant_id,
            run_id=run.id,
            scope="pipeline",
        )
        await record_evaluation_section_result(
            session=session,
            tenant_id=tenant_id,
            evaluation_pass_id=pass_two.id,
            section_id="intro",
            section_title="Introduction",
            section_order=1,
            quality_score=85,
            claims=[],
        )
        await record_evaluation_section_result(
            session=session,
            tenant_id=tenant_id,
            evaluation_pass_id=pass_two.id,
            section_id="results",
            section_title="Results",
            section_order=2,
            quality_score=92,
            claims=[],
        )
        await finalize_evaluation_pass(
            session=session,
            tenant_id=tenant_id,
            evaluation_pass_id=pass_two.id,
            quality_pct=89,
            hallucination_rate=5,
            issues_by_type={},
        )
        await session.commit()

        history = await list_evaluation_pass_history(
            session=session,
            tenant_id=tenant_id,
            run_id=run.id,
        )

        assert len(history) == 2
        assert history[0]["pass_index"] == 2
        assert history[0]["quality_pct"] == 89
        assert history[1]["pass_index"] == 1
        assert history[1]["quality_pct"] == 67
        assert history[1]["sections"][0]["quality_score"] == 45

    await engine.dispose()


@pytest.fixture()
def api_client(tmp_path):
    from app import create_app
    from core.auth.config import get_auth_config
    from core.settings import get_settings

    os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
    os.environ["AUTH_REQUIRED"] = "false"
    os.environ["DEV_BYPASS_AUTH"] = "true"
    get_auth_config.cache_clear()
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        yield client, app


def test_get_evaluation_returns_pipeline_history_without_manual_eval_status(api_client) -> None:
    from db.models.runs import RunStatusDb

    client, _ = api_client
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")

    async def _setup():
        async with _fresh_session_scope() as session:
            project = await create_project(
                session=session,
                tenant_id=tenant_id,
                name="Artifacts Eval History",
                description=None,
                created_by="dev-user",
            )
            run = await create_run(
                session=session,
                tenant_id=tenant_id,
                project_id=project.id,
                status=RunStatusDb.succeeded,
                question="Explain evaluation history",
            )
            session.add_all(
                [
                    RunSectionRow(
                        tenant_id=tenant_id,
                        run_id=run.id,
                        section_id="intro",
                        title="Introduction",
                        goal="Intro",
                        section_order=1,
                    ),
                    RunSectionRow(
                        tenant_id=tenant_id,
                        run_id=run.id,
                        section_id="results",
                        title="Results",
                        goal="Results",
                        section_order=2,
                    ),
                ]
            )

            pass_one = await create_evaluation_pass(
                session=session,
                tenant_id=tenant_id,
                run_id=run.id,
                scope="pipeline",
            )
            await record_evaluation_section_result(
                session=session,
                tenant_id=tenant_id,
                evaluation_pass_id=pass_one.id,
                section_id="intro",
                section_title="Introduction",
                section_order=1,
                quality_score=45,
                claims=[{"claim_index": 0, "claim_text": "AI is widely used.", "verdict": "unsupported", "citations": [], "notes": "Missing evidence"}],
            )
            await record_evaluation_section_result(
                session=session,
                tenant_id=tenant_id,
                evaluation_pass_id=pass_one.id,
                section_id="results",
                section_title="Results",
                section_order=2,
                quality_score=88,
                claims=[],
            )
            await finalize_evaluation_pass(
                session=session,
                tenant_id=tenant_id,
                evaluation_pass_id=pass_one.id,
                quality_pct=67,
                hallucination_rate=20,
                issues_by_type={"unsupported": 1},
            )

            pass_two = await create_evaluation_pass(
                session=session,
                tenant_id=tenant_id,
                run_id=run.id,
                scope="pipeline",
            )
            await record_evaluation_section_result(
                session=session,
                tenant_id=tenant_id,
                evaluation_pass_id=pass_two.id,
                section_id="intro",
                section_title="Introduction",
                section_order=1,
                quality_score=85,
                claims=[],
            )
            await record_evaluation_section_result(
                session=session,
                tenant_id=tenant_id,
                evaluation_pass_id=pass_two.id,
                section_id="results",
                section_title="Results",
                section_order=2,
                quality_score=92,
                claims=[],
            )
            await finalize_evaluation_pass(
                session=session,
                tenant_id=tenant_id,
                evaluation_pass_id=pass_two.id,
                quality_pct=89,
                hallucination_rate=5,
                issues_by_type={},
            )
            patch_run_usage_metrics(run, {"eval_quality_pct": 89, "eval_hallucination_rate": 5})
            return str(run.id)

    run_id = asyncio.run(_setup())

    response = client.get(f"/runs/{run_id}/evaluation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "complete"
    assert payload["quality_pct"] == 89
    assert payload["hallucination_rate"] == 5
    assert len(payload["history"]) == 2
    assert payload["history"][0]["pass_index"] == 2
    assert payload["history"][1]["pass_index"] == 1
    assert payload["history"][1]["quality_pct"] == 67
    assert payload["history"][1]["sections"][0]["quality_score"] == 45


def test_get_evaluation_includes_running_pass_history(api_client) -> None:
    from db.models.runs import RunStatusDb

    client, _ = api_client
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")

    async def _setup():
        async with _fresh_session_scope() as session:
            project = await create_project(
                session=session,
                tenant_id=tenant_id,
                name="Running Eval History",
                description=None,
                created_by="dev-user",
            )
            run = await create_run(
                session=session,
                tenant_id=tenant_id,
                project_id=project.id,
                status=RunStatusDb.succeeded,
                question="Show the active evaluation pass",
            )
            session.add(
                RunSectionRow(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    section_id="intro",
                    title="Introduction",
                    goal="Intro",
                    section_order=1,
                )
            )

            running_pass = await create_evaluation_pass(
                session=session,
                tenant_id=tenant_id,
                run_id=run.id,
                scope="manual",
            )
            await record_evaluation_section_result(
                session=session,
                tenant_id=tenant_id,
                evaluation_pass_id=running_pass.id,
                section_id="intro",
                section_title="Introduction",
                section_order=1,
                quality_score=72,
                claims=[{"claim_index": 0, "claim_text": "AI helps.", "verdict": "supported", "citations": [], "notes": ""}],
            )
            patch_run_usage_metrics(run, {"eval_status": "running"})
            return str(run.id)

    run_id = asyncio.run(_setup())

    response = client.get(f"/runs/{run_id}/evaluation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "running"
    assert len(payload["history"]) == 1
    assert payload["history"][0]["status"] == "running"
    assert payload["history"][0]["scope"] == "manual"
    assert payload["history"][0]["sections"][0]["quality_score"] == 72
