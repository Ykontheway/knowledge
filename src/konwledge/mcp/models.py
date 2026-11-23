"""MCP 输入与显式输出白名单; 不复用带定位符的领域/管理响应。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Annotated, Generic, Literal, Self, TypeVar
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from konwledge.domain.models import KnowledgeUnitStatus
from konwledge.lifecycle.diff import UnitChangeKind

Hash = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
Score = Annotated[float, Field(allow_inf_nan=False)]


class McpModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class PageQuery(McpModel):
    limit: int = Field(default=20, strict=True, ge=1, le=100)
    offset: int = Field(default=0, strict=True, ge=0, le=100_000)


class SearchInput(McpModel):
    """mode/include_stale 不属于输入, 由服务固定为 lexical/False。"""

    query: str = Field(strict=True, min_length=1, max_length=4096)
    top_k: int = Field(default=5, strict=True, ge=1, le=100)
    candidate_limit: int | None = Field(default=None, strict=True, ge=1, le=1000)
    rrf_k: int = Field(default=60, strict=True, ge=1, le=1000)
    at: AwareDatetime | None = Field(default=None)
    source_id: UUID | None = None

    @field_validator("at", mode="before")
    @classmethod
    def strict_datetime(cls, value: object) -> object:
        # Python 服务调用可传 datetime；协议仅接受带时区的日期时间字符串。
        if value is None or isinstance(value, datetime):
            return value
        if not isinstance(value, str) or re.match(r"^\d{4}-\d{2}-\d{2}[Tt ]", value) is None:
            raise ValueError("mcp_datetime_invalid")
        return value

    @field_validator("query")
    @classmethod
    def nonblank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("mcp_query_invalid")
        return value

    @model_validator(mode="after")
    def candidate_budget(self) -> Self:
        if self.candidate_limit is not None and self.candidate_limit < self.top_k:
            raise ValueError("mcp_candidate_limit_invalid")
        return self


class BuildContextInput(SearchInput):
    """max_chars 限制整块证据正文的字符总数; 不截断 exact evidence。"""

    max_chars: int = Field(default=8000, strict=True, ge=0, le=100_000)
    max_units: int = Field(default=10, strict=True, ge=1, le=100)


class GetEvidenceInput(McpModel):
    unit_id: UUID


class GetLineageInput(PageQuery):
    lineage_id: UUID


class CompareDocumentsInput(PageQuery):
    old_document_id: UUID
    new_document_id: UUID


class UnitDTO(McpModel):
    unit_id: UUID
    lineage_id: UUID
    document_id: UUID
    source_id: UUID
    ordinal: int = Field(ge=0)
    status: KnowledgeUnitStatus
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    content_hash: Hash


class EvidenceDTO(McpModel):
    unit_id: UUID
    lineage_id: UUID
    document_id: UUID
    source_id: UUID
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    text: str = Field(strict=True, min_length=1)
    content_hash: Hash
    document_checksum: Hash
    revision_ids: tuple[UUID, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def exact_span(self) -> Self:
        if not self.text.strip() or self.end_char - self.start_char != len(self.text):
            raise ValueError("historical_evidence_invalid")
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.content_hash:
            raise ValueError("historical_evidence_invalid")
        return self


class SearchHitDTO(EvidenceDTO):
    status: Literal[KnowledgeUnitStatus.ACTIVE] = KnowledgeUnitStatus.ACTIVE
    score: Score
    lexical_rank: int = Field(gt=0)
    lexical_score: Score


class SearchDTO(McpModel):
    mode: Literal["lexical"] = "lexical"
    include_stale: Literal[False] = False
    evaluated_at: AwareDatetime
    top_k: int = Field(ge=1, le=100)
    candidate_limit: int = Field(ge=1, le=1000)
    rrf_k: int = Field(ge=1, le=1000)
    hits: tuple[SearchHitDTO, ...]


class SanitizedEvidenceBlock(SearchHitDTO):
    label: str = Field(strict=True, pattern=r"^\[[1-9][0-9]*\]$")


class SkippedEvidence(McpModel):
    unit_id: UUID
    reason: Literal["duplicate", "overlap", "budget", "max_units"]


class ContextPacket(McpModel):
    mode: Literal["lexical"] = "lexical"
    include_stale: Literal[False] = False
    evaluated_at: AwareDatetime
    max_chars: int = Field(ge=0, le=100_000)
    max_units: int = Field(ge=1, le=100)
    used_chars: int = Field(ge=0)
    blocks: tuple[SanitizedEvidenceBlock, ...]
    skipped: tuple[SkippedEvidence, ...]

    @model_validator(mode="after")
    def packet_budget(self) -> Self:
        if self.used_chars != sum(len(block.text) for block in self.blocks):
            raise ValueError("mcp_context_budget_invalid")
        if self.used_chars > self.max_chars or len(self.blocks) > self.max_units:
            raise ValueError("mcp_context_budget_invalid")
        if [block.label for block in self.blocks] != [
            f"[{index}]" for index in range(1, len(self.blocks) + 1)
        ]:
            raise ValueError("mcp_context_labels_invalid")
        return self


T = TypeVar("T")


class Page(McpModel, Generic[T]):
    items: tuple[T, ...]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0, le=100_000)


class LineageDTO(McpModel):
    lineage_id: UUID
    versions: Page[UnitDTO]


class DiffItem(McpModel):
    kind: UnitChangeKind
    lineage_id: UUID
    old: UnitDTO | None
    new: UnitDTO | None


class DiffCounts(McpModel):
    added: int = Field(ge=0)
    modified: int = Field(ge=0)
    moved: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    removed: int = Field(ge=0)


class DocumentDiffDTO(McpModel):
    source_id: UUID
    old_document_id: UUID
    new_document_id: UUID
    counts: DiffCounts
    changes: Page[DiffItem]
