"""
Regression tests for DB layer bug fixes identified in code review.

Run from backend/:
    python -m pytest tests/test_db_fixes.py -v

Path setup: tests live in backend/tests/; DB packages live under backend/data/,
so we insert both backend/ and backend/data/ into sys.path.
"""
from __future__ import annotations

import importlib
import os
import sys
import unittest.mock as mock
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "data"))


# ── shared helpers ─────────────────────────────────────────────────────────────


def _make_session():
    """In-memory SQLite session with all tables created."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import db.models  # noqa: F401 — registers all models with Base.metadata
    from db.models.base import Base

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)
    return Session()


def _seed_roles(session) -> None:
    from db.models.roles import RoleRow

    for name in ("owner", "admin", "researcher", "viewer"):
        session.add(RoleRow(name=name, description=f"Built-in {name}"))
    session.flush()


def _make_project(session, tenant_id):
    from db.models.projects import ProjectRow

    p = ProjectRow(tenant_id=tenant_id, name=f"proj-{uuid4()}", created_by="tester")
    session.add(p)
    session.flush()
    return p


def _make_run(session, tenant_id, project_id):
    from db.models.runs import RunRow, RunStatusDb

    r = RunRow(tenant_id=tenant_id, project_id=project_id, status=RunStatusDb.running)
    session.add(r)
    session.flush()
    return r


# ── Issue 1: RunRow.usage_json must decode "true"/"false" → Python bools ───────


def test_usage_json_decodes_true_string_to_python_bool():
    """RunRow.usage_json getter must return True (bool), not 'true' (string)."""
    from db.models.runs import RunRow

    class FakeMetric:
        def __init__(self, name, text, number=None):
            self.metric_name = name
            self.metric_text = text
            self.metric_number = number

    run = mock.MagicMock(spec=RunRow)
    run.usage_metrics = [FakeMetric("web_search", "true")]

    result = RunRow.usage_json.fget(run)

    assert result["web_search"] is True, (
        f"Expected True (bool), got {result['web_search']!r} ({type(result['web_search']).__name__})"
    )


def test_usage_json_decodes_false_string_to_python_bool():
    """RunRow.usage_json getter must return False (bool), not 'false' (string)."""
    from db.models.runs import RunRow

    class FakeMetric:
        def __init__(self, name, text, number=None):
            self.metric_name = name
            self.metric_text = text
            self.metric_number = number

    run = mock.MagicMock(spec=RunRow)
    run.usage_metrics = [FakeMetric("cached", "false")]

    result = RunRow.usage_json.fget(run)

    assert result["cached"] is False, (
        f"Expected False (bool), got {result['cached']!r} ({type(result['cached']).__name__})"
    )


def test_usage_json_matches_get_run_usage_metrics_for_bools():
    """RunRow.usage_json and get_run_usage_metrics() must return identical values for bool metrics."""
    import db.repositories.project_runs as pr
    from db.models.runs import RunRow

    class FakeMetric:
        def __init__(self, name, text, number=None):
            self.metric_name = name
            self.metric_text = text
            self.metric_number = number

    metrics = [
        FakeMetric("flag_a", "true"),
        FakeMetric("flag_b", "false"),
        FakeMetric("count", None, 7),
    ]
    run = mock.MagicMock(spec=RunRow)
    run.usage_metrics = metrics

    property_result = RunRow.usage_json.fget(run)
    repo_result = pr.get_run_usage_metrics(run)

    assert property_result == repo_result, (
        f"Property and repo function disagree:\n"
        f"  property : {property_result}\n"
        f"  repo     : {repo_result}"
    )


# ── Issue 2: create_or_get_source must handle concurrent-insert IntegrityError ─


def test_create_or_get_source_returns_existing_on_integrity_error():
    """When a concurrent insert races and causes IntegrityError, returns the existing row."""
    from sqlalchemy.exc import IntegrityError as SAIntegrityError

    import db.repositories.corpus as corpus

    tenant_id = uuid4()
    canonical_id = "doi:10.9999/race"

    existing = mock.MagicMock()
    existing.canonical_id = canonical_id
    existing.title = "Existing paper"
    existing.authors = []
    existing.identifiers = []
    existing.metadata_json = {}
    existing.updated_at = None

    mock_session = mock.MagicMock()
    # flush raises IntegrityError (concurrent insert from another worker)
    mock_session.flush.side_effect = SAIntegrityError(
        "UNIQUE constraint failed", orig=Exception("unique"), params={}
    )

    with mock.patch.object(corpus, "get_source_by_canonical_id") as mock_get:
        # First call (before our insert attempt): source appears absent
        # Second call (after we catch IntegrityError): the other worker's row is there
        mock_get.side_effect = [None, existing]

        result = corpus.create_or_get_source(
            session=mock_session,
            tenant_id=tenant_id,
            canonical_id=canonical_id,
            source_type="paper",
        )

    assert result is existing, "Should return the row inserted by the concurrent worker"


# ── Issue 3: append_run_event must use FOR UPDATE to serialize event_number ─────


def test_append_run_event_run_fetch_uses_with_for_update():
    """The run SELECT inside append_run_event must carry WITH FOR UPDATE."""
    from sqlalchemy import select
    from db.models.runs import RunRow
    import db.repositories.project_runs as pr

    session = _make_session()
    _seed_roles(session)
    tenant_id = uuid4()
    project = _make_project(session, tenant_id)
    run = _make_run(session, tenant_id, project.id)
    session.commit()

    captured_stmts: list = []
    real_execute = session.__class__.execute

    def spy(self, stmt, *args, **kwargs):
        captured_stmts.append(stmt)
        return real_execute(self, stmt, *args, **kwargs)

    from db.models.run_events import RunEventLevelDb

    with mock.patch.object(session.__class__, "execute", spy):
        pr.append_run_event(
            session=session,
            tenant_id=tenant_id,
            run_id=run.id,
            level=RunEventLevelDb.info,
            message="hello",
        )

    # Find every SELECT statement that targets the runs table
    run_selects = [
        s for s in captured_stmts
        if hasattr(s, "_for_update_arg") and "runs" in str(s).lower()
    ]
    assert run_selects, "No SELECT on 'runs' table found in append_run_event"
    assert any(s._for_update_arg is not None for s in run_selects), (
        "The run fetch in append_run_event does not use WITH FOR UPDATE — "
        "concurrent appends can produce duplicate event_numbers"
    )
    session.close()


# ── Issue 4: SnippetEmbeddingRow must be importable without pgvector installed ──


def test_snippet_embeddings_has_pgvector_import_guard():
    """db.models.snippet_embeddings must guard the pgvector import with try/except.

    The presence of _PGVECTOR_AVAILABLE proves that a conditional import is in place
    instead of a hard unconditional `from pgvector.sqlalchemy import Vector` that
    would raise ImportError in environments without the pgvector package.
    """
    from db.models import snippet_embeddings as se

    assert hasattr(se, "_PGVECTOR_AVAILABLE"), (
        "snippet_embeddings is missing _PGVECTOR_AVAILABLE — "
        "the pgvector import is unconditional and will break without the package"
    )
    assert isinstance(se._PGVECTOR_AVAILABLE, bool), (
        f"_PGVECTOR_AVAILABLE must be bool, got {type(se._PGVECTOR_AVAILABLE)}"
    )


# ── Issue 5: get_user_by_id must filter by tenant_id ──────────────────────────


def test_get_user_by_id_returns_none_for_wrong_tenant():
    """get_user_by_id(tenant_id=X) must return None when user belongs to tenant Y."""
    from db.repositories.identity import create_user, get_user_by_id

    session = _make_session()
    _seed_roles(session)

    tenant_a = uuid4()
    tenant_b = uuid4()

    # Create a user in tenant A
    user_a = create_user(
        session=session,
        tenant_id=tenant_a,
        username="alice",
        email="alice@example.com",
        password_hash="hash",
        role_names=["viewer"],
    )
    session.flush()

    # Looking up with tenant B's ID should return None
    result = get_user_by_id(session, tenant_id=tenant_b, user_id=user_a.id)

    assert result is None, (
        f"get_user_by_id should return None for a different tenant, got {result!r}"
    )
    session.close()


def test_get_user_by_id_returns_user_for_correct_tenant():
    """get_user_by_id(tenant_id=X) returns the user when tenant matches."""
    from db.repositories.identity import create_user, get_user_by_id

    session = _make_session()
    _seed_roles(session)

    tenant_id = uuid4()
    user = create_user(
        session=session,
        tenant_id=tenant_id,
        username="bob",
        email="bob@example.com",
        password_hash="hash",
        role_names=["viewer"],
    )
    session.flush()

    result = get_user_by_id(session, tenant_id=tenant_id, user_id=user.id)

    assert result is not None
    assert result.id == user.id
    session.close()


# ── Issue 7: _touch_project_from_run must not accept a `run` parameter ─────────


def test_touch_project_from_run_has_no_run_parameter():
    """_touch_project_from_run must not carry the unused `run` parameter."""
    import inspect
    import db.repositories.project_runs as pr

    sig = inspect.signature(pr._touch_project_from_run)
    assert "run" not in sig.parameters, (
        f"_touch_project_from_run still has an unused 'run' parameter: {list(sig.parameters)}"
    )


# ── Issue 8: _table_exists must not query the DB on every create_run ───────────


def test_table_exists_only_called_once_across_multiple_create_runs():
    """_table_exists result is cached; the DB introspection fires at most once."""
    import db.repositories.project_runs as pr

    session = _make_session()
    _seed_roles(session)
    tenant_id = uuid4()
    project = _make_project(session, tenant_id)
    session.flush()

    # Clear any stale cache from earlier tests
    if hasattr(pr, "_table_existence_cache"):
        pr._table_existence_cache.clear()

    call_count = [0]
    real_table_exists = pr._table_exists

    def counting_table_exists(sess, table_name):
        call_count[0] += 1
        return real_table_exists(sess, table_name)

    with mock.patch.object(pr, "_table_exists", side_effect=counting_table_exists):
        pr.create_run(session=session, tenant_id=tenant_id, project_id=project.id)
        pr.create_run(session=session, tenant_id=tenant_id, project_id=project.id)

    assert call_count[0] <= 1, (
        f"_table_exists was called {call_count[0]} times across 2 create_run calls; "
        "expected ≤1 (result should be cached)"
    )
    session.close()


# ── Issue 8b: replace_run_usage_metrics must update existing rows in place ───────


def test_replace_run_usage_metrics_updates_existing_rows_without_unique_conflict():
    """Replacing usage metrics on an existing run must not create duplicate metric_name rows."""
    import db.repositories.project_runs as pr
    from db.models.runs import RunStatusDb

    session = _make_session()
    _seed_roles(session)
    tenant_id = uuid4()
    project = _make_project(session, tenant_id)

    run = pr.create_run(
        session=session,
        tenant_id=tenant_id,
        project_id=project.id,
        status=RunStatusDb.queued,
        current_stage="retrieve",
        usage={
            "job_type": "research.run",
            "user_query": "compare multilingual embeddings",
            "output_type": "report",
        },
    )
    session.flush()

    updated_usage = dict(pr.get_run_usage_metrics(run))
    updated_usage["evidence_snippets"] = 20
    updated_usage["job_type"] = "research.run"

    pr.replace_run_usage_metrics(run, updated_usage)
    session.flush()

    refreshed = pr.get_run_usage_metrics(run)
    assert refreshed["job_type"] == "research.run"
    assert refreshed["evidence_snippets"] == 20
    metric_names = sorted(row.metric_name for row in run.usage_metrics)
    assert metric_names.count("job_type") == 1
    session.close()


# ── Issue 9: get_last_action timestamps must not swap when created_at is None ──


def test_get_last_action_started_at_uses_created_at():
    """get_last_action started_at must use action.created_at, not resolved_at."""
    from datetime import datetime, UTC, timezone
    from db.repositories.chat import get_last_action

    created = datetime(2025, 1, 10, 9, 0, 0, tzinfo=UTC)
    resolved = datetime(2025, 1, 10, 9, 5, 0, tzinfo=UTC)

    action = mock.MagicMock()
    action.action_kind = "last"
    action.action_type = "run_research"
    action.created_at = created
    action.resolved_at = resolved
    action.related_run_id = None
    action.reply_message_id = None
    action.consent = None

    conv = mock.MagicMock()
    conv.actions = [action]

    result = get_last_action(conv)

    assert result is not None
    # started_at must reflect when the action was created, not when it completed
    assert result["started_at"] == created.isoformat(), (
        f"started_at should be {created.isoformat()!r}, got {result['started_at']!r}"
    )
    assert result["completed_at"] == resolved.isoformat(), (
        f"completed_at should be {resolved.isoformat()!r}, got {result['completed_at']!r}"
    )


def test_get_last_action_timestamps_do_not_swap_when_created_at_is_none():
    """When created_at is None, started_at must not silently become resolved_at."""
    from datetime import datetime, UTC
    from db.repositories.chat import get_last_action

    resolved = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)

    action = mock.MagicMock()
    action.action_kind = "last"
    action.action_type = "run_research"
    action.created_at = None  # old row with no created_at
    action.resolved_at = resolved
    action.related_run_id = None
    action.reply_message_id = None
    action.consent = None

    conv = mock.MagicMock()
    conv.actions = [action]

    result = get_last_action(conv)

    assert result is not None
    # completed_at must be resolved_at
    assert result["completed_at"] == resolved.isoformat(), (
        f"completed_at should be {resolved.isoformat()!r}, got {result['completed_at']!r}"
    )
    # started_at must NOT equal completed_at (they shouldn't silently be the same timestamp)
    # When created_at is None, we should get a sensible fallback, not resolved_at
    assert result["started_at"] != result["completed_at"], (
        "started_at and completed_at should not be the same when created_at is None — "
        "this indicates the timestamp fallback is swapped"
    )
