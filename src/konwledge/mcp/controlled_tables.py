"""仅显式 B6 runtime 创建的批准审计表；不注册到全局 storage.Base。"""

from uuid import UUID

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Uuid


class ControlledBase(DeclarativeBase):
    pass


class McpApprovalRow(ControlledBase):
    __tablename__ = "mcp_approvals"
    __table_args__ = (
        CheckConstraint("length(token_hash) = 64"),
        CheckConstraint("length(preview_binding_hash) = 64"),
        CheckConstraint("length(request_fingerprint) = 64"),
        CheckConstraint("(consumed_at IS NULL) = (command_id IS NULL)"),
        CheckConstraint("command_id IS NULL OR command_id = idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    scope_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(80), nullable=False)
    preview_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    preview_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    expires_at: Mapped[str] = mapped_column(String(40), nullable=False)
    consumed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    command_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
