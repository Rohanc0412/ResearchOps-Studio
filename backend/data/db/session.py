from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from core.settings import Settings
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
    return create_async_engine(url, pool_pre_ping=True, future=True)


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
