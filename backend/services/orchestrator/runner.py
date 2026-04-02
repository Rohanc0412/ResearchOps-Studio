"""
Runner for executing the orchestrator graph.

Integrates with the run lifecycle and emits SSE events.
"""

from __future__ import annotations

import inspect
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from cancellation import RunCancelledError
from checkpoint_store import write_checkpoint
from core.env import env_int
from core.orchestrator.state import OrchestratorState
from core.runs.lifecycle import is_run_cancel_requested_async, transition_run_status_async
from db.models.run_checkpoints import RunCheckpointRow
from db.models.runs import RunRow, RunStatusDb
from db.repositories.artifacts import create_artifact, list_artifacts
from graph import create_orchestrator_graph
from observability import langfuse_enabled
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


class _RunnerRuntimeAdapter:
    def __init__(
        self,
        *,
        session: AsyncSession,
        tenant_id: UUID,
        run_id: UUID,
        user_query: str,
        research_goal: str | None,
        llm_provider: str | None,
        llm_model: str | None,
        stage_models: dict[str, str | None],
        max_iterations: int,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.user_query = user_query
        self.research_goal = research_goal
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.stage_models = stage_models
        self.max_iterations = max_iterations

    def initial_state(self) -> OrchestratorState:
        return OrchestratorState(
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            user_query=self.user_query,
            research_goal=self.research_goal,
            llm_provider=self.llm_provider,
            llm_model=self.llm_model,
            stage_models=self.stage_models,
            max_iterations=self.max_iterations,
            started_at=datetime.now(UTC),
        )

    async def assert_not_cancelled(self) -> None:
        if await is_run_cancel_requested_async(
            session=self.session,
            tenant_id=self.tenant_id,
            run_id=self.run_id,
        ):
            raise RunCancelledError(f"Run {self.run_id} cancelled by user")

    async def flush_pending_events(self) -> None:
        await self.session.flush()

    async def _write_after_node(self, *, state: OrchestratorState, node_name: str) -> None:
        await write_checkpoint(
            session=self.session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            node_name=node_name,
            iteration_count=state.iteration_count,
            state_payload=state.model_dump(mode="json"),
            summary_payload={"node_name": node_name},
        )

    async def execute_node(self, *, node_name: str, node_func, state: OrchestratorState) -> OrchestratorState:
        await self.assert_not_cancelled()

        if inspect.iscoroutinefunction(node_func):
            next_state = await node_func(state, self)
        else:
            next_state = await self.session.run_sync(lambda sync_session: node_func(state, sync_session))

        if isinstance(next_state, dict):
            next_state = OrchestratorState(**next_state)

        await self._write_after_node(state=next_state, node_name=node_name)
        await self.flush_pending_events()
        await self.session.commit()
        return next_state

    async def mark_succeeded(self, *, current_stage: str = "export") -> None:
        await transition_run_status_async(
            session=self.session,
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            to_status=RunStatusDb.succeeded,
            current_stage=current_stage,
            finished_at=datetime.now(UTC),
        )

    async def mark_canceled(self) -> None:
        await transition_run_status_async(
            session=self.session,
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            to_status=RunStatusDb.canceled,
            finished_at=datetime.now(UTC),
        )

    async def mark_failed(self, *, failure_reason: str) -> None:
        await transition_run_status_async(
            session=self.session,
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            to_status=RunStatusDb.failed,
            failure_reason=failure_reason,
            finished_at=datetime.now(UTC),
        )


class _RunnerTerminalLifecycleAdapter:
    def __init__(self, *, session: AsyncSession, tenant_id: UUID, run_id: UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.run_id = run_id

    async def mark_succeeded(self, *, current_stage: str = "export") -> None:
        await transition_run_status_async(
            session=self.session,
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            to_status=RunStatusDb.succeeded,
            current_stage=current_stage,
            finished_at=datetime.now(UTC),
        )

    async def mark_canceled(self) -> None:
        await transition_run_status_async(
            session=self.session,
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            to_status=RunStatusDb.canceled,
            finished_at=datetime.now(UTC),
        )

    async def mark_failed(self, *, failure_reason: str) -> None:
        await transition_run_status_async(
            session=self.session,
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            to_status=RunStatusDb.failed,
            failure_reason=failure_reason,
            finished_at=datetime.now(UTC),
        )


def _resolve_terminal_lifecycle_owner(
    runtime_obj: Any,
    *,
    session: AsyncSession,
    tenant_id: UUID,
    run_id: UUID,
):
    has_terminal_hooks = all(
        callable(getattr(runtime_obj, hook_name, None))
        for hook_name in ("mark_succeeded", "mark_canceled", "mark_failed")
    )
    if has_terminal_hooks:
        return runtime_obj
    return _RunnerTerminalLifecycleAdapter(session=session, tenant_id=tenant_id, run_id=run_id)


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
    transition_to_running: bool = True,
    runtime: Any | None = None,
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
    if transition_to_running:
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

    runtime_obj = runtime or _RunnerRuntimeAdapter(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        user_query=user_query,
        research_goal=research_goal,
        llm_provider=llm_provider,
        llm_model=llm_model,
        stage_models=stage_models or {},
        max_iterations=max_iterations,
    )
    terminal_lifecycle = _resolve_terminal_lifecycle_owner(
        runtime_obj,
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
    )
    initial_state = runtime_obj.initial_state()
    initial_state.max_iterations = max_iterations

    # Create graph
    graph = create_orchestrator_graph(runtime_obj)
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
        final_state_dict = await graph.ainvoke(initial_state.model_dump(), config=config)
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

        await terminal_lifecycle.mark_succeeded(current_stage="export")

        await session.commit()

        return final_state

    except RunCancelledError:
        await session.rollback()
        await terminal_lifecycle.mark_canceled()
        await session.commit()
        return initial_state

    except Exception as e:
        await session.rollback()
        await terminal_lifecycle.mark_failed(failure_reason=str(e))
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
    checkpoint = (
        (
            await session.execute(
                select(RunCheckpointRow.payload_json)
                .where(RunCheckpointRow.tenant_id == tenant_id, RunCheckpointRow.run_id == run_id)
                .order_by(RunCheckpointRow.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if checkpoint is None:
        raise ValueError(f"No checkpoint found for run {run_id}")

    checkpoint_state = OrchestratorState(**checkpoint)
    runtime_obj = _RunnerRuntimeAdapter(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        user_query=checkpoint_state.user_query,
        research_goal=checkpoint_state.research_goal,
        llm_provider=checkpoint_state.llm_provider,
        llm_model=checkpoint_state.llm_model,
        stage_models=checkpoint_state.stage_models,
        max_iterations=checkpoint_state.max_iterations,
    )
    terminal_lifecycle = _resolve_terminal_lifecycle_owner(
        runtime_obj,
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
    )
    graph = create_orchestrator_graph(runtime_obj)
    config = {
        "configurable": {
            "thread_id": str(run_id),
        },
        "recursion_limit": checkpoint_state.max_iterations * 20,
    }
    try:
        final_state_dict = await graph.ainvoke(checkpoint_state.model_dump(), config=config)
        final_state = OrchestratorState(**final_state_dict)

        # Update completion time
        final_state.completed_at = datetime.now(UTC)

        await terminal_lifecycle.mark_succeeded(current_stage="export")

        await session.commit()

        return final_state

    except RunCancelledError:
        await session.rollback()
        await terminal_lifecycle.mark_canceled()
        await session.commit()
        return checkpoint_state

    except Exception as e:
        await session.rollback()
        await terminal_lifecycle.mark_failed(failure_reason=str(e))
        await session.commit()
        raise
