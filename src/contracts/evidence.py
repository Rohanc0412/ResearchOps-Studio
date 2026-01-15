from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from src.contracts._base import StrictBaseModel

SnapshotId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=64,
        pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{2,63}$",
    ),
]

SnippetId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=64,
        pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{2,63}$",
    ),
]

Sha256Hex = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"),
]


class EvidenceRef(StrictBaseModel):
    snapshot_id: SnapshotId
    snippet_id: SnippetId
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _offsets_consistent(self) -> "EvidenceRef":
        if (self.start_char is None) ^ (self.end_char is None):
            raise ValueError("EvidenceRef offsets must include both start_char and end_char, or neither")
        if self.start_char is not None and self.end_char is not None and self.start_char >= self.end_char:
            raise ValueError("EvidenceRef offsets must satisfy start_char < end_char")
        return self


class EvidenceSnapshot(StrictBaseModel):
    snapshot_id: SnapshotId
    source_meta: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000)]
    content_hash: Sha256Hex
    captured_at: AwareDatetime
    raw_text: Annotated[str, StringConstraints(min_length=1, max_length=5_000_000)]

    @field_validator("captured_at", mode="before")
    @classmethod
    def _coerce_datetime(cls, value: object) -> object:
        if isinstance(value, datetime):
            return value
        return value


class EvidenceSnippet(StrictBaseModel):
    snippet_id: SnippetId
    snapshot_id: SnapshotId
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    snippet_text: Annotated[str, StringConstraints(min_length=1, max_length=200_000)]
    injection_risk_flag: bool = False

    @model_validator(mode="after")
    def _ranges_consistent(self) -> "EvidenceSnippet":
        if self.start_char >= self.end_char:
            raise ValueError("EvidenceSnippet requires start_char < end_char")
        return self

