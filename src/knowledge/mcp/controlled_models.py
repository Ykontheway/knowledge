"""B6 显式协议白名单；批准签发仅供带外 CLI，不是 MCP 工具。"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, StrictBool, field_validator

from knowledge.mcp.models import Hash, McpModel
from knowledge.mutations.models import ContentType, DiffKind, EvaluationStatus

Token = Annotated[str, Field(strict=True, min_length=1, max_length=512, repr=False)]


class ControlledModel(McpModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )


class EmptyInput(ControlledModel):
    pass


class GetMutationDocumentInput(ControlledModel):
    document_id: UUID


class PreviewDocumentUpdateInput(ControlledModel):
    source_id: UUID
    document_id: UUID
    expected_checksum: Hash
    text: str = Field(strict=True, max_length=65536)

    @field_validator("text")
    @classmethod
    def utf8_bound(cls, value: str) -> str:
        try:
            if len(value.encode("utf-8", errors="strict")) <= 65536:
                return value
        except UnicodeError:
            pass
        raise ValueError("mcp_mutation_text_invalid")


class ApplyDocumentUpdateInput(ControlledModel):
    preview_id: UUID
    confirmation_token: Token
    idempotency_key: UUID
    approval_token: Token


class GetMutationCommandInput(ControlledModel):
    command_id: UUID


class McpSourceSessionDTO(ControlledModel):
    source_id: UUID
    document_id: UUID
    checksum: Hash
    content_type: ContentType
    label: str = Field(strict=True, min_length=1, max_length=120)


class McpSessionDTO(ControlledModel):
    scope_id: UUID
    actor_id: str = Field(strict=True, min_length=1, max_length=80)
    role: Literal["demo_editor"] = "demo_editor"
    capabilities: tuple[Literal["document.update"], ...] = ("document.update",)
    sources: tuple[McpSourceSessionDTO, ...]


class McpDocumentDTO(ControlledModel):
    scope_id: UUID
    source_id: UUID
    document_id: UUID
    checksum: Hash
    content_type: ContentType
    text: str = Field(strict=True, max_length=65536)

    @field_validator("text")
    @classmethod
    def utf8_bound(cls, value: str) -> str:
        return PreviewDocumentUpdateInput.utf8_bound(value)


class McpDiffCounts(ControlledModel):
    added: int = Field(strict=True, ge=0)
    modified: int = Field(strict=True, ge=0)
    moved: int = Field(strict=True, ge=0)
    unchanged: int = Field(strict=True, ge=0)
    removed: int = Field(strict=True, ge=0)


class McpDiffEntry(ControlledModel):
    kind: DiffKind
    old_text: str | None = Field(strict=True)
    new_text: str | None = Field(strict=True)


class McpPreviewDTO(ControlledModel):
    preview_id: UUID
    scope_id: UUID
    source_id: UUID
    document_id: UUID
    expected_checksum: Hash
    new_checksum: Hash
    expires_at: AwareDatetime
    confirmation_token: str = Field(strict=True, min_length=43, max_length=128, repr=False)
    changed: StrictBool
    counts: McpDiffCounts
    diff: tuple[McpDiffEntry, ...] = Field(max_length=200)


class McpCommandDTO(ControlledModel):
    command_id: UUID
    scope_id: UUID
    actor_id: str = Field(strict=True, min_length=1, max_length=80)
    source_id: UUID
    previous_document_id: UUID
    document_id: UUID
    new_checksum: Hash
    committed: Literal[True] = True
    changed: StrictBool
    revision_ids: tuple[UUID, ...]
    job_ids: tuple[UUID, ...]
    evaluation_status: EvaluationStatus

    @field_validator("committed", mode="before")
    @classmethod
    def true_boolean(cls, value: object) -> object:
        if value is not True:
            raise ValueError("mcp_mutation_result_invalid")
        return value


class ApprovalReviewDTO(ControlledModel):
    preview_id: UUID
    idempotency_key: UUID
    scope_id: UUID
    actor_id: str = Field(strict=True, min_length=1, max_length=80)
    source_id: UUID
    document_id: UUID
    expected_checksum: Hash
    new_checksum: Hash
    expires_at: AwareDatetime
    counts: McpDiffCounts
    diff: tuple[McpDiffEntry, ...] = Field(max_length=200)
    approval_phrase: str = Field(strict=True, max_length=256)


class ApprovalGrantDTO(ControlledModel):
    approval_id: UUID
    scope_id: UUID
    actor_id: str = Field(strict=True, min_length=1, max_length=80)
    preview_id: UUID
    idempotency_key: UUID
    expires_at: AwareDatetime
    approval_token: Token


CONTROLLED_TOOL_INPUTS: dict[str, tuple[type[McpModel], str]] = {
    "get_mutation_session": (EmptyInput, "读取受控演示编辑范围与当前文档标识。"),
    "get_mutation_document": (GetMutationDocumentInput, "读取 allowlist 当前文档完整正文。"),
    "preview_document_update": (PreviewDocumentUpdateInput, "审计正文更新预览；不会提交知识。"),
    "apply_document_update": (
        ApplyDocumentUpdateInput,
        "持带外批准提交预览；未知结果仅 GET 原 command key 回查。",
    ),
    "get_mutation_command": (GetMutationCommandInput, "只读回查原 command key 的持久结果。"),
}
CONTROLLED_TOOL_OUTPUTS: dict[str, type[McpModel]] = {
    "get_mutation_session": McpSessionDTO,
    "get_mutation_document": McpDocumentDTO,
    "preview_document_update": McpPreviewDTO,
    "apply_document_update": McpCommandDTO,
    "get_mutation_command": McpCommandDTO,
}
CONTROLLED_TOOL_ANNOTATIONS: dict[str, dict[str, bool]] = {
    name: {
        "readOnlyHint": name.startswith("get_"),
        "destructiveHint": name == "apply_document_update",
        "idempotentHint": name != "preview_document_update",
        "openWorldHint": False,
    }
    for name in CONTROLLED_TOOL_INPUTS
}
