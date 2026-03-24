from __future__ import annotations

from pathlib import Path


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

