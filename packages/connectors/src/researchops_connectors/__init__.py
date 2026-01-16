"""
Placeholder connector interfaces.

Part 2 provides structure only; implementations land in later parts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class Connector(Protocol):
    name: str

    def healthcheck(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class ConnectorResult:
    ok: bool
    detail: str | None = None

