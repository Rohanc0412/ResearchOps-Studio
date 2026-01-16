from __future__ import annotations

import time

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import OperationalError
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
                # Serialize schema init across api/worker containers to avoid races (e.g. ENUM type creation).
                with engine.begin() as conn:
                    conn.execute(text("SELECT pg_advisory_lock(42424242)"))
                    try:
                        Base.metadata.create_all(bind=conn, checkfirst=True)
                        apply_sql_migrations(conn)
                    finally:
                        conn.execute(text("SELECT pg_advisory_unlock(42424242)"))
            else:
                Base.metadata.create_all(engine)
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
