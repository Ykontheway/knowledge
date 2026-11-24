"""Independent SQLAlchemy metadata for opt-in mutation demo tables."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Uuid


class MutationBase(DeclarativeBase):
    """Base isolated from knowledge.storage.tables.Base."""


class MutationPreviewRow(MutationBase):
    __tablename__ = "mutation_previews"
    __table_args__ = (
        CheckConstraint("length(expected_checksum) = 64"),
        CheckConstraint("length(new_checksum) = 64"),
        Index("ix_mutation_previews_actor_scope", "actor_id", "scope_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    scope_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    expected_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    new_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    counts_json: Mapped[dict[str, Any]] = mapped_column("counts", JSON, nullable=False)
    diff_json: Mapped[list[dict[str, Any]]] = mapped_column("diff", JSON, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    expires_at: Mapped[str] = mapped_column(String(40), nullable=False)


class MutationCommandRow(MutationBase):
    __tablename__ = "mutation_commands"
    __table_args__ = (
        UniqueConstraint("scope_id", "actor_id", "idempotency_key"),
        CheckConstraint("id = idempotency_key"),
        CheckConstraint("length(new_checksum) = 64"),
        Index("ix_mutation_commands_actor_scope", "actor_id", "scope_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    scope_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    preview_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    previous_document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    new_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    changed: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_ids_json: Mapped[list[str]] = mapped_column("revision_ids", JSON, nullable=False)
    job_ids_json: Mapped[list[str]] = mapped_column("job_ids", JSON, nullable=False)
    evaluation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column("result", JSON, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


def create_mutation_schema(engine: Engine) -> None:
    """Explicit opt-in schema creation for mutation tables only."""

    MutationBase.metadata.create_all(engine)


def enable_schema(engine: Engine) -> None:
    create_mutation_schema(engine)


__all__ = [
    "MutationBase",
    "MutationCommandRow",
    "MutationPreviewRow",
    "create_mutation_schema",
    "enable_schema",
]
