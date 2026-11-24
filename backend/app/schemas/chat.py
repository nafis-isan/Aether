from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ModelRole = Literal["general", "coding"]


class ChatRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    message: str = Field(min_length=1, max_length=12_000)
    conversation_id: UUID | None = None
    model_role: ModelRole = "general"

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message cannot be blank")
        return value


class ConversationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def reject_blank_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("Conversation title cannot be blank")
        return title


class RunRedirectRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12_000)

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message cannot be blank")
        return value


class ChatResponse(BaseModel):
    conversation_id: UUID
    reply: str
    model: str
    created_at: datetime
    run_id: UUID | None = None
    selected_agent: str | None = None
    pending_approval_id: UUID | None = None
    citations: list[dict] = Field(default_factory=list)


class ConversationRead(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class MessageRead(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    metadata: dict | None = Field(default=None, validation_alias="metadata_json", serialization_alias="metadata")
