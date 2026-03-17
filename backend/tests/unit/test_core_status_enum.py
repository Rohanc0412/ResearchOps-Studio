from __future__ import annotations

from core.models import RunStatus


def test_run_status_enum_values() -> None:
    assert {s.value for s in RunStatus} == {"created", "queued", "running", "failed", "succeeded"}

