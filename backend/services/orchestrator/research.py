from __future__ import annotations

import asyncio
import json as _json
import logging
from uuid import UUID

from db.models.runs import RunRow
from db.repositories.project_runs import get_run_usage_metrics
from observability.context import bind
from runner import run_orchestrator
from sqlalchemy import select
from sqlalchemy.orm import Session

RESEARCH_JOB_TYPE = "research.run"

logger = logging.getLogger(__name__)


def process_research_run(*, session: Session, run_id: UUID, tenant_id: UUID) -> None:
    """Process a full research run using the LangGraph pipeline."""
    run = session.execute(
        select(RunRow).where(RunRow.id == run_id, RunRow.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if run is None:
        raise ValueError("run not found")

    inputs = get_run_usage_metrics(run)
    user_query = inputs.get("user_query") or inputs.get("prompt")
    research_goal = inputs.get("research_goal") or inputs.get("output_type")
    llm_provider = inputs.get("llm_provider")
    llm_model = inputs.get("llm_model")
    stage_models_raw = inputs.get("stage_models")
    stage_models: dict[str, str | None] | None = None
    if isinstance(stage_models_raw, str):
        try:
            stage_models = _json.loads(stage_models_raw)
        except (ValueError, TypeError):
            stage_models = None
    elif isinstance(stage_models_raw, dict):
        stage_models = stage_models_raw

    if not user_query:
        raise ValueError("run input missing user_query")

    bind(tenant_id=str(tenant_id), run_id=str(run_id))
    logger.info(
        "Starting research pipeline run",
        extra={
            "event": "pipeline.run.start",
            "run_id": str(run_id),
            "tenant_id": str(tenant_id),
            "user_query": user_query,
            "research_goal": research_goal,
            "llm_provider": llm_provider,
            "llm_model": llm_model,
            "stage_models": stage_models,
        },
    )
    try:
        logger.info(
            "Research pipeline invoking orchestrator",
            extra={
                "event": "pipeline.run.invoke",
                "run_id": str(run_id),
                "tenant_id": str(tenant_id),
            },
        )
        asyncio.run(
            run_orchestrator(
                session=session,
                tenant_id=tenant_id,
                run_id=run_id,
                user_query=user_query,
                research_goal=research_goal,
                llm_provider=llm_provider,
                llm_model=llm_model,
                stage_models=stage_models,
            )
        )
        logger.info(
            "Research pipeline run finished",
            extra={
                "event": "pipeline.run.finish",
                "run_id": str(run_id),
                "tenant_id": str(tenant_id),
            },
        )
    except Exception:
        logger.exception(
            "Research pipeline run failed",
            extra={
                "event": "pipeline.run.error",
                "run_id": str(run_id),
                "tenant_id": str(tenant_id),
            },
        )
        raise
