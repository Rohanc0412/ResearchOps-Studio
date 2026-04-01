from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from core.settings import Settings
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _async_url(url: str) -> str:
    """Rewrite a sync postgres driver URL to use asyncpg."""
    for sync_driver in (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgresql://",
    ):
        if url.startswith(sync_driver):
            return "postgresql+asyncpg://" + url[len(sync_driver):]
    return url


def create_db_engine(settings: Settings) -> AsyncEngine:
    url = _async_url(settings.database_url)
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        # aiosqlite requires check_same_thread=False.
        # Use NullPool so each connection is opened/closed independently,
        # which avoids pool-level contention under test/single-process workloads.
        from sqlalchemy.pool import NullPool
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = NullPool
    engine = create_async_engine(url, **kwargs)
    if url.startswith("sqlite"):
        # Enable WAL journal mode and a generous busy timeout on every new SQLite
        # connection so concurrent writers wait instead of immediately failing with
        # "database is locked" errors.
        # NOTE: aiosqlite wraps a sync sqlite3 connection in a background thread.
        # We listen on the *sync* engine's "connect" event which fires for the
        # underlying sqlite3 connection that aiosqlite manages.
        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):
            try:
                dbapi_connection.execute("PRAGMA journal_mode=WAL")
                dbapi_connection.execute("PRAGMA busy_timeout=10000")
            except Exception:
                pass  # silently ignore if connection type doesn't support execute directly

    return engine


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def session_scope(
    SessionLocal: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
