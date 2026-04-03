from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from cancellation import RunCancelledError
from checkpoint_store import write_checkpoint
from core.orchestrator.state import OrchestratorState
from core.runs.lifecycle import is_run_cancel_requested_async, transition_run_status_async
from db.models.run_checkpoints import RunCheckpointRow
from db.models.run_events import RunEventAudienceDb, RunEventLevelDb, RunEventRow
from db.models.runs import RunStatusDb
from event_store import append_runtime_event
from runner import run_orchestrator
from runtime_types import ResearchRunInputs
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _QueuedNodeEvent:
    tenant_id: UUID
    run_id: UUID
    event_type: str
    stage: str | None
    message: str
    payload: dict | None
    audience: RunEventAudienceDb = RunEventAudienceDb.progress


class _RuntimeNodeSessionProxy:
    """Proxy around sync SQLAlchemy Session with runtime-owned event enqueue APIs."""

    __slots__ = ("_session", "_runtime")

    def __init__(self, *, session: Session, runtime: "ResearchRuntime") -> None:
        self._session = session
        self._runtime = runtime

    def __getattr__(self, name: str):
        return getattr(self._session, name)

    def enqueue_runtime_event(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        event_type: str,
        stage: str | None = None,
        message: str | None = None,
        data: dict | None = None,
    ) -> None:
        self._runtime.queue_node_event(
            tenant_id=tenant_id,
            run_id=run_id,
            event_type=event_type,
            stage=stage,
            message=message,
            data=data,
        )


@dataclass(slots=True)
class RuntimeEventStore:
    session: AsyncSession

    async def append(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        audience: RunEventAudienceDb,
        event_type: str,
        level: RunEventLevelDb,
        stage: str | None,
        message: str,
        payload: dict | None = None,
        allow_finished: bool = False,
    ) -> RunEventRow:
        return await append_runtime_event(
            session=self.session,
            tenant_id=tenant_id,
            run_id=run_id,
            audience=audience,
            event_type=event_type,
            level=level,
            stage=stage,
            message=message,
            payload=payload,
            allow_finished=allow_finished,
        )


@dataclass(slots=True)
class RuntimeCheckpointStore:
    session: AsyncSession

    async def write(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        node_name: str,
        iteration_count: int,
        state_payload: dict | None = None,
        summary_payload: dict | None = None,
        checkpoint_version: int = 1,
    ) -> RunCheckpointRow:
        return await write_checkpoint(
            session=self.session,
            tenant_id=tenant_id,
            run_id=run_id,
            node_name=node_name,
            iteration_count=iteration_count,
            state_payload=state_payload,
            summary_payload=summary_payload,
            checkpoint_version=checkpoint_version,
        )

    async def write_after_node(
        self, *, state: OrchestratorState, node_name: str
    ) -> RunCheckpointRow:
        return await self.write(
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            node_name=node_name,
            iteration_count=state.iteration_count,
            state_payload=state.model_dump(mode="json"),
            summary_payload={"node_name": node_name},
        )


