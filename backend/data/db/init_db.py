from __future__ import annotations

import time
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.engine import Engine

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
                # Running both inside the advisory-lock transaction means no container
                # can race to seed roles while another is still migrating.
                from alembic import command
                from alembic.config import Config

                backend_root = Path(__file__).resolve().parents[2]
                alembic_ini = backend_root / "alembic.ini"
                alembic_dir = backend_root / "data" / "db" / "alembic"

                with engine.begin() as conn:
                    conn.execute(text("SELECT pg_advisory_xact_lock(42424242)"))
                    cfg = Config(str(alembic_ini))
                    cfg.set_main_option("script_location", str(alembic_dir))
                    cfg.set_main_option("prepend_sys_path", str(backend_root))
                    cfg.attributes["connection"] = conn
                    command.upgrade(cfg, "head")
                    _seed_reference_data(conn)
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
        conn.execute(sa.insert(RoleRow).values(name=role_name, description=f"Built-in {role_name} role"))
