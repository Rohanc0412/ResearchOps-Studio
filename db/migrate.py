from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, Connection, text


def apply_sql_migrations(bind: Engine | Connection, *, migrations_dir: Path | None = None) -> None:
    migrations_dir = migrations_dir or Path("db/migrations")
    if not migrations_dir.exists():
        return

    if isinstance(bind, Engine):
        conn_ctx = bind.begin()
    else:
        conn_ctx = _NoopContext(bind)

    with conn_ctx as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                  id TEXT PRIMARY KEY,
                  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )

        files = sorted(p for p in migrations_dir.glob("*.sql") if p.is_file())
        for path in files:
            migration_id = path.name
            exists = conn.execute(
                text("SELECT 1 FROM schema_migrations WHERE id = :id"), {"id": migration_id}
            ).first()
            if exists:
                continue
            sql = path.read_text(encoding="utf-8")
            if sql.strip():
                conn.exec_driver_sql(sql)
            conn.execute(text("INSERT INTO schema_migrations (id) VALUES (:id)"), {"id": migration_id})


class _NoopContext:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def __enter__(self) -> Connection:
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> None:
        return None
