from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path


def now_utc() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


def env_int(name: str, default: int, *, min_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            value = default
    if min_value is not None:
        return max(min_value, value)
    return value


def env_float(name: str, default: float, *, min_value: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = float(raw)
        except ValueError:
            value = default
    if min_value is not None:
        return max(min_value, value)
    return value


def env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name, "").strip().lower()
    if val in {"1", "true", "yes", "on"}:
        return True
    if val in {"0", "false", "no", "off"}:
        return False
    return default


def env_optional_int(name: str, *, min_value: int | None = None) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if min_value is not None and value < min_value:
        return min_value
    return value


def resolve_env_files() -> tuple[str, ...]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        resolved = str(path.resolve())
        if resolved in seen or not path.exists():
            return
        seen.add(resolved)
        candidates.append(resolved)

    cwd = Path.cwd().resolve()
    parent_candidates = [cwd, *cwd.parents]
    for base in reversed(parent_candidates):
        add(base / ".env")

    module_parents = list(Path(__file__).resolve().parents)
    for base in reversed(module_parents):
        add(base / ".env")

    return tuple(candidates)

