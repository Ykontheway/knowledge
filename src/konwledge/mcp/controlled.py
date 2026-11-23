"""受控正文更新：B4 单事务核心 + 带外批准；不依赖 MCP SDK。"""

from __future__ import annotations

import re
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeVar
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, create_engine, event, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from konwledge.domain import SourceKind
from konwledge.mcp.controlled_models import (
    CONTROLLED_TOOL_ANNOTATIONS,
    CONTROLLED_TOOL_INPUTS,
    CONTROLLED_TOOL_OUTPUTS,
    ApplyDocumentUpdateInput,
    ApprovalGrantDTO,
    ApprovalReviewDTO,
    EmptyInput,
    GetMutationCommandInput,
    GetMutationDocumentInput,
    McpCommandDTO,
    McpDiffCounts,
    McpDiffEntry,
    McpDocumentDTO,
    McpPreviewDTO,
    McpSessionDTO,
    McpSourceSessionDTO,
    PreviewDocumentUpdateInput,
)
from konwledge.mcp.controlled_safety import ScopeGuard
from konwledge.mcp.controlled_tables import ControlledBase, McpApprovalRow
from konwledge.mcp.models import McpModel
from konwledge.mcp.service import McpReadError
from konwledge.mutations.models import (
    CommandDTO,
    ContentType,
    MutationError,
    MutationScope,
    PreviewRequest,
)
from konwledge.mutations.service import MutationService, _canonical_hash, _token_hash, _utc
from konwledge.mutations.tables import MutationCommandRow, MutationPreviewRow
from konwledge.storage import SessionFactory, UnitOfWork, create_session_factory
from konwledge.storage.full_text import fts_document

_SAFE_B4_CODES = frozenset(
    {
        "mutation_startup_invalid",
        "document_not_found",
        "historical_document",
        "source_not_allowed",
        "source_not_found",
        "checksum_conflict",
        "diff_too_large",
        "text_too_large",
        "document_uneditable",
        "mutation_schema_unavailable",
        "idempotency_conflict",
        "preview_not_found",
        "confirmation_mismatch",
        "preview_corrupt",
        "preview_expired",
        "auto_evaluation_required",
        "write_conflict",
        "scope_mismatch",
        "server_clock_invalid",
        "command_not_found",
    }
)
_SAFE_CODES = frozenset(
    {
        "mcp_mutation_scope_invalid",
        "mcp_mutation_input_invalid",
        "mcp_mutation_unavailable",
        "mcp_mutation_outcome_unknown",
        "mcp_approval_required",
        "mcp_approval_expired",
        "mcp_approval_conflict",
        "mcp_approval_phrase_mismatch",
    }
) | frozenset("mcp_" + code for code in _SAFE_B4_CODES)


class McpControlledError(McpReadError):
    def __init__(self, code: str, status: int) -> None:
        if code not in _SAFE_CODES or status not in {400, 403, 404, 409, 410, 413, 500, 503}:
            code, status = "mcp_mutation_unavailable", 503
        super().__init__(status, code)


T = TypeVar("T", bound=McpModel)
_EMPTY_INPUT = EmptyInput()


def _input(query: T, model: type[T]) -> T:
    # model_copy 不验证；服务边界再验证，避免 Python 调用绕过 DTO。
    if not isinstance(query, model):
        raise McpControlledError("mcp_mutation_input_invalid", 400)
    return model.model_validate(query.model_dump(warnings=False))


def _request_fingerprint(
    scope: MutationScope, actor: str, preview: UUID, key: UUID, token_hash: str
) -> str:
    # 与 B4 apply_command 完全相同，不将 approval secret 纳入 B4 对外合同。
    return _canonical_hash(
        {
            "scope_id": str(scope.scope_id),
            "actor_id": actor,
            "preview_id": str(preview),
            "token_hash": token_hash,
            "idempotency_key": str(key),
            "confirmed": True,
        }
    )


class _FileMutationService(MutationService):
    def _require_editable_source(self, uow: UnitOfWork, source_id: UUID) -> None:
        super()._require_editable_source(uow, source_id)
        source = uow.sources.get(source_id)
        if source is None or source.kind is not SourceKind.FILE:
            raise McpControlledError("mcp_source_not_allowed", 403)


