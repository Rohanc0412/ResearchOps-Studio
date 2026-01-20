"""
Runner for executing the orchestrator graph.

Integrates with the run lifecycle and emits SSE events.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from db.models.runs import RunRow, RunStatusDb
from db.services.truth import create_artifact, list_artifacts
from researchops_core.orchestrator.state import OrchestratorState
from researchops_core.runs.lifecycle import transition_run_status
from researchops_orchestrator.checkpoints import PostgresCheckpointSaver
from researchops_orchestrator.graph import create_orchestrator_graph

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


def _persist_artifacts(session: Session, run_row: RunRow, artifacts: dict[str, object]) -> int:
    if not artifacts:
        logger.info("artifacts_empty", extra={"run_id": str(run_row.id)})
        return 0

    existing = list_artifacts(
        session=session, tenant_id=run_row.tenant_id, run_id=run_row.id, limit=1
    )
    if existing:
        logger.info(
            "artifacts_already_present",
            extra={"run_id": str(run_row.id), "existing": len(existing)},
        )
        return 0

    created = 0
    for name, content in artifacts.items():
        if content is None:
            continue
        text = _normalize_artifact_content(content)
        mime_type = _guess_mime_type(name)
        metadata = _artifact_metadata(name, text)
        size_bytes = len(text.encode("utf-8"))
        create_artifact(
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

    logger.info(
        "artifacts_persisted",
        extra={"run_id": str(run_row.id), "count": created},
    )
    print(f"    📦 Saved {created} artifact(s)")
    return created


async def run_orchestrator(
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    user_query: str,
    research_goal: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
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
    logger.info(
        "orchestrator_start",
        extra={
            "run_id": str(run_id),
            "tenant_id": str(tenant_id),
            "user_query": user_query,
        },
    )
    transition_run_status(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        to_status=RunStatusDb.running,
        current_stage="retrieve",
    )
    session.commit()

    # Initialize state
    initial_state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query=user_query,
        research_goal=research_goal,
        llm_provider=llm_provider,
        llm_model=llm_model,
        max_iterations=max_iterations,
        started_at=datetime.now(UTC),
    )

    # Create checkpoint saver
    checkpoint_saver = PostgresCheckpointSaver(
        session=session, tenant_id=tenant_id, run_id=run_id
    )

    # Create graph
    graph = create_orchestrator_graph(session)

    # Configure graph execution
    config = {
        "configurable": {
            "thread_id": str(run_id),
            "checkpoint_ns": "orchestrator",
        },
        "recursion_limit": max_iterations * 20,  # Allow plenty of steps
    }

    try:
        # Execute graph (synchronous for now, can be made async)
        final_state_dict = graph.invoke(initial_state.dict(), config=config)

        # Convert back to OrchestratorState
        final_state = OrchestratorState(**final_state_dict)

        # Mark completion time
        final_state.completed_at = datetime.now(UTC)

        # Update run status
        run_row = session.query(RunRow).get(run_id)
        if run_row:
            run_row.current_stage = "export"
            run_row.updated_at = datetime.now(UTC)
            _persist_artifacts(session, run_row, final_state.artifacts or {})

        # Transition to succeeded
        transition_run_status(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
            to_status=RunStatusDb.succeeded,
            current_stage="export",
        )

        session.commit()

        logger.info(
            "orchestrator_complete",
            extra={"run_id": str(run_id), "tenant_id": str(tenant_id)},
        )
        return final_state

    except Exception as e:
        session.rollback()
        logger.exception(
            "orchestrator_failed",
            extra={"run_id": str(run_id), "tenant_id": str(tenant_id), "error": str(e)},
        )
        # Transition to failed
        transition_run_status(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
            to_status=RunStatusDb.failed,
            failure_reason=str(e),
        )
        session.commit()

        raise


async def resume_orchestrator(
    session: Session, tenant_id: UUID, run_id: UUID
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
    # Create checkpoint saver
    checkpoint_saver = PostgresCheckpointSaver(
        session=session, tenant_id=tenant_id, run_id=run_id
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
    graph = create_orchestrator_graph(session)

    # Continue execution
    final_state_dict = graph.invoke(checkpoint, config=config)
    final_state = OrchestratorState(**final_state_dict)

    # Update completion time
    final_state.completed_at = datetime.now(UTC)

    # Update run status
    transition_run_status(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        to_status=RunStatusDb.succeeded,
        current_stage="export",
    )

    session.commit()

    return final_state
