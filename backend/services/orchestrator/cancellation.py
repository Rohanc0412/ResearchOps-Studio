from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from db.models.runs import RunRow
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


class RunCancelledError(Exception):
    """Raised when a run cancel request has been persisted."""


def _bind_uses_asyncpg(session: Session) -> bool:
    bind = session.get_bind()
    if bind is None:
        return False
    dialect = bind.dialect
    return getattr(dialect, "name", "") == "postgresql" and getattr(dialect, "driver", "") == "asyncpg"


def _sync_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg://" + url[len("postgresql+asyncpg://"):]
    return url


@lru_cache(maxsize=4)
def _sidecar_engine(url: str) -> Engine:
    return create_engine(_sync_url(url), future=True, pool_pre_ping=True)


def _bind_url_string(session: Session) -> str:
    url = session.get_bind().url
    render = getattr(url, "render_as_string", None)
    if callable(render):
        return render(hide_password=False)
    return str(url)


def _read_cancel_requested_at_via_sidecar_session(session: Session, tenant_id: UUID, run_id: UUID):
    engine = _sidecar_engine(_bind_url_string(session))
    stmt = (
        select(RunRow.cancel_requested_at)
        .where(RunRow.tenant_id == tenant_id, RunRow.id == run_id)
        .execution_options(populate_existing=True)
    )
    with Session(bind=engine, expire_on_commit=False, autoflush=False, future=True) as sidecar_session:
        return sidecar_session.execute(stmt).scalar_one_or_none()


def is_run_cancel_requested(session: Session, tenant_id: UUID, run_id: UUID) -> bool:
    """Read cancellation state from the database, bypassing stale ORM identity-map rows."""
    if _bind_uses_asyncpg(session):
        cancel_requested_at = _read_cancel_requested_at_via_sidecar_session(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
        )
    else:
        stmt = (
            select(RunRow.cancel_requested_at)
            .where(RunRow.tenant_id == tenant_id, RunRow.id == run_id)
            .execution_options(populate_existing=True)
        )
        cancel_requested_at = session.execute(stmt).scalar_one_or_none()
    return cancel_requested_at is not None


def raise_if_run_cancel_requested(session: Session, tenant_id: UUID, run_id: UUID) -> None:
    if is_run_cancel_requested(session=session, tenant_id=tenant_id, run_id=run_id):
        raise RunCancelledError(f"Run {run_id} cancelled by user")
