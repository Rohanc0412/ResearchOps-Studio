from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv


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


def resolve_repo_root(start: Path | None = None) -> Path | None:
    if start is None:
        start = Path(__file__).resolve()
    return _find_repo_root(start)


def resolve_root_env_file(start: Path | None = None) -> Path | None:
    repo_root = resolve_repo_root(start)
    if repo_root is None:
        return None
    env_file = repo_root / ".env"
    if not env_file.exists():
        return None
    return env_file.resolve()


def load_root_env(start: Path | None = None) -> Path | None:
    env_file = resolve_root_env_file(start)
    if env_file is None:
        return None
    load_dotenv(env_file, override=False)
    return env_file

