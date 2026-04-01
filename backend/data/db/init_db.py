from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Union

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.exc import IntegrityError, OperationalError

from db.models.base import Base
from db.models.roles import RoleRow


def _get_sync_engine(engine: Union[AsyncEngine, Engine]) -> Engine:
    """Return the underlying sync Engine for either an AsyncEngine or a plain Engine."""
    if isinstance(engine, AsyncEngine):
        return engine.sync_engine
    return engine


async def init_db(engine: Union[AsyncEngine, Engine], *, retries: int = 30, sleep_seconds: float = 1.0) -> None:
    sync_engine = _get_sync_engine(engine)
    if sync_engine.dialect.name == "sqlite":
        if isinstance(engine, AsyncEngine):
            async with engine.begin() as conn:
                await conn.execute(text("PRAGMA journal_mode=WAL"))
                await conn.execute(text("PRAGMA busy_timeout=30000"))
                import db.models  # noqa: F401
                await conn.run_sync(Base.metadata.create_all)
                await conn.run_sync(_seed_reference_data)
        else:
            # Sync engine (used by orchestrator worker and tests)
            import db.models  # noqa: F401
            with sync_engine.begin() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
                conn.execute(text("PRAGMA busy_timeout=30000"))
            Base.metadata.create_all(sync_engine)
            with sync_engine.begin() as conn:
                _seed_reference_data(conn)
        return

    last_error: Exception | None = None
    for _ in range(retries):
        try:
            if sync_engine.dialect.name == "postgresql":
                # Serialize schema init *and* seeding across api/worker containers.
                # Use a session-level advisory lock so Alembic transaction boundaries
                # cannot release the lock between revisions.
                from alembic import command
                from alembic.config import Config

                backend_root = Path(__file__).resolve().parents[2]
                alembic_ini = backend_root / "alembic.ini"
                alembic_dir = backend_root / "data" / "db" / "alembic"

                with sync_engine.connect() as conn:
                    conn.execute(text("SELECT pg_advisory_lock(42424242)"))
                    conn.commit()
                    try:
                        cfg = Config(str(alembic_ini))
                        cfg.set_main_option("script_location", str(alembic_dir))
                        cfg.set_main_option("prepend_sys_path", str(backend_root))
                        cfg.attributes["connection"] = conn
                        command.upgrade(cfg, "head")
                        _seed_reference_data(conn)
                        if conn.in_transaction():
                            conn.commit()
                    finally:
                        if conn.in_transaction():
                            conn.rollback()
                        conn.execute(text("SELECT pg_advisory_unlock(42424242)"))
                        if conn.in_transaction():
                            conn.commit()
            else:
                import db.models  # noqa: F401
                Base.metadata.create_all(sync_engine)
                with sync_engine.begin() as conn:
                    _seed_reference_data(conn)
            return
        except IntegrityError as e:
            last_error = e
            time.sleep(sleep_seconds)
        except OperationalError as e:
            last_error = e
            time.sleep(sleep_seconds)
    assert last_error is not None
    raise last_error


def init_db_sync(engine: Union[AsyncEngine, Engine], *, retries: int = 30, sleep_seconds: float = 1.0) -> None:
    """Synchronous wrapper for init_db — use in non-async contexts (e.g., orchestrator worker)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        raise RuntimeError(
            "init_db_sync cannot be called from a running async event loop. Use `await init_db()` instead."
        )
    asyncio.run(init_db(engine, retries=retries, sleep_seconds=sleep_seconds))


def _seed_reference_data(conn: sa.engine.Connection) -> None:
    existing = {
        row[0]
        for row in conn.execute(sa.select(RoleRow.name))
    }
    for role_name in ("owner", "admin", "researcher", "viewer"):
        if role_name in existing:
            continue
        conn.execute(
            sa.insert(RoleRow).values(name=role_name, description=f"Built-in {role_name} role")
        )
