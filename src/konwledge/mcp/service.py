"""无官方 MCP SDK 的只读服务; SQLite 隔离连接与输出投影是双重门禁。"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import monotonic
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Engine, and_, create_engine, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from konwledge.domain import KnowledgeUnit, KnowledgeUnitStatus
from konwledge.lifecycle.diff import diff_by_lineage
from konwledge.mcp.models import (
    BuildContextInput,
    CompareDocumentsInput,
    ContextPacket,
    DiffCounts,
    DiffItem,
    DocumentDiffDTO,
    EvidenceDTO,
    GetEvidenceInput,
    GetLineageInput,
    LineageDTO,
    Page,
    SanitizedEvidenceBlock,
    SearchDTO,
    SearchHitDTO,
    SearchInput,
    SkippedEvidence,
    UnitDTO,
)
from konwledge.retrieval import RetrievalMode, RetrievalService
from konwledge.storage.database import SessionFactory
from konwledge.storage.tables import DocumentRow, KnowledgeUnitRow, RevisionRow, SourceRow


class McpReadError(Exception):
    """传输层只应输出固定 code/status, 不输出存储异常、SQL 或路径。"""

    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code
        super().__init__(code)


def _uuid(value: object) -> UUID | None:
    if not isinstance(value, (str, UUID)):
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _hash(value: object) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None


class McpReadOnlyService:
    """仅取 factory 的 bind, 从不调用其 hooks 或 KnowledgeLibrary。

    复用 ManagementService.read_session 的隔离模式: 文件 mode=ro (保留 WAL
    可见性), 内存 StaticPool backup 到独立快照; query_only/BEGIN/rollback
    只作用于专用连接。没有 create_schema、upgrade、FTS 回填或状态物化。
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        bind = session_factory.kw.get("bind")
        if not isinstance(bind, Engine) or bind.dialect.name != "sqlite":
            raise ValueError("mcp_storage_unsupported")
        self._engine = bind

    @contextmanager
    def read_session(self) -> Iterator[Session]:
        database = self._engine.url.database
        raw: sqlite3.Connection | None = None
        reader: Engine | None = None
        original = 0
        try:
            if database is None or database in {"", ":memory:"}:
                raw = sqlite3.connect(":memory:")
                pool = self._engine.pool
                if not isinstance(pool, StaticPool):
                    raise McpReadError(500, "mcp_storage_unavailable")
                # 不 checkout/close 原 StaticPool, 也不惰性创建其连接或运行 hooks。
                record = vars(pool).get("connection")
                dbapi = getattr(record, "dbapi_connection", None)
                if not isinstance(dbapi, sqlite3.Connection):
                    raise McpReadError(500, "mcp_storage_unavailable")
                deadline = monotonic() + 5

                def progress(_status: int, _remaining: int, _total: int) -> None:
                    if monotonic() > deadline:
                        raise McpReadError(503, "mcp_snapshot_unavailable")

                dbapi.backup(raw, pages=256, progress=progress, sleep=0.01)
            else:
                uri = Path(database).resolve().as_uri() + "?mode=ro"
                raw = sqlite3.connect(uri, uri=True)
            original = raw.execute("PRAGMA query_only").fetchone()[0]
            raw.execute("PRAGMA query_only=ON")
            reader = create_engine("sqlite+pysqlite://", creator=lambda: raw, poolclass=NullPool)
            with Session(reader, autoflush=False) as session:
                # dialect 首次初始化会 rollback DBAPI; 必须先 checkout 再显式 BEGIN。
                session.connection()
                raw.execute("BEGIN")
                yield session
        finally:
            if raw is not None:
                try:
                    raw.rollback()
                    raw.execute(f"PRAGMA query_only={int(original)}")
                except sqlite3.ProgrammingError:
                    pass  # Session/NullPool 已 rollback 并关闭专用连接。
                finally:
                    raw.close()
            if reader is not None:
                reader.dispose()

    @contextmanager
    def _read_operation(self) -> Iterator[Session]:
        try:
            with self.read_session() as session:
                yield session
        except (SQLAlchemyError, sqlite3.Error):
            raise McpReadError(503, "mcp_storage_unavailable") from None
        except (ValidationError, ValueError, RuntimeError):
            raise McpReadError(409, "mcp_record_invalid") from None

    def search(self, query: SearchInput) -> SearchDTO:
        with self._read_operation() as session:
            return self._search(session, query)

    def _search(self, session: Session, query: SearchInput) -> SearchDTO:
        # 即使库无 eligible units, 缺 FTS 也必须失败, 不静默回填/降级。
        session.execute(text("SELECT unit_id FROM knowledge_units_fts LIMIT 0"))
        # 核心检索的 UoW 使用无 hooks 的临时 factory, 在当前只读事务内建立
        # savepoint; UoW rollback 不结束外部快照, 后续锚点验证仍在同一 BEGIN 内。
        factory = sessionmaker(
            bind=session.connection(),
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        result = RetrievalService(factory).search(
            query.query,
            mode=RetrievalMode.LEXICAL,
            include_stale=False,
            top_k=query.top_k,
            candidate_limit=query.candidate_limit,
            rrf_k=query.rrf_k,
            at=query.at,
            source_id=query.source_id,
        )
        hits: list[SearchHitDTO] = []
        for hit in result.hits:
            evidence = self._evidence(session, hit.unit.id)
            hits.append(
                SearchHitDTO.model_validate(
                    {
                        **evidence.model_dump(),
                        "status": hit.status,
                        "score": hit.score,
                        "lexical_rank": hit.lexical_rank,
                        "lexical_score": hit.lexical_score,
                    }
                )
            )
        return SearchDTO(
            evaluated_at=result.evaluated_at,
            top_k=result.top_k,
            candidate_limit=result.candidate_limit,
            rrf_k=result.rrf_k,
            hits=tuple(hits),
        )

    def build_context(self, query: BuildContextInput) -> ContextPacket:
        with self._read_operation() as session:
            result = self._search(session, query)
            blocks: list[SanitizedEvidenceBlock] = []
            skipped: list[SkippedEvidence] = []
            lineages: set[UUID] = set()
            spans: dict[UUID, list[tuple[int, int]]] = {}
            used_chars = 0
            for hit in result.hits:
                reason = None
                if len(blocks) >= query.max_units:
                    reason = "max_units"
                elif hit.lineage_id in lineages:
                    reason = "duplicate"
                elif any(
                    hit.start_char < end and start < hit.end_char
                    for start, end in spans.get(hit.document_id, ())
                ):
                    reason = "overlap"
                elif used_chars + len(hit.text) > query.max_chars:
                    reason = "budget"
                if reason is not None:
                    skipped.append(
                        SkippedEvidence.model_validate({"unit_id": hit.unit_id, "reason": reason})
                    )
                    continue
                blocks.append(
                    SanitizedEvidenceBlock(**hit.model_dump(), label=f"[{len(blocks) + 1}]")
                )
                used_chars += len(hit.text)
                lineages.add(hit.lineage_id)
                spans.setdefault(hit.document_id, []).append((hit.start_char, hit.end_char))
            return ContextPacket(
                evaluated_at=result.evaluated_at,
                max_chars=query.max_chars,
                max_units=query.max_units,
                used_chars=used_chars,
                blocks=tuple(blocks),
                skipped=tuple(skipped),
            )

    @staticmethod
    def _document(session: Session, identifier: UUID, *, historical: bool = False) -> DocumentRow:
        document = session.get(DocumentRow, identifier)
        if document is None:
            raise McpReadError(
                410 if historical else 404,
                "historical_document_unavailable" if historical else "document_not_found",
            )
        return document

    @staticmethod
    def _unit(row: KnowledgeUnitRow, document: DocumentRow) -> UnitDTO:
        return UnitDTO(
            unit_id=row.id,
            lineage_id=row.lineage_id or row.id,
            document_id=document.id,
            source_id=document.source_id,
            ordinal=row.ordinal,
            status=KnowledgeUnitStatus(row.status),
            start_char=row.start_char,
            end_char=row.end_char,
            content_hash=hashlib.sha256(row.text.encode("utf-8")).hexdigest(),
        )

    def get_lineage(self, query: GetLineageInput) -> LineageDTO:
        with self._read_operation() as session:
            statement = select(KnowledgeUnitRow).where(
                or_(
                    KnowledgeUnitRow.lineage_id == query.lineage_id,
                    and_(
                        KnowledgeUnitRow.lineage_id.is_(None),
                        KnowledgeUnitRow.id == query.lineage_id,
                    ),
                )
            )
            total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
            if not total:
                raise McpReadError(404, "lineage_not_found")
            rows = session.scalars(
                statement.join(DocumentRow)
                .order_by(DocumentRow.ingested_at, DocumentRow.id, KnowledgeUnitRow.ordinal)
                .limit(query.limit)
                .offset(query.offset)
            ).all()
            return LineageDTO(
                lineage_id=query.lineage_id,
                versions=Page(
                    items=tuple(
                        self._unit(row, self._document(session, row.document_id, historical=True))
                        for row in rows
                    ),
                    total=total,
                    limit=query.limit,
                    offset=query.offset,
                ),
            )

    def compare_documents(self, query: CompareDocumentsInput) -> DocumentDiffDTO:
        with self._read_operation() as session:
            old = self._document(session, query.old_document_id)
            new = self._document(session, query.new_document_id)
            if old.source_id != new.source_id:
                raise McpReadError(409, "diff_source_mismatch")

            def load(document: DocumentRow) -> list[KnowledgeUnitRow]:
                rows = list(
                    session.scalars(
                        select(KnowledgeUnitRow)
                        .where(KnowledgeUnitRow.document_id == document.id)
                        .order_by(KnowledgeUnitRow.ordinal)
                    )
                )
                if len({row.lineage_id or row.id for row in rows}) != len(rows):
                    raise McpReadError(409, "historical_lineage_invalid")
                return rows

            def domain(row: KnowledgeUnitRow) -> KnowledgeUnit:
                # section_path 仅参与 moved 判断; metadata/heading/tags 不进入 DTO。
                return KnowledgeUnit(
                    id=row.id,
                    lineage_id=row.lineage_id or row.id,
                    document_id=row.document_id,
                    ordinal=row.ordinal,
                    text=row.text,
                    start_char=row.start_char,
                    end_char=row.end_char,
                    section_path=tuple(row.section_path),
                )

            old_rows, new_rows = load(old), load(new)
            result = diff_by_lineage(
                [domain(row) for row in old_rows], [domain(row) for row in new_rows]
            )
            by_id = {row.id: row for row in (*old_rows, *new_rows)}
            changes: list[DiffItem] = []
            for change in result.changes[query.offset : query.offset + query.limit]:
                subject = change.new or change.old
                assert subject is not None
                changes.append(
                    DiffItem(
                        kind=change.kind,
                        lineage_id=subject.lineage_id,
                        old=None if change.old is None else self._unit(by_id[change.old.id], old),
                        new=None if change.new is None else self._unit(by_id[change.new.id], new),
                    )
                )
            return DocumentDiffDTO(
                source_id=new.source_id,
                old_document_id=old.id,
                new_document_id=new.id,
                counts=DiffCounts.model_validate(result.counts()),
                changes=Page(
                    items=tuple(changes),
                    total=len(result.changes),
                    limit=query.limit,
                    offset=query.offset,
                ),
            )

    def get_evidence(self, query: GetEvidenceInput) -> EvidenceDTO:
        with self._read_operation() as session:
            return self._evidence(session, query.unit_id)

    def _evidence(self, session: Session, identifier: UUID) -> EvidenceDTO:
        unit = session.get(KnowledgeUnitRow, identifier)
        if unit is None:
            raise McpReadError(404, "unit_not_found")
        document = self._document(session, unit.document_id, historical=True)
        if session.get(SourceRow, document.source_id) is None:
            raise McpReadError(410, "historical_source_unavailable")
        if (
            not unit.text.strip()
            or unit.start_char < 0
            or unit.end_char - unit.start_char != len(unit.text)
            or _hash(document.checksum) is None
        ):
            raise McpReadError(409, "historical_evidence_invalid")
        content_hash = hashlib.sha256(unit.text.encode("utf-8")).hexdigest()
        lineage_id = unit.lineage_id or unit.id
        revisions = session.scalars(
            select(RevisionRow)
            .where(RevisionRow.entity_type == "knowledge_unit", RevisionRow.entity_id == lineage_id)
            .order_by(RevisionRow.revision)
        ).all()
        anchored: list[UUID] = []
        expected: set[str] = set()
        checksum_anchored = False
        for revision in revisions:
            payload = revision.payload
            if not isinstance(payload, dict):
                raise McpReadError(409, "historical_evidence_invalid")
            for id_key, hash_key, document_key in (
                ("unit_id", "content_hash", "document_id"),
                ("previous_unit_id", "previous_content_hash", "previous_document_id"),
            ):
                if _uuid(payload.get(id_key)) == unit.id:
                    value = _hash(payload.get(hash_key))
                    if value is None or _uuid(payload.get(document_key)) != document.id:
                        raise McpReadError(409, "historical_evidence_invalid")
                    expected.add(value)
                    anchored.append(revision.id)
            if _uuid(payload.get("document_id")) == document.id and "document_checksum" in payload:
                if _hash(payload["document_checksum"]) != document.checksum:
                    raise McpReadError(409, "historical_evidence_invalid")
                checksum_anchored = True
                anchored.append(revision.id)

        publications = session.scalars(
            select(RevisionRow)
            .where(RevisionRow.entity_type == "source", RevisionRow.entity_id == document.source_id)
            .order_by(RevisionRow.revision)
        ).all()
        if any(not isinstance(row.payload, dict) for row in publications):
            raise McpReadError(409, "historical_evidence_invalid")
        publication = None
        for row in publications:
            if _uuid(row.payload.get("document_id")) == document.id:
                if _hash(row.payload.get("document_checksum")) != document.checksum:
                    raise McpReadError(409, "historical_evidence_invalid")
                checksum_anchored = True
                if publication is None:
                    publication = row  # exact 版本的首次 publication, 不是 latest/revert。
        if publication is not None:
            anchored.append(publication.id)
            if not expected:
                # 未变化的新 unit 无独立 revision: 首次 publication 前的 lineage
                # 内容 hash + 此 exact document checksum 联合锚定, 不读取最新正文。
                prior = [
                    row
                    for row in revisions
                    if row.created_at <= publication.created_at
                    and _hash(row.payload.get("content_hash")) is not None
                ]
                if prior:
                    expected.add(prior[-1].payload["content_hash"])
                    anchored.append(prior[-1].id)
        if not expected or not checksum_anchored:
            raise McpReadError(410, "historical_evidence_unavailable")
        if expected != {content_hash}:
            raise McpReadError(409, "historical_evidence_invalid")
        return EvidenceDTO(
            source_id=document.source_id,
            document_id=document.id,
            unit_id=unit.id,
            lineage_id=lineage_id,
            start_char=unit.start_char,
            end_char=unit.end_char,
            text=unit.text,
            content_hash=content_hash,
            document_checksum=document.checksum,
            revision_ids=tuple(dict.fromkeys(anchored)),
        )
