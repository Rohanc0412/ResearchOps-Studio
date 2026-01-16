from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


RunStatus = Literal["created", "queued", "running", "failed", "succeeded", "canceled"]
RunEventLevel = Literal["debug", "info", "warn", "error"]
ClaimVerdict = Literal["supported", "unsupported", "partially_supported", "needs_citation"]


class ProjectCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class ProjectOut(ApiModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    last_run_id: UUID | None = None
    last_run_status: RunStatus | None = None
    last_activity_at: datetime | None = None


class RunCreate(ApiModel):
    budgets_json: dict[str, Any] = Field(default_factory=dict)


class RunUpdateStatus(ApiModel):
    status: RunStatus
    current_stage: str | None = None
    failure_reason: str | None = None
    error_code: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunOut(ApiModel):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    status: RunStatus
    current_stage: str | None = None
    budgets_json: dict[str, Any]
    usage_json: dict[str, Any]
    failure_reason: str | None = None
    error_code: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RunEventCreate(ApiModel):
    stage: str | None = None
    level: RunEventLevel
    message: str = Field(min_length=1)
    payload_json: dict[str, Any] = Field(default_factory=dict)


class RunEventOut(ApiModel):
    id: UUID
    tenant_id: UUID
    run_id: UUID
    ts: datetime
    stage: str | None = None
    level: RunEventLevel
    message: str
    payload_json: dict[str, Any]


class SourceUpsert(ApiModel):
    canonical_id: str = Field(min_length=1, max_length=500)
    source_type: str = Field(min_length=1, max_length=50)
    title: str | None = None
    authors_json: list[Any] = Field(default_factory=list)
    year: int | None = None
    url: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class SourceOut(ApiModel):
    id: UUID
    tenant_id: UUID
    canonical_id: str
    source_type: str
    title: str | None = None
    authors_json: list[Any]
    year: int | None = None
    url: str | None = None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SnapshotCreate(ApiModel):
    content_type: str | None = None
    blob_ref: str = Field(min_length=1, max_length=1000)
    sha256: str = Field(min_length=1, max_length=64)
    size_bytes: int | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class SnapshotOut(ApiModel):
    id: UUID
    tenant_id: UUID
    source_id: UUID
    snapshot_version: int
    retrieved_at: datetime
    content_type: str | None = None
    blob_ref: str
    sha256: str
    size_bytes: int | None = None
    metadata_json: dict[str, Any]


class SnippetCreate(ApiModel):
    text: str = Field(min_length=1)
    char_start: int | None = None
    char_end: int | None = None
    token_count: int | None = None
    sha256: str | None = None
    risk_flags_json: dict[str, Any] = Field(default_factory=dict)


class SnippetOut(ApiModel):
    id: UUID
    tenant_id: UUID
    snapshot_id: UUID
    snippet_index: int
    text: str
    char_start: int | None = None
    char_end: int | None = None
    token_count: int | None = None
    sha256: str
    risk_flags_json: dict[str, Any]
    created_at: datetime


class ArtifactCreate(ApiModel):
    run_id: UUID | None = None
    type: str = Field(min_length=1, max_length=100)
    blob_ref: str = Field(min_length=1, max_length=1000)
    mime_type: str = Field(min_length=1, max_length=200)
    size_bytes: int | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ArtifactOut(ApiModel):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    run_id: UUID | None = None
    type: str
    blob_ref: str
    mime_type: str
    size_bytes: int | None = None
    metadata: dict[str, Any] = Field(
        default_factory=dict, validation_alias="metadata_json", serialization_alias="metadata"
    )
    created_at: datetime


class ClaimMapCreate(ApiModel):
    claim_text: str = Field(min_length=1)
    snippet_ids: list[UUID] = Field(default_factory=list)
    verdict: ClaimVerdict
    explanation: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ClaimMapOut(ApiModel):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    run_id: UUID
    claim_text: str
    claim_hash: str
    snippet_ids: list[UUID]
    verdict: ClaimVerdict
    explanation: str | None = None
    metadata_json: dict[str, Any]
    created_at: datetime
