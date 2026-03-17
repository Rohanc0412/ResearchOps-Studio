from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def _add_path(p: Path) -> None:
    sys.path.insert(0, str(p))


REPO_ROOT = Path(__file__).resolve().parents[1]

# Make monorepo trees importable without editable installs.
_add_path(REPO_ROOT / "services" / "api" / "src")
_add_path(REPO_ROOT / "services" / "orchestrator" / "src")
_add_path(REPO_ROOT / "services" / "workers" / "src")
_add_path(REPO_ROOT / "libs")
_add_path(REPO_ROOT / "libs" / "research_rules")
_add_path(REPO_ROOT / "data")
_add_path(REPO_ROOT)  # backend-local imports


@pytest.fixture()
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture()
def evidence_store():
    from contracts.evidence import EvidenceSnapshot, EvidenceSnippet
    from enforcement.evidence_validator import EvidenceStore
    from utils.hash import sha256_hex

    store = EvidenceStore()
    raw_text = "Example evidence text used for fixtures. It is immutable."
    snapshot = EvidenceSnapshot(
        snapshot_id="snap_001",
        source_meta="fixture://example",
        content_hash=sha256_hex(raw_text),
        captured_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        raw_text=raw_text,
    )
    store.add_snapshot(snapshot)

    start = 0
    end = 34
    snippet = EvidenceSnippet(
        snippet_id="snip_001",
        snapshot_id="snap_001",
        start_char=start,
        end_char=end,
        snippet_text=raw_text[start:end],
        injection_risk_flag=False,
    )
    store.add_snippet(snippet)
    return store


@pytest.fixture()
def sqlite_engine(tmp_path: Path) -> Engine:
    db_path = tmp_path / "test.db"
    return create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
