from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.runs import RunRow
from researchops_orchestrator.runner import run_orchestrator


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
