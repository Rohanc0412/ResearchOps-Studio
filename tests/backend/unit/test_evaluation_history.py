from __future__ import annotations

import asyncio
import os
import sys
import types
from uuid import UUID

import pytest
from db.models.run_sections import RunSectionRow
from db.models.section_reviews import SectionReviewRow
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
            verdict="fail",
            grounding_score=45,
            issues=[{"sentence_index": 0, "problem": "unsupported", "notes": "Missing evidence", "citations": []}],
        )
        await record_evaluation_section_result(
            session=session,
            tenant_id=tenant_id,
            evaluation_pass_id=pass_one.id,
            section_id="results",
            section_title="Results",
            section_order=2,
            verdict="pass",
            grounding_score=88,
            issues=[],
        )
        await finalize_evaluation_pass(
            session=session,
            tenant_id=tenant_id,
            evaluation_pass_id=pass_one.id,
            grounding_pct=67,
            sections_passed=1,
            sections_total=2,
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
            verdict="pass",
            grounding_score=85,
            issues=[],
        )
        await record_evaluation_section_result(
            session=session,
            tenant_id=tenant_id,
            evaluation_pass_id=pass_two.id,
            section_id="results",
            section_title="Results",
            section_order=2,
            verdict="pass",
            grounding_score=92,
            issues=[],
        )
        await finalize_evaluation_pass(
            session=session,
            tenant_id=tenant_id,
            evaluation_pass_id=pass_two.id,
            grounding_pct=89,
            sections_passed=2,
            sections_total=2,
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
        assert history[0]["sections_passed"] == 2
        assert history[1]["pass_index"] == 1
        assert history[1]["sections_passed"] == 1
        assert history[1]["sections"][0]["verdict"] == "fail"

    await engine.dispose()


@pytest.fixture()
def api_client(tmp_path):
    from app import create_app

    os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
    os.environ["AUTH_REQUIRED"] = "false"
    os.environ["DEV_BYPASS_AUTH"] = "true"
    app = create_app()
    with TestClient(app) as client:
        yield client, app


def test_get_evaluation_returns_pipeline_history_without_manual_eval_status(api_client) -> None:
    from db.models.runs import RunStatusDb

    client, app = api_client
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    SessionLocal = app.state.SessionLocal

    async def _setup():
        async with session_scope(SessionLocal) as session:
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

            latest_review_intro = SectionReviewRow(
                tenant_id=tenant_id,
                run_id=run.id,
                section_id="intro",
                verdict="pass",
            )
            latest_review_intro.issues_json = []
            latest_review_results = SectionReviewRow(
                tenant_id=tenant_id,
                run_id=run.id,
                section_id="results",
                verdict="pass",
            )
            latest_review_results.issues_json = []
            session.add_all([latest_review_intro, latest_review_results])

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
                verdict="fail",
                grounding_score=45,
                issues=[{"sentence_index": 0, "problem": "unsupported", "notes": "Missing evidence", "citations": []}],
            )
            await record_evaluation_section_result(
                session=session,
                tenant_id=tenant_id,
                evaluation_pass_id=pass_one.id,
                section_id="results",
                section_title="Results",
                section_order=2,
                verdict="pass",
                grounding_score=88,
                issues=[],
            )
            await finalize_evaluation_pass(
                session=session,
                tenant_id=tenant_id,
                evaluation_pass_id=pass_one.id,
                grounding_pct=67,
                sections_passed=1,
                sections_total=2,
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
                verdict="pass",
                grounding_score=85,
                issues=[],
            )
            await record_evaluation_section_result(
                session=session,
                tenant_id=tenant_id,
                evaluation_pass_id=pass_two.id,
                section_id="results",
                section_title="Results",
                section_order=2,
                verdict="pass",
                grounding_score=92,
                issues=[],
            )
            await finalize_evaluation_pass(
                session=session,
                tenant_id=tenant_id,
                evaluation_pass_id=pass_two.id,
                grounding_pct=89,
                faithfulness_pct=93,
                sections_passed=2,
                sections_total=2,
                issues_by_type={},
            )
            patch_run_usage_metrics(run, {"eval_sections_passed": 2, "eval_sections_total": 2})
            return str(run.id)

    run_id = asyncio.run(_setup())

    response = client.get(f"/runs/{run_id}/evaluation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "complete"
    assert payload["grounding_pct"] == 89
    assert payload["faithfulness_pct"] == 93
    assert payload["sections_passed"] == 2
    assert payload["sections_total"] == 2
    assert len(payload["history"]) == 2
    assert payload["history"][0]["pass_index"] == 2
    assert payload["history"][1]["pass_index"] == 1
    assert payload["history"][1]["sections_passed"] == 1
    assert payload["history"][1]["sections"][0]["verdict"] == "fail"


def test_get_evaluation_includes_running_pass_history(api_client) -> None:
    from db.models.runs import RunStatusDb

    client, app = api_client
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    SessionLocal = app.state.SessionLocal

    async def _setup():
        async with session_scope(SessionLocal) as session:
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
                verdict="fail",
                grounding_score=72,
                issues=[{"sentence_index": 0, "problem": "unsupported", "notes": "Still checking", "citations": []}],
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
    assert payload["history"][0]["sections"][0]["grounding_score"] == 72
    assert payload["sections"][0]["grounding_score"] == 72
