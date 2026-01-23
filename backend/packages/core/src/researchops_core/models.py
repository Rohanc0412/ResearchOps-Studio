from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)


class RunStatus(str, Enum):
    created = "created"
    queued = "queued"
    running = "running"
    failed = "failed"
    succeeded = "succeeded"


class Run(StrictModel):
    id: UUID
    tenant_id: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None


class Artifact(StrictModel):
    id: UUID
    run_id: UUID
    artifact_type: str
    payload_json: dict[str, Any]
    created_at: datetime


class CreateRunRequest(StrictModel):
    tenant_id: str = Field(min_length=1, max_length=200)


class ArtifactResponse(StrictModel):
    id: UUID
    artifact_type: str
    created_at: datetime


class RunResponse(StrictModel):
    id: UUID
    tenant_id: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None
    artifacts: list[ArtifactResponse] = Field(default_factory=list)

