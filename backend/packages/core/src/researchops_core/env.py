from __future__ import annotations

from pathlib import Path


def resolve_env_file() -> str | None:
    cwd = Path.cwd().resolve()
    for base in (cwd, *cwd.parents):
        candidate = base / ".env"
        if candidate.exists():
            return str(candidate)
    for base in Path(__file__).resolve().parents:
        candidate = base / ".env"
        if candidate.exists():
            return str(candidate)
    return None

