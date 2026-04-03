"""
Regression test: events queued via queue_node_event must be flushed with
audience=progress, not audience=diagnostic.

Run from repo root:
    cd backend && python -m pytest ../tests/backend/test_runtime_event_audience.py -v
"""
import os
import sys
import asyncio
import unittest.mock as mock
from uuid import uuid4
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "services", "orchestrator"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "data"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "libs"))

from db.models.run_events import RunEventAudienceDb, RunEventLevelDb


def _make_runtime(mock_event_store):
    """Build a ResearchRuntime with a mocked event_store and session."""
    from runtime import ResearchRuntime, RuntimeEventStore, RuntimeCheckpointStore

    mock_session = mock.AsyncMock()
    mock_session.flush = mock.AsyncMock()

    runtime = ResearchRuntime(
        session=mock_session,
        tenant_id=uuid4(),
        run_id=uuid4(),
        inputs=mock.MagicMock(),
        event_store=mock_event_store,
        checkpoint_store=mock.MagicMock(),
    )
    return runtime


def test_queued_node_events_are_flushed_with_progress_audience():
    """Events queued via queue_node_event must arrive at event_store with audience=progress."""
    appended_calls = []

    async def fake_append(*, tenant_id, run_id, audience, event_type, level, stage, message, payload=None, allow_finished=False):
        appended_calls.append({
            "audience": audience,
            "event_type": event_type,
            "stage": stage,
        })
        return mock.MagicMock()

    mock_event_store = mock.MagicMock()
    mock_event_store.append = fake_append

    runtime = _make_runtime(mock_event_store)
    tenant_id = runtime.tenant_id
    run_id = runtime.run_id

    runtime.queue_node_event(
        tenant_id=tenant_id,
        run_id=run_id,
        event_type="stage_start",
        stage="evidence_pack",
        message="Starting stage: evidence_pack",
    )
    runtime.queue_node_event(
        tenant_id=tenant_id,
        run_id=run_id,
        event_type="evidence_pack.created",
        stage="evidence_pack",
        message="evidence_pack.created: evidence_pack",
    )

    asyncio.run(runtime.flush_pending_events())

    assert len(appended_calls) == 2
    for call in appended_calls:
        assert call["audience"] == RunEventAudienceDb.progress, (
            f"Expected audience=progress, got {call['audience']} for event_type={call['event_type']}"
        )


def test_append_run_event_sync_defaults_to_progress_audience():
    """append_run_event_sync must default audience to progress."""
    import inspect
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "data"))
    from db.repositories.project_runs import append_run_event_sync
    sig = inspect.signature(append_run_event_sync)
    audience_param = sig.parameters.get("audience")
    assert audience_param is not None, "append_run_event_sync must have an 'audience' parameter"
    assert audience_param.default == RunEventAudienceDb.progress, (
        f"Default must be RunEventAudienceDb.progress, got {audience_param.default}"
    )
