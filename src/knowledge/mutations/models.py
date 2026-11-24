"""Frozen DTOs and internal values for the opt-in mutation demo API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MANIFEST_KIND: Literal["knowledge-mutation-demo-v1"] = "knowledge-mutation-demo-v1"
MAX_REQUEST_BYTES = 128 * 1024
MAX_TEXT_BYTES = 64 * 1024
PREVIEW_TTL_SECONDS = 300


@dataclass(frozen=True, slots=True)
class MutationScope:
    scope_id: UUID
    database_path: Path
    allowed_source_ids: tuple[UUID, ...]


class MutationError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class MutationModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        str_strip_whitespace=False,
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )


class ContentType(StrEnum):
    MARKDOWN = "markdown"
    TEXT = "text"


class DiffKind(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    MOVED = "moved"
    UNCHANGED = "unchanged"
    REMOVED = "removed"


class EvaluationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    PENDING = "pending"
    NOT_TRIGGERED = "not_triggered"
    UNAVAILABLE = "unavailable"


class SourceSessionDTO(MutationModel):
    source_id: UUID
    document_id: UUID
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_type: ContentType
    label: str = Field(min_length=1, max_length=120)


class SessionDTO(MutationModel):
    scope_id: UUID
    actor_id: str
    role: Literal["demo_editor"] = "demo_editor"
    capabilities: tuple[Literal["document.update"], ...]
    sources: tuple[SourceSessionDTO, ...]


class DocumentDTO(MutationModel):
    scope_id: UUID
    source_id: UUID
    document_id: UUID
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_type: ContentType
    text: str


class PreviewRequest(MutationModel):
    scope_id: UUID
    source_id: UUID
    document_id: UUID
    expected_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str

    @field_validator("text")
    @classmethod
    def text_utf8_bound(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError("text exceeds maximum UTF-8 size")
        return value


class DiffCounts(MutationModel):
    added: int = Field(ge=0)
    modified: int = Field(ge=0)
    moved: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    removed: int = Field(ge=0)


class DiffEntry(MutationModel):
    kind: DiffKind
    old_text: str | None
    new_text: str | None


class PreviewDTO(MutationModel):
    preview_id: UUID
    scope_id: UUID
    source_id: UUID
    document_id: UUID
    expected_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    new_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at: datetime
    confirmation_token: str = Field(min_length=43, max_length=128)
    changed: bool
    counts: DiffCounts
    diff: tuple[DiffEntry, ...]


class CommandRequest(MutationModel):
    preview_id: UUID
    confirmation_token: str = Field(min_length=1, max_length=512)
    idempotency_key: UUID
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def require_explicit_confirmation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("confirmed must be the JSON boolean true")
        return value


class CommandDTO(MutationModel):
    command_id: UUID
    scope_id: UUID
    actor_id: str
    source_id: UUID
    previous_document_id: UUID
    document_id: UUID
    new_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    committed: Literal[True] = True
    changed: bool
    revision_ids: tuple[UUID, ...]
    job_ids: tuple[UUID, ...]
    evaluation_status: EvaluationStatus


class MutationSchemaBundle(MutationModel):
    session: dict[str, object]
    document: dict[str, object]
    preview_request: dict[str, object]
    preview: dict[str, object]
    command_request: dict[str, object]
    command: dict[str, object]

    @classmethod
    def build(cls) -> MutationSchemaBundle:
        return cls(
            session=SessionDTO.model_json_schema(),
            document=DocumentDTO.model_json_schema(),
            preview_request=PreviewRequest.model_json_schema(),
            preview=PreviewDTO.model_json_schema(),
            command_request=CommandRequest.model_json_schema(),
            command=CommandDTO.model_json_schema(),
        )


class MutationManifest(MutationModel):
    kind: Literal["knowledge-mutation-demo-v1"]
    scope_id: UUID
    database: str = Field(min_length=1)
    allowed_source_ids: tuple[UUID, ...] = Field(min_length=1, max_length=16)
    created_at: datetime

    @field_validator("database")
    @classmethod
    def reject_bad_database_string(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("database must be a regular relative path")
        if path.name != "knowledge.db":
            raise ValueError("database marker is invalid")
        return value

    @field_validator("created_at", mode="before")
    @classmethod
    def parse_isoz(cls, value: object) -> object:
        if isinstance(value, str) and value.endswith("Z"):
            return value[:-1] + "+00:00"
        return value

    @model_validator(mode="after")
    def unique_sources(self) -> MutationManifest:
        if len(set(self.allowed_source_ids)) != len(self.allowed_source_ids):
            raise ValueError("duplicate source ids")
        return self
