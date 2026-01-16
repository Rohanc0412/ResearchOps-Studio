from __future__ import annotations

import time

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.engine import Engine

from db.models.base import Base
from db.migrate import apply_sql_migrations


def init_db(engine: Engine, *, retries: int = 30, sleep_seconds: float = 1.0) -> None:
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
        return

    last_error: Exception | None = None
    for _ in range(retries):
        try:
            if engine.dialect.name == "postgresql":
                # Serialize schema init across api/worker containers to avoid races.
                #
                # We run Alembic migrations (idempotent via alembic_version). This is safer than
                # `create_all()` when schemas evolve, and it enables pgvector + enums reliably.
                from alembic import command
                from alembic.config import Config

                # Use a transaction-scoped advisory lock so we can safely commit/rollback and avoid
                # leaking locks even when migrations error.
                with engine.begin() as conn:
                    conn.execute(text("SELECT pg_advisory_xact_lock(42424242)"))
                    cfg = Config("alembic.ini")
                    cfg.attributes["connection"] = conn

                    inspector = sa.inspect(conn)
                    has_alembic_version = inspector.has_table("alembic_version")
                    has_projects = inspector.has_table("projects")
                    if not has_alembic_version and has_projects:
                        # Legacy dev DBs may have been initialized via `Base.metadata.create_all()`
                        # (no alembic_version table). In that case, stamp to avoid duplicate DDL.
                        command.stamp(cfg, "head")
                    else:
                        command.upgrade(cfg, "head")
            else:
                Base.metadata.create_all(engine)
                apply_sql_migrations(engine)
            return
        except IntegrityError as e:
            # A concurrent initializer may have created a named type between our check and create.
            last_error = e
            time.sleep(sleep_seconds)
        except OperationalError as e:
            last_error = e
            time.sleep(sleep_seconds)
    assert last_error is not None
    raise last_error