class _ReadMutationService(_FileMutationService):
    def __init__(self, factory: SessionFactory, scope: MutationScope, actor: str) -> None:
        # 不调用 MutationService.__init__，因此不安装 AutoEvaluationService hooks。
        self._session_factory = factory
        self._scope = scope
        self._actor_id = actor
        self._clock = lambda: datetime.now(UTC)
        self._validate_startup()


@dataclass
class _ApplyContext:
    request: ApplyDocumentUpdateInput
    commit_attempted: bool = False


class _GuardedMutationService(_FileMutationService):
    def __init__(
        self, factory: SessionFactory, scope: MutationScope, owner: McpControlledService
    ) -> None:
        self._owner = owner
        super().__init__(factory, scope, actor_id=owner.actor)

    def _commit_command(self, uow: UnitOfWork, command_id: UUID, request_fingerprint: str) -> None:
        context = self._owner._active.get()
        if context is None or command_id != context.request.idempotency_key:
            raise McpControlledError("mcp_approval_required", 403)
        grant = self._owner._check_grant(uow, context.request, replay=False)
        if grant.request_fingerprint != request_fingerprint:
            raise McpControlledError("mcp_approval_conflict", 409)
        grant.consumed_at = _utc(self._clock()).isoformat()
        grant.command_id = command_id
        # 此 flush/commit 与 B4 知识、revision、command、outbox 同一个 BEGIN IMMEDIATE。
        uow.session.flush()
        context.commit_attempted = True
        try:
            super()._commit_command(uow, command_id, request_fingerprint)
        except Exception:
            # B4 已验证提交失败时，不能把已知 rollback 伪装为未知提交。
            try:
                with self._owner._reader._session_factory() as session:
                    row = session.get(MutationCommandRow, command_id)
                    if row is None:
                        context.commit_attempted = False
            except Exception:
                pass  # 真正无法读取持久结果时保留 unknown，绝不重试 apply。
            raise

    def _command_result(self, uow: UnitOfWork, row: MutationCommandRow) -> CommandDTO:
        context = self._owner._active.get()
        if context is not None:
            self._owner._check_grant(uow, context.request, replay=True)
        return super()._command_result(uow, row)

    def get_command(self, command_id: UUID) -> CommandDTO:
        # B4 提交后的结果读取同样走无 hooks 的独立 RO factory。
        return self._owner._reader.get_command(command_id)


