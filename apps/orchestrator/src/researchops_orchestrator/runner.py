"""
Runner for executing the orchestrator graph.

Integrates with the run lifecycle and emits SSE events.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from db.models.runs import RunRow, RunStatusDb
from researchops_core.orchestrator.state import OrchestratorState
from researchops_core.runs.lifecycle import transition_run_status
from researchops_orchestrator.checkpoints import PostgresCheckpointSaver
from researchops_orchestrator.graph import create_orchestrator_graph


async def run_orchestrator(
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    user_query: str,
    research_goal: str | None = None,
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
    transition_run_status(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        target_status=RunStatusDb.running,
        current_stage="retrieve",
    )
    session.commit()

    # Initialize state
    initial_state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query=user_query,
        research_goal=research_goal,
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

        # Transition to succeeded
        transition_run_status(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
            target_status=RunStatusDb.succeeded,
            current_stage="export",
        )

        session.commit()

        return final_state

    except Exception as e:
        # Transition to failed
        transition_run_status(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
            target_status=RunStatusDb.failed,
            error_message=str(e),
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
        target_status=RunStatusDb.succeeded,
        current_stage="export",
    )

    session.commit()

    return final_state
