from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, populate_by_name=True)


RunStatus = Literal["created", "queued", "running", "failed", "succeeded", "canceled"]
RunEventLevel = Literal["debug", "info", "warn", "error"]


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


class RunEventOut(ApiModel):
    id: UUID
    tenant_id: UUID
    run_id: UUID
    ts: datetime
    stage: str | None = None
    level: RunEventLevel
    message: str
    payload_json: dict[str, Any]


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