class McpControlledService:
    """实例只能由通过 scope preflight 的 runtime 提供。

    review/issue 是 operator API，不在工具注册表中。模型不能自行授予批准。
    同 OS owner 可访问终端和批准文件；本轮不声称生产 SSO 或人类密码学证明。
    """

    def __init__(
        self, guard: ScopeGuard, reader: _ReadMutationService, writer_factory: SessionFactory
    ) -> None:
        self._guard = guard
        self._reader = reader
        self.actor = reader.actor_id
        self.scope = guard.scope
        self._active: ContextVar[_ApplyContext | None] = ContextVar(
            f"mcp_approval_request_{id(self)}", default=None
        )
        self._approval_factory = sessionmaker(
            bind=writer_factory.kw["bind"], autoflush=False, expire_on_commit=False
        )
        self._writer = _GuardedMutationService(writer_factory, self.scope, self)

    @contextmanager
    def _operation(self) -> Iterator[None]:
        try:
            self._guard.validate()
            self._reader._validate_startup()
            yield
        except McpControlledError:
            raise
        except MutationError as error:
            raise McpControlledError("mcp_" + error.code, error.status_code) from None
        except ValidationError:
            raise McpControlledError("mcp_mutation_input_invalid", 400) from None
        except Exception:
            raise McpControlledError("mcp_mutation_unavailable", 503) from None

    def get_mutation_session(self, query: EmptyInput = _EMPTY_INPUT) -> McpSessionDTO:
        with self._operation():
            _input(query, EmptyInput)
            return McpSessionDTO(
                scope_id=self.scope.scope_id,
                actor_id=self.actor,
                sources=tuple(
                    McpSourceSessionDTO(
                        source_id=value.source_id,
                        document_id=value.document_id,
                        checksum=value.checksum,
                        content_type=value.content_type,
                        # 不传 source.title，固定标签消除 URI/control/bidi 暴露。
                        label="演示文档",
                    )
                    for value in self._reader.list_sources()
                ),
            )

    def get_mutation_document(self, query: GetMutationDocumentInput) -> McpDocumentDTO:
        with self._operation():
            query = _input(query, GetMutationDocumentInput)
            source_id, document, content = self._reader.get_document_text(query.document_id)
            return McpDocumentDTO(
                scope_id=self.scope.scope_id,
                source_id=source_id,
                document_id=document.id,
                checksum=document.checksum,
                content_type=ContentType(document.content_type.value),
                text=content,
            )

    def preview_document_update(self, query: PreviewDocumentUpdateInput) -> McpPreviewDTO:
        with self._operation():
            query = _input(query, PreviewDocumentUpdateInput)
            value = self._writer.create_preview(
                PreviewRequest(
                    scope_id=self.scope.scope_id,
                    source_id=query.source_id,
                    document_id=query.document_id,
                    expected_checksum=query.expected_checksum,
                    text=query.text,
                )
            )
            return McpPreviewDTO(
                preview_id=value.preview_id,
                scope_id=value.scope_id,
                source_id=value.source_id,
                document_id=value.document_id,
                expected_checksum=value.expected_checksum,
                new_checksum=value.new_checksum,
                expires_at=value.expires_at,
                confirmation_token=value.confirmation_token,
                changed=value.changed,
                counts=McpDiffCounts(**value.counts.model_dump()),
                diff=tuple(
                    McpDiffEntry(kind=item.kind, old_text=item.old_text, new_text=item.new_text)
                    for item in value.diff
                ),
            )

    @staticmethod
    def _command_dto(value: CommandDTO) -> McpCommandDTO:
        return McpCommandDTO(
            command_id=value.command_id,
            scope_id=value.scope_id,
            actor_id=value.actor_id,
            source_id=value.source_id,
            previous_document_id=value.previous_document_id,
            document_id=value.document_id,
            new_checksum=value.new_checksum,
            committed=value.committed,
            changed=value.changed,
            revision_ids=value.revision_ids,
            job_ids=value.job_ids,
            evaluation_status=value.evaluation_status,
        )

    def get_mutation_command(self, query: GetMutationCommandInput) -> McpCommandDTO:
        with self._operation():
            query = _input(query, GetMutationCommandInput)
            return self._command_dto(self._reader.get_command(query.command_id))

    def _review(
        self, uow: UnitOfWork, preview_id: UUID, key: UUID
    ) -> tuple[MutationPreviewRow, ApprovalReviewDTO]:
        row = uow.session.get(MutationPreviewRow, preview_id)
        if row is None or row.scope_id != self.scope.scope_id or row.actor_id != self.actor:
            raise McpControlledError("mcp_preview_not_found", 404)
        self._reader._validate_preview(row)
        expires = _utc(datetime.fromisoformat(row.expires_at))
        if _utc(self._writer._clock()) >= expires:
            raise McpControlledError("mcp_preview_expired", 410)
        document = self._reader._current_document(uow, row.source_id, row.document_id)
        self._reader._document_text(uow, document)
        if document.checksum != row.expected_checksum:
            raise McpControlledError("mcp_checksum_conflict", 409)
        if not self._reader._auto_evaluation_enabled(uow):
            raise McpControlledError("mcp_auto_evaluation_required", 409)
        return row, ApprovalReviewDTO(
            preview_id=row.id,
            idempotency_key=key,
            scope_id=row.scope_id,
            actor_id=row.actor_id,
            source_id=row.source_id,
            document_id=row.document_id,
            expected_checksum=row.expected_checksum,
            new_checksum=row.new_checksum,
            expires_at=expires,
            counts=McpDiffCounts.model_validate(row.counts_json),
            diff=tuple(McpDiffEntry.model_validate(item) for item in row.diff_json),
            approval_phrase=f"APPROVE {row.id} {key} {row.new_checksum}",
        )

    def review_approval(self, preview_id: UUID, idempotency_key: UUID) -> ApprovalReviewDTO:
        with self._operation(), UnitOfWork(self._reader._session_factory) as uow:
            if not isinstance(preview_id, UUID) or not isinstance(idempotency_key, UUID):
                raise McpControlledError("mcp_mutation_input_invalid", 400)
            return self._review(uow, preview_id, idempotency_key)[1]

    def issue_approval(
        self, preview_id: UUID, idempotency_key: UUID, *, approval_phrase: str
    ) -> ApprovalGrantDTO:
        with self._operation(), UnitOfWork(self._approval_factory) as uow:
            if not isinstance(preview_id, UUID) or not isinstance(idempotency_key, UUID):
                raise McpControlledError("mcp_mutation_input_invalid", 400)
            uow.session.execute(text("BEGIN IMMEDIATE"))
            row, review = self._review(uow, preview_id, idempotency_key)
            if not isinstance(approval_phrase, str) or approval_phrase != review.approval_phrase:
                raise McpControlledError("mcp_approval_phrase_mismatch", 403)
            if uow.session.get(MutationCommandRow, idempotency_key) is not None:
                raise McpControlledError("mcp_approval_conflict", 409)
            now = _utc(self._writer._clock())
            expires = min(now + timedelta(seconds=120), review.expires_at)
            if now >= expires:
                raise McpControlledError("mcp_preview_expired", 410)
            token, identifier = secrets.token_urlsafe(32), uuid4()
            grant = ApprovalGrantDTO(
                approval_id=identifier,
                scope_id=self.scope.scope_id,
                actor_id=self.actor,
                preview_id=preview_id,
                idempotency_key=idempotency_key,
                expires_at=expires,
                approval_token=token,
            )
            uow.session.add(
                McpApprovalRow(
                    id=identifier,
                    scope_id=self.scope.scope_id,
                    actor_id=self.actor,
                    preview_id=preview_id,
                    idempotency_key=idempotency_key,
                    token_hash=_token_hash(token),
                    preview_binding_hash=row.payload_fingerprint,
                    request_fingerprint=_request_fingerprint(
                        self.scope,
                        self.actor,
                        preview_id,
                        idempotency_key,
                        row.token_hash,
                    ),
                    created_at=now.isoformat(),
                    expires_at=expires.isoformat(),
                    consumed_at=None,
                    command_id=None,
                )
            )
            uow.commit()  # 无 hooks，批准审计不创建知识/revision/command/outbox。
            return grant

    def _check_grant(
        self, uow: UnitOfWork, request: ApplyDocumentUpdateInput, *, replay: bool
    ) -> McpApprovalRow:
        grant = uow.session.scalar(
            select(McpApprovalRow).where(
                McpApprovalRow.token_hash == _token_hash(request.approval_token)
            )
        )
        if grant is None:
            raise McpControlledError("mcp_approval_required", 403)
        fingerprint = _request_fingerprint(
            self.scope,
            self.actor,
            request.preview_id,
            request.idempotency_key,
            _token_hash(request.confirmation_token),
        )
        if (
            grant.scope_id != self.scope.scope_id
            or grant.actor_id != self.actor
            or grant.preview_id != request.preview_id
            or grant.idempotency_key != request.idempotency_key
            or not secrets.compare_digest(grant.request_fingerprint, fingerprint)
        ):
            raise McpControlledError("mcp_approval_conflict", 403)
        preview = uow.session.get(MutationPreviewRow, request.preview_id)
        if (
            preview is None
            or preview.scope_id != self.scope.scope_id
            or preview.actor_id != self.actor
        ):
            raise McpControlledError("mcp_preview_not_found", 404)
        self._reader._validate_preview(preview)
        self._reader._require_editable_source(uow, preview.source_id)
        if (
            grant.preview_binding_hash != preview.payload_fingerprint
            or preview.token_hash != _token_hash(request.confirmation_token)
        ):
            raise McpControlledError("mcp_approval_conflict", 409)
        command = uow.session.get(MutationCommandRow, request.idempotency_key)
        if replay:
            if (
                grant.consumed_at is None
                or grant.command_id != request.idempotency_key
                or command is None
                or command.scope_id != self.scope.scope_id
                or command.actor_id != self.actor
                or command.preview_id != request.preview_id
                or command.request_fingerprint != fingerprint
            ):
                raise McpControlledError("mcp_approval_conflict", 409)
            return grant  # 仅精确 consumed grant + 已提交 command 可过期后只读重放。
        if grant.consumed_at is not None or grant.command_id is not None:
            raise McpControlledError("mcp_approval_conflict", 409)
        now = _utc(self._writer._clock())
        created, expires = map(
            lambda value: _utc(datetime.fromisoformat(value)), (grant.created_at, grant.expires_at)
        )
        if (
            expires
            > min(
                created + timedelta(seconds=120), _utc(datetime.fromisoformat(preview.expires_at))
            )
            or now < created
        ):
            raise McpControlledError("mcp_approval_conflict", 409)
        if now >= expires:
            raise McpControlledError("mcp_approval_expired", 410)
        return grant

    def apply_document_update(self, query: ApplyDocumentUpdateInput) -> McpCommandDTO:
        with self._operation():
            query = _input(query, ApplyDocumentUpdateInput)
            with UnitOfWork(self._reader._session_factory) as uow:
                existing = uow.session.get(MutationCommandRow, query.idempotency_key)
                self._check_grant(uow, query, replay=existing is not None)
                if existing is not None:
                    return self._command_dto(self._reader._command_result(uow, existing))
                self._review(uow, query.preview_id, query.idempotency_key)
            # 内部 confirmed=True 仅在真实 grant RO 校验之后构造。
            from konwledge.mutations.models import CommandRequest

            context = _ApplyContext(query)
            token = self._active.set(context)
            try:
                result = self._writer.apply_command(
                    CommandRequest(
                        preview_id=query.preview_id,
                        confirmation_token=query.confirmation_token,
                        idempotency_key=query.idempotency_key,
                        confirmed=True,
                    )
                )
                return self._command_dto(result)
            except (MutationError, McpControlledError):
                raise
            except Exception:
                code = (
                    "mcp_mutation_outcome_unknown"
                    if context.commit_attempted
                    else "mcp_mutation_unavailable"
                )
                raise McpControlledError(code, 500 if context.commit_attempted else 503) from None
            finally:
                self._active.reset(token)


