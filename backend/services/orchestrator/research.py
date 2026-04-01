from __future__ import annotations

import json as _json
import logging
from uuid import UUID

from db.repositories.project_runs import get_run, get_run_usage_metrics
from embeddings import (
    get_embed_worker_pool,
    resolve_embed_device,
    resolve_embed_dtype,
    resolve_embed_max_seq_len,
    resolve_embed_model,
    resolve_embed_normalize,
    resolve_embed_provider,
    resolve_embed_trust_remote_code,
    resolve_embed_workers,
)
from observability.context import bind
from runner import run_orchestrator
from sqlalchemy.ext.asyncio import AsyncSession

RESEARCH_JOB_TYPE = "research.run"

logger = logging.getLogger(__name__)


def _warm_local_embed_pool(*, llm_provider: str | None) -> None:
    provider = resolve_embed_provider(llm_provider)
    if provider not in {"local", "sentence-transformers", "bge"}:
        return

    workers = resolve_embed_workers()
    if workers <= 1:
        return

    device = resolve_embed_device()
    model_name = resolve_embed_model(provider)
    get_embed_worker_pool(
        model_name=model_name,
        device=device,
        normalize_embeddings=resolve_embed_normalize(),
        max_seq_length=resolve_embed_max_seq_len(),
        dtype=resolve_embed_dtype(device),
        trust_remote_code=resolve_embed_trust_remote_code(model_name),
        n_workers=workers,
        preloaded_model=None,
    )
    logger.info(
        "Research embed worker pool warmed",
        extra={
            "event": "pipeline.embed_pool.ready",
            "provider": provider,
            "model_name": model_name,
            "device": device,
            "workers": workers,
        },
    )


async def process_research_run(*, session: AsyncSession, run_id: UUID, tenant_id: UUID) -> None:
    """Process a full research run using the LangGraph pipeline."""
    run = await get_run(session=session, tenant_id=tenant_id, run_id=run_id)
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
        _warm_local_embed_pool(llm_provider=llm_provider)
        logger.info(
            "Research pipeline invoking orchestrator",
            extra={
                "event": "pipeline.run.invoke",
                "run_id": str(run_id),
                "tenant_id": str(tenant_id),
            },
        )
        await run_orchestrator(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
            user_query=user_query,
            research_goal=research_goal,
            llm_provider=llm_provider,
            llm_model=llm_model,
            stage_models=stage_models,
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