@dataclass(slots=True)
class ResearchRuntime:
    session: AsyncSession
    tenant_id: UUID
    run_id: UUID
    inputs: ResearchRunInputs
    event_store: RuntimeEventStore
    checkpoint_store: RuntimeCheckpointStore
    _pending_node_events: list[_QueuedNodeEvent] = field(default_factory=list)

    @classmethod
    async def create(
        cls,
        *,
        session: AsyncSession,
        tenant_id: UUID,
        run_id: UUID,
        inputs: ResearchRunInputs,
    ) -> ResearchRuntime:
        return cls(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
            inputs=inputs,
            event_store=RuntimeEventStore(session=session),
            checkpoint_store=RuntimeCheckpointStore(session=session),
        )

    def initial_state(self) -> OrchestratorState:
        return OrchestratorState(
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            user_query=self.inputs.user_query,
            research_goal=self.inputs.research_goal,
            llm_provider=self.inputs.llm_provider,
            llm_model=self.inputs.llm_model,
            stage_models=self.inputs.stage_models,
            max_iterations=self.inputs.max_iterations,
            started_at=datetime.now(UTC),
        )

    async def assert_not_cancelled(self) -> None:
        if await is_run_cancel_requested_async(
            session=self.session,
            tenant_id=self.tenant_id,
            run_id=self.run_id,
        ):
            raise RunCancelledError(f"Run {self.run_id} cancelled by user")

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

    def queue_node_event(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        event_type: str,
        stage: str | None = None,
        message: str | None = None,
        data: dict | None = None,
        audience: RunEventAudienceDb = RunEventAudienceDb.progress,
    ) -> None:
        self._pending_node_events.append(
            _QueuedNodeEvent(
                tenant_id=tenant_id,
                run_id=run_id,
                event_type=event_type,
                stage=stage,
                message=message or f"{event_type}: {stage or 'unknown'}",
                payload=data or {},
                audience=audience,
            )
        )

    def sync_node_session(self, sync_session: Session) -> _RuntimeNodeSessionProxy:
        return _RuntimeNodeSessionProxy(session=sync_session, runtime=self)

    async def flush_pending_events(self) -> None:
        pending_events = self._pending_node_events
        self._pending_node_events = []
        for event in pending_events:
            try:
                await self.event_store.append(
                    tenant_id=event.tenant_id,
                    run_id=event.run_id,
                    audience=event.audience,
                    event_type=event.event_type,
                    level=RunEventLevelDb.info,
                    stage=event.stage,
                    message=event.message,
                    payload=event.payload,
                    allow_finished=True,
                )
            except Exception:
                logger.debug(
                    "runtime event queue suppressed append error",
                    extra={
                        "event_type": event.event_type,
                        "run_id": str(event.run_id),
                        "tenant_id": str(event.tenant_id),
                    },
                    exc_info=True,
                )
        await self.session.flush()

    async def execute_node(
        self,
        *,
        node_name: str,
        node_func,
        state: OrchestratorState,
    ) -> OrchestratorState:
        await self.assert_not_cancelled()

        try:
            if inspect.iscoroutinefunction(node_func):
                next_state = await node_func(state, self)
            else:
                next_state = await self.session.run_sync(
                    lambda sync_session: node_func(state, self.sync_node_session(sync_session))
                )

            if isinstance(next_state, dict):
                next_state = OrchestratorState(**next_state)

            await self.checkpoint_store.write_after_node(state=next_state, node_name=node_name)
            await self.flush_pending_events()
            await self.session.commit()
            return next_state
        except Exception:
            try:
                await self.session.rollback()
                if self._pending_node_events:
                    await self.flush_pending_events()
                    await self.session.commit()
            except Exception:
                logger.exception(
                    "failed to persist queued node events after node exception",
                    extra={
                        "node_name": node_name,
                        "run_id": str(self.run_id),
                        "tenant_id": str(self.tenant_id),
                    },
                )
                try:
                    await self.session.rollback()
                except Exception:
                    pass
            raise


async def run_research_orchestrator(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    run_id: UUID,
    inputs: ResearchRunInputs,
) -> OrchestratorState:
    runtime = await ResearchRuntime.create(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        inputs=inputs,
    )

    await transition_run_status_async(
        session=runtime.session,
        tenant_id=runtime.tenant_id,
        run_id=runtime.run_id,
        to_status=RunStatusDb.running,
        current_stage="retrieve",
    )
    await runtime.session.commit()

    return await run_orchestrator(
        session=runtime.session,
        tenant_id=runtime.tenant_id,
        run_id=runtime.run_id,
        user_query=runtime.inputs.user_query,
        research_goal=runtime.inputs.research_goal,
        llm_provider=runtime.inputs.llm_provider,
        llm_model=runtime.inputs.llm_model,
        stage_models=runtime.inputs.stage_models,
        max_iterations=runtime.inputs.max_iterations,
        transition_to_running=False,
        runtime=runtime,
    )


__all__ = [
    "ResearchRuntime",
    "RuntimeCheckpointStore",
    "RuntimeEventStore",
    "run_research_orchestrator",
]