@dataclass(frozen=True)
class ControlledRuntime:
    service: McpControlledService


def _engine(guard: ScopeGuard, *, readonly: bool) -> Engine:
    def connect() -> sqlite3.Connection:
        guard.check_paths()
        raw = sqlite3.connect(
            guard.database.as_uri() + ("?mode=ro" if readonly else "?mode=rw"),
            uri=True,
            check_same_thread=False,
            timeout=5,
        )
        raw.execute("PRAGMA foreign_keys=ON")
        if readonly:
            raw.execute("PRAGMA query_only=ON")
        else:
            raw.create_function("knowledge_fts_text", 1, fts_document, deterministic=True)
        return raw

    engine = create_engine(
        f"sqlite+pysqlite:///{guard.database.as_posix()}",
        creator=connect,
        poolclass=NullPool,
    )
    if readonly:

        @event.listens_for(engine, "begin")
        def begin_snapshot(connection: Connection) -> None:
            connection.exec_driver_sql("BEGIN")

    return engine


@contextmanager
def open_controlled_runtime(
    database: Path, manifest: Path, actor: str, *, demo_root: Path | None = None
) -> Iterator[ControlledRuntime]:
    reader_engine: Engine | None = None
    writer_engine: Engine | None = None
    try:
        try:
            if (
                not isinstance(actor, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,79}", actor) is None
            ):
                raise McpControlledError("mcp_mutation_input_invalid", 400)
            guard = ScopeGuard.prepare(
                database,
                manifest,
                demo_root if demo_root is not None else Path.cwd() / ".konwledge" / "mutation-demo",
            )
            reader_engine = _engine(guard, readonly=True)
            reader_factory = sessionmaker(
                bind=reader_engine,
                autoflush=False,
                expire_on_commit=False,
            )
            reader = _ReadMutationService(reader_factory, guard.scope, actor)
            # 上面包含 B4 完整 RO preflight，批准 schema 是此后的唯一显式 schema 创建。
            guard.validate()
            writer_engine = _engine(guard, readonly=False)
            ControlledBase.metadata.create_all(writer_engine)
            service = McpControlledService(guard, reader, create_session_factory(writer_engine))
        except McpControlledError:
            raise
        except Exception:
            raise McpControlledError("mcp_mutation_scope_invalid", 503) from None
        yield ControlledRuntime(service)
    finally:
        if writer_engine is not None:
            writer_engine.dispose()
        if reader_engine is not None:
            reader_engine.dispose()


__all__ = [
    "CONTROLLED_TOOL_ANNOTATIONS",
    "CONTROLLED_TOOL_INPUTS",
    "CONTROLLED_TOOL_OUTPUTS",
    "ControlledRuntime",
    "McpControlledError",
    "McpControlledService",
    "open_controlled_runtime",
]
