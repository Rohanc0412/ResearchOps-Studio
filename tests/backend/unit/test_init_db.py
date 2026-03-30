from __future__ import annotations

from types import SimpleNamespace


def test_init_db_uses_session_level_advisory_lock_for_postgres(monkeypatch):
    from db import init_db as init_db_module

    executed: list[str] = []
    seeded: list[object] = []

    class FakeConnection:
        def __init__(self):
            self.attributes = {}
            self._in_transaction = False

        def execute(self, statement):
            executed.append(str(statement))
            self._in_transaction = True

        def commit(self):
            self._in_transaction = False

        def rollback(self):
            self._in_transaction = False

        def in_transaction(self):
            return self._in_transaction

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        dialect = SimpleNamespace(name="postgresql")

        def __init__(self):
            self.connection = FakeConnection()

        def connect(self):
            return self.connection

        def begin(self):
            return self.connection

    class FakeConfig:
        def __init__(self, path: str):
            self.path = path
            self.main_options: dict[str, str] = {}
            self.attributes: dict[str, object] = {}

        def set_main_option(self, key: str, value: str) -> None:
            self.main_options[key] = value

    upgrade_calls: list[tuple[FakeConfig, str]] = []

    def fake_upgrade(cfg, revision):
        upgrade_calls.append((cfg, revision))

    monkeypatch.setattr("alembic.config.Config", FakeConfig)
    monkeypatch.setattr("alembic.command.upgrade", fake_upgrade)
    monkeypatch.setattr(
        init_db_module,
        "_seed_reference_data",
        lambda conn: seeded.append(conn),
    )

    engine = FakeEngine()

    init_db_module.init_db(engine, retries=1, sleep_seconds=0)

    assert upgrade_calls, "Alembic upgrade should run"
    assert upgrade_calls[0][0].attributes["connection"] is engine.connection
    assert any("pg_advisory_lock(42424242)" in stmt for stmt in executed)
    assert any("pg_advisory_unlock(42424242)" in stmt for stmt in executed)
    assert not any("pg_advisory_xact_lock" in stmt for stmt in executed)
    assert seeded == [engine.connection]
