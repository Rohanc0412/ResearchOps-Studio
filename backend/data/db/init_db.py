from __future__ import annotations

import time
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError

from db.models.base import Base
from db.models.roles import RoleRow


def init_db(engine: Engine, *, retries: int = 30, sleep_seconds: float = 1.0) -> None:
    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA busy_timeout=30000"))
        import db.models  # noqa: F401
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            _seed_reference_data(conn)
        return

    last_error: Exception | None = None
    for _ in range(retries):
        try:
            if engine.dialect.name == "postgresql":
                # Serialize schema init *and* seeding across api/worker containers.
                # Use a session-level advisory lock so Alembic transaction boundaries
                # cannot release the lock between revisions.
                from alembic import command
                from alembic.config import Config

                backend_root = Path(__file__).resolve().parents[2]
                alembic_ini = backend_root / "alembic.ini"
                alembic_dir = backend_root / "data" / "db" / "alembic"

                with engine.connect() as conn:
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
                Base.metadata.create_all(engine)
                with engine.begin() as conn:
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
