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


def _find_repo_root(start: Path) -> Path | None:
    for base in (start, *start.parents):
        if (base / ".git").exists() or (base / "requirements.txt").exists():
            return base
    return None


def resolve_env_files() -> tuple[str, ...]:
    repo_root = _find_repo_root(Path(__file__).resolve())
    if repo_root is None:
        return ()
    env_file = repo_root / ".env"
    if not env_file.exists():
        return ()
    return (str(env_file.resolve()),)

