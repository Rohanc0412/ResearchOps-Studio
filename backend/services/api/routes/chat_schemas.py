from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID | None = None
    title: str | None = Field(default=None, max_length=200)


class ConversationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    title: str | None = None
    created_at: datetime
    last_message_at: datetime | None = None


class ConversationListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ConversationOut]
    next_cursor: str | None = None


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    role: str
    type: str
    content_text: str
    content_json: dict | None = None
    created_at: datetime


class ChatMessageListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ChatMessageOut]
    next_cursor: str | None = None


class ChatSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    project_id: UUID | None = None
    message: str = Field(min_length=1)
    client_message_id: str = Field(min_length=1, max_length=200)
    llm_provider: str | None = Field(default=None, pattern="^(hosted)$")
    llm_model: str | None = Field(default=None, min_length=1)
    force_pipeline: bool = False
    stage_models: dict[str, str | None] | None = None


class ChatSendResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    user_message: ChatMessageOut
    assistant_message: ChatMessageOut | None = None
    pending_action: dict | None = None
    idempotent_replay: bool = False
