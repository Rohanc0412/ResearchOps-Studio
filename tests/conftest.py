from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def _add_path(p: Path) -> None:
    sys.path.insert(0, str(p))


REPO_ROOT = Path(__file__).resolve().parents[1] / "backend"

# Make monorepo trees importable without editable installs.
_add_path(REPO_ROOT / "services" / "api")
_add_path(REPO_ROOT / "services" / "orchestrator")
_add_path(REPO_ROOT / "services" / "workers")
_add_path(REPO_ROOT / "libs")
_add_path(REPO_ROOT / "data")
_add_path(REPO_ROOT)  # backend-local imports

# ---------------------------------------------------------------------------
# PostgreSQL test database URLs
# ---------------------------------------------------------------------------

_DEFAULT_TEST_DB_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/researchops_test"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", _DEFAULT_TEST_DB_URL)


def _to_async_url(url: str) -> str:
    """Rewrite a sync postgres driver URL to use asyncpg."""
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix):]
    return url


TEST_ASYNC_DATABASE_URL = _to_async_url(TEST_DATABASE_URL)

# Expose via environment so tests that read os.environ["TEST_DATABASE_URL"] work.
os.environ.setdefault("TEST_DATABASE_URL", TEST_DATABASE_URL)


@pytest.fixture()
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def pg_sync_engine():
    """Sync PostgreSQL engine for one-time schema init and per-test cleanup."""
    from db.init_db import init_db_sync

    engine = create_engine(TEST_DATABASE_URL, future=True)
    init_db_sync(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def reset_postgres_db(pg_sync_engine) -> None:
    """Keep PostgreSQL-backed tests isolated from each other."""
    if pg_sync_engine.dialect.name != "postgresql":
        yield
        return

    with pg_sync_engine.begin() as conn:
        table_names = conn.execute(
            text(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename NOT IN ('alembic_version', 'roles')
                """
            )
        ).scalars().all()
        if table_names:
            quoted_tables = ", ".join(f'"{table_name}"' for table_name in table_names)
            conn.execute(text(f"TRUNCATE TABLE {quoted_tables} RESTART IDENTITY CASCADE"))

    yield


@pytest_asyncio.fixture()
async def pg_engine() -> AsyncEngine:
    """Async PostgreSQL engine connected to the test database.

    Runs Alembic migrations on first use (idempotent).
    """
    from db.init_db import init_db

    engine = create_async_engine(TEST_ASYNC_DATABASE_URL, future=True)
    await init_db(engine)
    yield engine
    await engine.dispose()
