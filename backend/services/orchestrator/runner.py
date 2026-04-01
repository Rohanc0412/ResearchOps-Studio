"""
Runner for executing the orchestrator graph.

Integrates with the run lifecycle and emits SSE events.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from checkpoints import PostgresCheckpointSaver
from core.env import env_int
from observability import langfuse_enabled
from core.orchestrator.state import OrchestratorState
from core.runs.lifecycle import transition_run_status_async
from db.models.runs import RunRow, RunStatusDb
from db.repositories.artifacts import create_artifact, list_artifacts
from graph import RunCancelledError, create_orchestrator_graph
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _guess_mime_type(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".md"):
        return "text/markdown"
    if lower.endswith(".json"):
        return "application/json"
    return "text/plain"


def _normalize_artifact_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return json.dumps(content, indent=2, default=str)


def _artifact_metadata(name: str, text: str) -> dict:
    metadata: dict[str, object] = {"filename": name}
    lower = name.lower()
    if lower.endswith(".md"):
        metadata["markdown"] = text
    elif lower.endswith(".json"):
        try:
            metadata["json"] = json.loads(text)
        except json.JSONDecodeError:
            metadata["content"] = text
    else:
        metadata["content"] = text
    return metadata


async def _persist_artifacts(session: AsyncSession, run_row: RunRow, artifacts: dict[str, object]) -> int:
    if not artifacts:
        return 0

    existing = await list_artifacts(
        session=session, tenant_id=run_row.tenant_id, run_id=run_row.id, limit=1
    )
    if existing:
        return 0

    created = 0
    for name, content in artifacts.items():
        if content is None:
            continue
        text = _normalize_artifact_content(content)
        mime_type = _guess_mime_type(name)
        metadata = _artifact_metadata(name, text)
        size_bytes = len(text.encode("utf-8"))
        await create_artifact(
            session=session,
            tenant_id=run_row.tenant_id,
            project_id=run_row.project_id,
            run_id=run_row.id,
            artifact_type=name,
            blob_ref=f"inline://runs/{run_row.id}/{name}",
            mime_type=mime_type,
            size_bytes=size_bytes,
            metadata_json=metadata,
        )
        created += 1

    return created


async def run_orchestrator(
    session: AsyncSession,
    tenant_id: UUID,
    run_id: UUID,
    user_query: str,
    research_goal: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    stage_models: dict[str, str | None] | None = None,
    max_iterations: int = 5,
) -> OrchestratorState:
    """
    Execute the orchestrator graph for a run.

    Args:
        session: Database session
        tenant_id: Tenant ID
        run_id: Run ID
        user_query: User's research query
        research_goal: Optional research goal
        max_iterations: Maximum iterations (default: 5)

    Returns:
        Final orchestrator state

    Raises:
        Exception: If graph execution fails
    """
    # Transition run to running
    await transition_run_status_async(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        to_status=RunStatusDb.running,
        current_stage="retrieve",
    )
    await session.commit()
    logger.info(
        "Run transitioned to running",
        extra={
            "event": "pipeline.run.transitioned",
            "run_id": str(run_id),
            "tenant_id": str(tenant_id),
            "current_stage": "retrieve",
        },
    )

    if langfuse_enabled():
        try:
            from langfuse.decorators import langfuse_context
            langfuse_context.update_current_trace(
                name="research_run",
                id=str(run_id),
                metadata={
                    "tenant_id": str(tenant_id),
                    "query": user_query,
                    "llm_provider": llm_provider,
                    "llm_model": llm_model,
                },
            )
        except Exception:
            pass  # Never fail the pipeline due to observability

    max_iterations = env_int("ORCHESTRATOR_MAX_ITERATIONS", max_iterations, min_value=1)

    # Initialize state
    initial_state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query=user_query,
        research_goal=research_goal,
        llm_provider=llm_provider,
        llm_model=llm_model,
        stage_models=stage_models or {},
        max_iterations=max_iterations,
        started_at=datetime.now(UTC),
    )

    # Extract sync session proxy for synchronous graph execution
    sync_session = session.sync_session

    # Create checkpoint saver
    checkpoint_saver = PostgresCheckpointSaver(
        session=sync_session, tenant_id=tenant_id, run_id=run_id
    )
    logger.info(
        "Checkpoint saver initialized",
        extra={
            "event": "pipeline.run.checkpoint_init",
            "run_id": str(run_id),
            "tenant_id": str(tenant_id),
            "checkpoint_saver": checkpoint_saver.__class__.__name__,
        },
    )

    # Create graph
    graph = create_orchestrator_graph(sync_session)
    logger.info(
        "Orchestrator graph compiled",
        extra={
            "event": "pipeline.run.graph_ready",
            "run_id": str(run_id),
            "tenant_id": str(tenant_id),
        },
    )

    # Configure graph execution
    config = {
        "configurable": {
            "thread_id": str(run_id),
            "checkpoint_ns": "orchestrator",
        },
        "recursion_limit": max_iterations * 20,  # Allow plenty of steps
    }

    try:
        logger.info(
            "Invoking orchestrator graph",
            extra={
                "event": "pipeline.run.graph_invoke",
                "run_id": str(run_id),
                "tenant_id": str(tenant_id),
            },
        )
        # Execute graph (synchronous for now, can be made async)
        final_state_dict = graph.invoke(initial_state.dict(), config=config)
        logger.info(
            "Orchestrator graph returned",
            extra={
                "event": "pipeline.run.graph_return",
                "run_id": str(run_id),
                "tenant_id": str(tenant_id),
            },
        )

        # Convert back to OrchestratorState
        final_state = OrchestratorState(**final_state_dict)

        # Mark completion time
        final_state.completed_at = datetime.now(UTC)

        # Update run status
        await session.execute(
            update(RunRow)
            .where(RunRow.id == run_id)
            .values(current_stage="export", updated_at=datetime.now(UTC))
        )
        run_row = (await session.execute(
            select(RunRow).where(RunRow.id == run_id)
        )).scalar_one_or_none()
        if run_row:
            await _persist_artifacts(session, run_row, final_state.artifacts or {})

        # Transition to succeeded
        await transition_run_status_async(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
            to_status=RunStatusDb.succeeded,
            current_stage="export",
        )

        await session.commit()

        return final_state

    except RunCancelledError:
        await session.rollback()
        await transition_run_status_async(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
            to_status=RunStatusDb.canceled,
        )
        await session.commit()
        return initial_state

    except Exception as e:
        await session.rollback()
        # Transition to failed
        await transition_run_status_async(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
            to_status=RunStatusDb.failed,
            failure_reason=str(e),
        )
        await session.commit()

        raise


async def resume_orchestrator(
    session: AsyncSession, tenant_id: UUID, run_id: UUID
) -> OrchestratorState:
    """
    Resume orchestrator from last checkpoint.

    Args:
        session: Database session
        tenant_id: Tenant ID
        run_id: Run ID

    Returns:
        Final orchestrator state

    Raises:
        Exception: If no checkpoint found or execution fails
    """
    # Extract sync session proxy for synchronous graph execution
    sync_session = session.sync_session

    # Create checkpoint saver
    checkpoint_saver = PostgresCheckpointSaver(
        session=sync_session, tenant_id=tenant_id, run_id=run_id
    )

    # Get latest checkpoint
    config = {
        "configurable": {
            "thread_id": str(run_id),
            "checkpoint_ns": "orchestrator",
        }
    }

    checkpoint, metadata = checkpoint_saver.get(config)

    if not checkpoint:
        raise ValueError(f"No checkpoint found for run {run_id}")

    # Resume from checkpoint
    graph = create_orchestrator_graph(sync_session)

    # Continue execution
    final_state_dict = graph.invoke(checkpoint, config=config)
    final_state = OrchestratorState(**final_state_dict)

    # Update completion time
    final_state.completed_at = datetime.now(UTC)

    # Update run status
    await transition_run_status_async(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        to_status=RunStatusDb.succeeded,
        current_stage="export",
    )

    await session.commit()

    return final_state
