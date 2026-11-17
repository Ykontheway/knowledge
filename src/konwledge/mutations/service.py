"""Scoped document mutations with durable, atomic command evidence."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from konwledge.auto_evaluation import AutoEvaluationService
from konwledge.auto_evaluation.models import AutoEvaluationStatus
from konwledge.domain import (
    Document,
    DocumentContentType,
    KnowledgeUnit,
    RevisionEntityType,
    SourceKind,
)
from konwledge.ingestion.normalization import fingerprint_text, normalize_text
from konwledge.ingestion.pipeline import _revision_counter
from konwledge.ingestion.splitting import TraceableTextSplitter
from konwledge.lifecycle import (
    DEFAULT_SIMILARITY_THRESHOLD,
    DocumentDiff,
    diff_by_lineage,
    diff_units,
    head_at,
    load_timeline,
    materialize_statuses,
    publish_document,
    revisions_for_diff,
)
from konwledge.lifecycle.status import Publication
from konwledge.mutations.models import (
    MAX_TEXT_BYTES,
    PREVIEW_TTL_SECONDS,
    CommandDTO,
    CommandRequest,
    ContentType,
    DiffCounts,
    DiffEntry,
    DiffKind,
    EvaluationStatus,
    MutationError,
    MutationScope,
    PreviewDTO,
    PreviewRequest,
    SourceSessionDTO,
)
from konwledge.mutations.tables import MutationCommandRow, MutationPreviewRow
from konwledge.storage import SessionFactory, UnitOfWork
from konwledge.storage.auto_evaluation import AutoEvaluationRepository, is_knowledge_revision
from konwledge.storage.tables import AutoEvaluationJobRow, RevisionRow

Clock = Callable[[], datetime]
IdFactory = Callable[[], UUID]
_MAX_DIFF_ITEMS = 200
_MAX_RESPONSE_BYTES = 512 * 1024


def _canonical_hash(value: object) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MutationError("server_clock_invalid", "server clock is invalid", status_code=503)
    return value.astimezone(UTC)


def _content_type(value: DocumentContentType) -> ContentType:
    return ContentType(value.value)


def _preview_binding(row: MutationPreviewRow) -> str:
    return _canonical_hash(
        {
            "scope_id": str(row.scope_id),
            "actor_id": row.actor_id,
            "source_id": str(row.source_id),
            "document_id": str(row.document_id),
            "expected_checksum": row.expected_checksum,
            "new_checksum": row.new_checksum,
            "text_fingerprint": row.text_fingerprint,
            "token_hash": row.token_hash,
            "created_at": row.created_at,
            "expires_at": row.expires_at,
            "counts": row.counts_json,
            "diff": row.diff_json,
        }
    )


class MutationService:
    def __init__(
        self,
        session_factory: SessionFactory,
        scope: MutationScope,
        *,
        actor_id: str,
        id_factory: IdFactory = uuid4,
        clock: Clock | None = None,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> None:
        self._session_factory = session_factory
        self._scope = scope
        self._actor_id = actor_id
        self._id_factory = id_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._splitter = TraceableTextSplitter(id_factory=id_factory)
        self._similarity_threshold = similarity_threshold
        # Reuse the factory's single hook owner; never construct a library per apply.
        self._automatic_evaluation = AutoEvaluationService(session_factory)
        self._validate_startup()

    @property
    def scope(self) -> MutationScope:
        return self._scope

    @property
    def actor_id(self) -> str:
        return self._actor_id

    def _validate_startup(self) -> None:
        """Read-only preflight, before router/app creation; never create a schema."""
        try:
            with UnitOfWork(self._session_factory) as uow:
                bound_database = uow.session.get_bind().engine.url.database
                if bound_database is None:
                    raise ValueError("file-backed database required")
                if Path(bound_database).resolve(strict=True) != self._scope.database_path:
                    raise ValueError("database scope mismatch")
                uow.session.execute(select(MutationPreviewRow).limit(0))
                uow.session.execute(select(MutationCommandRow).limit(0))
                uow.session.execute(select(AutoEvaluationJobRow).limit(0))
                if not self._auto_evaluation_enabled(uow):
                    raise ValueError("automatic evaluation must be enabled")
                for source_id in self._scope.allowed_source_ids:
                    self._require_editable_source(uow, source_id)
                    head = self._head(uow, source_id)
                    if head is None:
                        raise ValueError("editable source must have a published document")
                    document = uow.documents.get(head.document_id)
                    if document is None:
                        raise ValueError("published document is missing")
                    self._document_text(uow, document)
        except (OperationalError, OSError, TypeError, ValueError) as exc:
            raise MutationError(
                "mutation_startup_invalid", "mutation scope is unavailable", status_code=503
            ) from exc

    def list_sources(self) -> tuple[SourceSessionDTO, ...]:
        with UnitOfWork(self._session_factory) as uow:
            result: list[SourceSessionDTO] = []
            for source_id in self._scope.allowed_source_ids:
                self._require_editable_source(uow, source_id)
                source = uow.sources.get(source_id)
                head = self._head(uow, source_id)
                if source is None or head is None:
                    continue
                document = uow.documents.get(head.document_id)
                if document is None:
                    continue
                self._document_text(uow, document)
                result.append(
                    SourceSessionDTO(
                        source_id=source_id,
                        document_id=document.id,
                        checksum=document.checksum,
                        content_type=_content_type(document.content_type),
                        label=self._safe_label(source.title),
                    )
                )
            return tuple(result)

    def get_document_text(self, document_id: UUID) -> tuple[UUID, Document, str]:
        with UnitOfWork(self._session_factory) as uow:
            try:
                document = uow.documents.get(document_id)
            except ValueError as exc:
                raise self._unsafe_document() from exc
            if document is None:
                raise MutationError("document_not_found", "document was not found", status_code=404)
            self._require_editable_source(uow, document.source_id)
            head = self._head(uow, document.source_id)
            if head is None or head.document_id != document.id:
                raise MutationError(
                    "historical_document", "document is not current", status_code=409
                )
            return document.source_id, document, self._document_text(uow, document)

    def _candidate_diff(
        self, uow: UnitOfWork, document: Document, content: str
    ) -> tuple[Document, DocumentDiff, bool]:
        checksum = fingerprint_text(content)
        # The actual SQLite import identity includes locator. Also reuse older
        # checksums of this source if a locator was changed since publication.
        historical = next(
            (
                item
                for item in uow.documents.list_by_source(document.source_id)
                if item.checksum == checksum
            ),
            None,
        )
        previous_units = tuple(uow.knowledge_units.list_by_document(document.id))
        if len(previous_units) > _MAX_DIFF_ITEMS:
            raise MutationError("diff_too_large", "preview has too many entries", status_code=413)
        if historical is not None:
            if self._document_text(uow, historical) != content:
                raise self._unsafe_document()
            existing = tuple(uow.knowledge_units.list_by_document(historical.id))
            return historical, diff_by_lineage(previous_units, existing), True
        candidate = Document(
            id=self._id_factory(),
            source_id=document.source_id,
            locator=document.locator,
            content_type=document.content_type,
            checksum=checksum,
            ingested_at=_utc(self._clock()),
            metadata=document.metadata,
        )
        units = self._splitter.split(candidate, content)
        if len(units) > _MAX_DIFF_ITEMS:
            raise MutationError("diff_too_large", "preview has too many entries", status_code=413)
        # Reject text the splitter cannot preserve (e.g. whitespace-only input).
        if self._assemble_units(candidate, units) != content:
            raise self._unsafe_document()
        diff = diff_units(
            previous_units, units, similarity_threshold=self._similarity_threshold
        ).with_inherited_lineage()
        return candidate, diff, False

    def create_preview(self, request: PreviewRequest) -> PreviewDTO:
        self._validate_scope_source(request.scope_id, request.source_id)
        normalized = normalize_text(request.text)
        if len(normalized.encode("utf-8")) > MAX_TEXT_BYTES:
            raise MutationError("text_too_large", "text is too large", status_code=413)
        with UnitOfWork(self._session_factory) as uow:
            document = self._current_document(uow, request.source_id, request.document_id)
            self._document_text(uow, document)
            if document.checksum != request.expected_checksum:
                raise MutationError(
                    "checksum_conflict", "document checksum changed", status_code=409
                )
            candidate, diff, _reverted = self._candidate_diff(uow, document, normalized)
            if len(diff.changes) > _MAX_DIFF_ITEMS:
                raise MutationError(
                    "diff_too_large", "preview has too many entries", status_code=413
                )
            counts = DiffCounts.model_validate(diff.counts())
            entries = tuple(
                DiffEntry(
                    kind=DiffKind(change.kind.value),
                    old_text=None if change.old is None else change.old.text,
                    new_text=None if change.new is None else change.new.text,
                )
                for change in diff.changes
            )
            now = _utc(self._clock())
            expires_at = now + timedelta(seconds=PREVIEW_TTL_SECONDS)
            token = secrets.token_urlsafe(32)
            row = MutationPreviewRow(
                id=self._id_factory(),
                scope_id=self._scope.scope_id,
                actor_id=self._actor_id,
                source_id=request.source_id,
                document_id=request.document_id,
                expected_checksum=request.expected_checksum,
                new_checksum=candidate.checksum,
                text=normalized,
                text_fingerprint=fingerprint_text(normalized),
                token_hash=_token_hash(token),
                counts_json=counts.model_dump(mode="json"),
                diff_json=[entry.model_dump(mode="json") for entry in entries],
                created_at=now.isoformat(),
                expires_at=expires_at.isoformat(),
            )
            row.payload_fingerprint = _preview_binding(row)
            result = PreviewDTO(
                preview_id=row.id,
                scope_id=row.scope_id,
                source_id=row.source_id,
                document_id=row.document_id,
                expected_checksum=row.expected_checksum,
                new_checksum=row.new_checksum,
                expires_at=expires_at,
                confirmation_token=token,
                changed=row.new_checksum != request.expected_checksum,
                counts=counts,
                diff=entries,
            )
            if len(result.model_dump_json().encode("utf-8")) > _MAX_RESPONSE_BYTES:
                raise MutationError("diff_too_large", "preview is too large", status_code=413)
            try:
                uow.session.add(row)
                uow.commit()
            except OperationalError as exc:
                raise MutationError(
                    "mutation_schema_unavailable", "mutation schema is unavailable", status_code=503
                ) from exc
            return result

    def apply_command(self, request: CommandRequest) -> CommandDTO:
        request_fingerprint = _canonical_hash(
            {
                "scope_id": str(self._scope.scope_id),
                "actor_id": self._actor_id,
                "preview_id": str(request.preview_id),
                "token_hash": _token_hash(request.confirmation_token),
                "idempotency_key": str(request.idempotency_key),
                "confirmed": request.confirmed,
            }
        )
        with UnitOfWork(self._session_factory) as uow:
            try:
                uow.session.execute(text("BEGIN IMMEDIATE"))
                existing = uow.session.get(MutationCommandRow, request.idempotency_key)
                if existing is not None:
                    if (
                        existing.scope_id != self._scope.scope_id
                        or existing.actor_id != self._actor_id
                        or existing.request_fingerprint != request_fingerprint
                    ):
                        raise MutationError(
                            "idempotency_conflict", "idempotency key conflicts", status_code=409
                        )
                    return self._command_result(uow, existing)

                preview = uow.session.get(MutationPreviewRow, request.preview_id)
                if (
                    preview is None
                    or preview.scope_id != self._scope.scope_id
                    or preview.actor_id != self._actor_id
                ):
                    raise MutationError(
                        "preview_not_found", "preview was not found", status_code=404
                    )
                if not secrets.compare_digest(
                    preview.token_hash, _token_hash(request.confirmation_token)
                ):
                    raise MutationError(
                        "confirmation_mismatch", "confirmation token mismatch", status_code=403
                    )
                self._validate_preview(preview)
                if _utc(self._clock()) >= _utc(datetime.fromisoformat(preview.expires_at)):
                    raise MutationError("preview_expired", "preview expired", status_code=410)
                if not self._auto_evaluation_enabled(uow):
                    raise MutationError(
                        "auto_evaluation_required",
                        "automatic evaluation is not enabled",
                        status_code=409,
                    )
                document = self._current_document(uow, preview.source_id, preview.document_id)
                self._document_text(uow, document)
                if document.checksum != preview.expected_checksum:
                    raise MutationError(
                        "checksum_conflict", "document checksum changed", status_code=409
                    )
                if preview.new_checksum == preview.expected_checksum:
                    self._persist_command(
                        uow,
                        request,
                        request_fingerprint,
                        preview,
                        previous_document_id=document.id,
                        document_id=document.id,
                        changed=False,
                        revision_ids=(),
                    )
                else:
                    new_document, diff, reverted = self._candidate_diff(uow, document, preview.text)
                    now = _utc(self._clock())
                    revisions = tuple(
                        revision.model_copy(update={"author": self._actor_id})
                        for revision in revisions_for_diff(
                            diff,
                            document=new_document,
                            previous_document_id=document.id,
                            id_factory=self._id_factory,
                            clock=lambda: now,
                            next_number=_revision_counter(uow),
                            extra_payload={
                                "command_id": str(request.idempotency_key),
                                "reverted": reverted,
                            },
                        )
                    )
                    if not reverted:
                        new_document = new_document.model_copy(
                            update={
                                "metadata": {
                                    **new_document.metadata,
                                    "mutation_command_id": str(request.idempotency_key),
                                }
                            }
                        )
                        uow.documents.add(new_document)
                        for unit in diff.new_units:
                            uow.knowledge_units.add(unit)
                    for revision in revisions:
                        uow.revisions.add(revision)
                    source_revision = publish_document(
                        uow,
                        new_document,
                        previous_document_id=document.id,
                        reverted=reverted,
                        id_factory=self._id_factory,
                        created_at=now,
                    )
                    source_row = uow.session.get(RevisionRow, source_revision.id)
                    if source_row is None:
                        raise RuntimeError("publication revision disappeared")
                    source_row.author = self._actor_id
                    source_row.payload = {
                        **source_row.payload,
                        "command_id": str(request.idempotency_key),
                    }
                    materialize_statuses(uow, new_document.source_id)
                    revision_ids = tuple(revision.id for revision in (*revisions, source_revision))
                    self._persist_command(
                        uow,
                        request,
                        request_fingerprint,
                        preview,
                        previous_document_id=document.id,
                        document_id=new_document.id,
                        changed=True,
                        revision_ids=revision_ids,
                    )
                # before_commit enqueues the existing auto-evaluation outbox in
                # this SAME transaction. Nothing after this is required evidence.
                self._commit_command(uow, request.idempotency_key, request_fingerprint)
            except IntegrityError as exc:
                raise MutationError(
                    "write_conflict", "mutation write conflicted", status_code=409
                ) from exc
            except OperationalError as exc:
                raise MutationError(
                    "mutation_schema_unavailable", "mutation schema is unavailable", status_code=503
                ) from exc
        return self.get_command(request.idempotency_key)

    def _commit_command(
        self,
        uow: UnitOfWork,
        command_id: UUID,
        request_fingerprint: str,
    ) -> None:
        try:
            uow.commit()
        except Exception:
            # An after_commit listener can fail after SQLite committed. Close the
            # old session (rollback is invalid in its committed callback state),
            # then consult durable evidence before interpreting any exception.
            uow.session.close()
            try:
                with self._session_factory() as session:
                    row = session.get(MutationCommandRow, command_id)
                    committed = (
                        row is not None
                        and row.scope_id == self._scope.scope_id
                        and row.actor_id == self._actor_id
                        and row.request_fingerprint == request_fingerprint
                    )
            except OperationalError as exc:
                # No trustworthy answer: HTTP 500, not a false pre-commit 503.
                # The client retains the fixed key for a later GET/replay.
                raise RuntimeError("command outcome is uncertain; query the command key") from exc
            if not committed:
                raise

    def get_command(self, command_id: UUID) -> CommandDTO:
        with UnitOfWork(self._session_factory) as uow:
            row = uow.session.get(MutationCommandRow, command_id)
            if (
                row is None
                or row.scope_id != self._scope.scope_id
                or row.actor_id != self._actor_id
            ):
                raise MutationError("command_not_found", "command was not found", status_code=404)
            return self._command_result(uow, row)

    def _persist_command(
        self,
        uow: UnitOfWork,
        request: CommandRequest,
        request_fingerprint: str,
        preview: MutationPreviewRow,
        *,
        previous_document_id: UUID,
        document_id: UUID,
        changed: bool,
        revision_ids: tuple[UUID, ...],
    ) -> None:
        result = CommandDTO(
            command_id=request.idempotency_key,
            scope_id=self._scope.scope_id,
            actor_id=self._actor_id,
            source_id=preview.source_id,
            previous_document_id=previous_document_id,
            document_id=document_id,
            new_checksum=preview.new_checksum,
            changed=changed,
            revision_ids=revision_ids,
            job_ids=(),
            evaluation_status=(
                EvaluationStatus.PENDING if changed else EvaluationStatus.NOT_TRIGGERED
            ),
        )
        uow.session.add(
            MutationCommandRow(
                id=request.idempotency_key,
                scope_id=self._scope.scope_id,
                actor_id=self._actor_id,
                idempotency_key=request.idempotency_key,
                request_fingerprint=request_fingerprint,
                preview_id=request.preview_id,
                source_id=preview.source_id,
                previous_document_id=previous_document_id,
                document_id=document_id,
                new_checksum=preview.new_checksum,
                changed=int(changed),
                revision_ids_json=[str(item) for item in revision_ids],
                job_ids_json=[],
                evaluation_status=result.evaluation_status.value,
                result_json=result.model_dump(mode="json"),
                created_at=_utc(self._clock()).isoformat(),
            )
        )
        uow.session.flush()

    def _command_result(self, uow: UnitOfWork, row: MutationCommandRow) -> CommandDTO:
        """Derive job/status from exact durable triggers, never a captured memory list."""
        result = CommandDTO(
            command_id=row.id,
            scope_id=row.scope_id,
            actor_id=row.actor_id,
            source_id=row.source_id,
            previous_document_id=row.previous_document_id,
            document_id=row.document_id,
            new_checksum=row.new_checksum,
            changed=bool(row.changed),
            revision_ids=tuple(UUID(item) for item in row.revision_ids_json),
            job_ids=(),
            evaluation_status=EvaluationStatus.NOT_TRIGGERED,
        )
        if not result.changed:
            return result
        revisions = uow.session.scalars(
            select(RevisionRow).where(RevisionRow.id.in_(result.revision_ids))
        ).all()
        trigger_ids = {str(item.id) for item in revisions if is_knowledge_revision(item)}
        if not trigger_ids:
            return result.model_copy(update={"evaluation_status": EvaluationStatus.UNAVAILABLE})
        # json_each finds intersecting triggers in SQL with no history pagination;
        # exact-set verification excludes unrelated/manual/retry jobs.
        triggers = func.json_each(AutoEvaluationJobRow.trigger_revision_ids).table_valued("value")
        rows = uow.session.scalars(
            select(AutoEvaluationJobRow)
            .where(
                AutoEvaluationJobRow.trigger_key.is_not(None),
                select(triggers.c.value).where(triggers.c.value.in_(trigger_ids)).exists(),
            )
            .order_by(AutoEvaluationJobRow.created_at, AutoEvaluationJobRow.id)
        ).all()
        jobs = tuple(item for item in rows if set(item.trigger_revision_ids) == trigger_ids)
        statuses = {item.status for item in jobs}
        if not jobs:
            status = EvaluationStatus.UNAVAILABLE
        elif statuses & {AutoEvaluationStatus.FAILED.value, AutoEvaluationStatus.BLOCKED.value}:
            status = EvaluationStatus.FAILED
        elif statuses == {AutoEvaluationStatus.PASSED.value}:
            status = EvaluationStatus.PASSED
        elif statuses <= {
            AutoEvaluationStatus.QUEUED.value,
            AutoEvaluationStatus.RUNNING.value,
            AutoEvaluationStatus.PASSED.value,
        }:
            status = EvaluationStatus.PENDING
        else:
            status = EvaluationStatus.UNAVAILABLE
        return result.model_copy(
            update={
                "job_ids": tuple(item.id for item in jobs),
                "evaluation_status": status,
            }
        )

    def _validate_preview(self, preview: MutationPreviewRow) -> None:
        try:
            valid = (
                normalize_text(preview.text) == preview.text
                and len(preview.text.encode("utf-8")) <= MAX_TEXT_BYTES
                and fingerprint_text(preview.text)
                == preview.text_fingerprint
                == preview.new_checksum
                and secrets.compare_digest(_preview_binding(preview), preview.payload_fingerprint)
            )
            _utc(datetime.fromisoformat(preview.expires_at))
            _utc(datetime.fromisoformat(preview.created_at))
        except (TypeError, ValueError, UnicodeError):
            valid = False
        if not valid:
            raise MutationError(
                "preview_corrupt", "preview integrity check failed", status_code=409
            )
        self._require_allowed_source(preview.source_id)

    def _head(self, uow: UnitOfWork, source_id: UUID) -> Publication | None:
        try:
            return head_at(load_timeline(uow, source_id))
        except (TypeError, ValueError, KeyError) as exc:
            raise self._unsafe_document() from exc

    def _current_document(self, uow: UnitOfWork, source_id: UUID, document_id: UUID) -> Document:
        self._require_editable_source(uow, source_id)
        head = self._head(uow, source_id)
        if head is None:
            raise MutationError("document_not_found", "document was not found", status_code=404)
        if head.document_id != document_id:
            raise MutationError("historical_document", "document is not current", status_code=409)
        try:
            document = uow.documents.get(document_id)
        except ValueError as exc:
            raise self._unsafe_document() from exc
        if document is None or document.source_id != source_id:
            raise MutationError("document_not_found", "document was not found", status_code=404)
        return document

    def _require_allowed_source(self, source_id: UUID) -> None:
        if source_id not in self._scope.allowed_source_ids:
            raise MutationError("source_not_allowed", "source is not allowed", status_code=403)

    def _require_editable_source(self, uow: UnitOfWork, source_id: UUID) -> None:
        self._require_allowed_source(source_id)
        try:
            source = uow.sources.get(source_id)
        except ValueError as exc:
            raise MutationError(
                "source_not_allowed", "source is not editable", status_code=403
            ) from exc
        if source is None:
            raise MutationError("source_not_found", "source was not found", status_code=404)
        if source.kind not in {SourceKind.FILE, SourceKind.MANUAL}:
            raise MutationError("source_not_allowed", "source is not editable", status_code=403)

    def _validate_scope_source(self, scope_id: UUID, source_id: UUID) -> None:
        if scope_id != self._scope.scope_id:
            raise MutationError("scope_mismatch", "scope mismatch", status_code=403)
        self._require_allowed_source(source_id)

    @staticmethod
    def _unsafe_document() -> MutationError:
        return MutationError(
            "document_uneditable", "stored document is not safely editable", status_code=503
        )

    def _assemble_units(self, document: Document, units: tuple[KnowledgeUnit, ...]) -> str:
        if document.content_type not in {DocumentContentType.TEXT, DocumentContentType.MARKDOWN}:
            raise self._unsafe_document()
        offset = 0
        parts: list[str] = []
        total_bytes = 0
        for ordinal, unit in enumerate(units):
            total_bytes += len(unit.text.encode("utf-8"))
            if (
                total_bytes > MAX_TEXT_BYTES
                or unit.ordinal != ordinal
                or unit.document_id != document.id
                or unit.start_char != offset
                or unit.end_char != offset + len(unit.text)
            ):
                raise self._unsafe_document()
            parts.append(unit.text)
            offset = unit.end_char
        content = "".join(parts)
        if fingerprint_text(content) != document.checksum:
            raise self._unsafe_document()
        return content

    def _document_text(self, uow: UnitOfWork, document: Document) -> str:
        try:
            units = tuple(uow.knowledge_units.list_by_document(document.id))
            content = self._assemble_units(document, units)
            # Unchanged units may inherit their hash evidence from an earlier
            # version of the same lineage; units don't have a separate hash column.
            chains = uow.revisions.list_for_many(
                RevisionEntityType.KNOWLEDGE_UNIT,
                (unit.lineage_id for unit in units),
            )
            for unit in units:
                if not any(
                    revision.payload.get("content_hash") == unit.content_hash
                    for revision in chains[unit.lineage_id]
                ):
                    raise self._unsafe_document()
            return content
        except (TypeError, ValueError, UnicodeError) as exc:
            raise self._unsafe_document() from exc

    def _auto_evaluation_enabled(self, uow: UnitOfWork) -> bool:
        try:
            config = AutoEvaluationRepository(uow.session).config()
        except (TypeError, ValueError):
            return False
        return bool(config is not None and config.enabled)

    @staticmethod
    def _safe_label(value: str | None) -> str:
        if value is None or not value.strip():
            return "演示文档"
        compact = " ".join(value.split())
        if "/" in compact or "\\" in compact or ":" in compact:
            return "演示文档"
        return compact[:120]
