from __future__ import annotations

import sys
from pathlib import Path

import pytest
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


@pytest.fixture()
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture()
def sqlite_engine(tmp_path: Path) -> AsyncEngine:
    db_path = tmp_path / "test.db"
    return create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
