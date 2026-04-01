from __future__ import annotations

import importlib.util
from pathlib import Path
import configparser


def _migration_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "backend" / "data" / "db" / "alembic" / "versions"


def _load_module(module_name: str, relative_path: str):
    root = Path(__file__).resolve().parents[3]
    module_path = root / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_alembic_ini_uses_os_path_separator():
    config_path = Path(__file__).resolve().parents[3] / "backend" / "alembic.ini"
    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf-8")

    assert parser.get("alembic", "path_separator") == "os"


def test_alembic_versions_contains_single_latest_schema_script():
    migration_files = sorted(path.name for path in _migration_dir().glob("*.py"))

    assert migration_files == ["20260330_0002_latest_schema_snapshot.py"]


def test_single_migration_is_root_snapshot(monkeypatch):
    module = _load_module(
        "migration_latest_schema",
        "backend/data/db/alembic/versions/20260330_0002_latest_schema_snapshot.py",
    )

    captured: dict[str, object] = {}

    class FakeBind:
        def execute(self, _statement):
            return None

    monkeypatch.setattr(module.op, "get_bind", lambda: FakeBind())

    def fake_create_all(bind):
        captured["bind"] = bind

    monkeypatch.setattr(module.Base.metadata, "create_all", fake_create_all)

    assert module.down_revision is None

    module.upgrade()

    assert "bind" in captured
