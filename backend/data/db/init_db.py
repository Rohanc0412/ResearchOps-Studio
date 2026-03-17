from __future__ import annotations

import time

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.engine import Engine

from db.models.base import Base
from db.models.roles import RoleRow


def init_db(engine: Engine, *, retries: int = 30, sleep_seconds: float = 1.0) -> None:
    if engine.dialect.name == "sqlite":
        import db.models  # noqa: F401
        Base.metadata.create_all(engine)
        _seed_reference_data(engine)
        return

    last_error: Exception | None = None
    for _ in range(retries):
        try:
            if engine.dialect.name == "postgresql":
                # Serialize schema init across api/worker containers to avoid races.
                from alembic import command
                from alembic.config import Config

                with engine.begin() as conn:
                    conn.execute(text("SELECT pg_advisory_xact_lock(42424242)"))
                    cfg = Config("alembic.ini")
                    cfg.attributes["connection"] = conn
                    command.upgrade(cfg, "head")
                _seed_reference_data(engine)
            else:
                import db.models  # noqa: F401
                Base.metadata.create_all(engine)
                _seed_reference_data(engine)
            return
        except IntegrityError as e:
            last_error = e
            time.sleep(sleep_seconds)
        except OperationalError as e:
            last_error = e
            time.sleep(sleep_seconds)
    assert last_error is not None
    raise last_error


def _seed_reference_data(engine: Engine) -> None:
    with engine.begin() as conn:
        existing = {
            row[0]
            for row in conn.execute(sa.select(RoleRow.name))
        }
        for role_name in ("owner", "admin", "researcher", "viewer"):
            if role_name in existing:
                continue
            conn.execute(sa.insert(RoleRow).values(name=role_name, description=f"Built-in {role_name} role"))
