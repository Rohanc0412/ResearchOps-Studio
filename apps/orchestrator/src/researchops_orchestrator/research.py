from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.runs import RunRow
from researchops_orchestrator.runner import run_orchestrator

logger = logging.getLogger(__name__)

RESEARCH_JOB_TYPE = "research.run"


def process_research_run(*, session: Session, run_id: UUID, tenant_id: UUID) -> None:
    """Process a full research run using the LangGraph pipeline."""
    run = session.execute(
        select(RunRow).where(RunRow.id == run_id, RunRow.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if run is None:
        raise ValueError("run not found")

    inputs = run.usage_json or {}
    user_query = inputs.get("user_query") or inputs.get("prompt")
    research_goal = inputs.get("research_goal") or inputs.get("output_type")
    llm_provider = inputs.get("llm_provider")
    llm_model = inputs.get("llm_model")

    if not user_query:
        raise ValueError("run input missing user_query")

    logger.info(
        "research_run_start",
        extra={
            "run_id": str(run_id),
            "tenant_id": str(tenant_id),
            "llm_provider": llm_provider,
            "llm_model": llm_model,
        },
    )

    print(f"\n  {'━'*56}")
    print(f"  RESEARCH PIPELINE STARTING")
    print(f"  {'━'*56}")
    print(f"  Query: {user_query[:70]}{'...' if len(user_query) > 70 else ''}")
    print(f"  Goal:  {research_goal}")
    print(f"  LLM:   {llm_provider}/{llm_model}")
    print(f"  {'━'*56}\n")

    asyncio.run(
        run_orchestrator(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
            user_query=user_query,
            research_goal=research_goal,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
    )

    print(f"\n  {'━'*56}")
    print(f"  RESEARCH PIPELINE COMPLETE")
    print(f"  {'━'*56}\n")
    logger.info("research_run_complete", extra={"run_id": str(run_id), "tenant_id": str(tenant_id)})
