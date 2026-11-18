"""B5/U22: 真库只读门禁、嵌套白名单与 exact 历史证据。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, delete, event, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from konwledge.application import KnowledgeLibrary
from konwledge.mcp import models
from konwledge.mcp.models import (
    BuildContextInput,
    CompareDocumentsInput,
    GetEvidenceInput,
    GetLineageInput,
    SearchInput,
)
from konwledge.mcp.service import McpReadError, McpReadOnlyService
from konwledge.storage import (
    SessionFactory,
    create_schema,
    create_session_factory,
    create_sqlite_engine,
)
from konwledge.storage.tables import (
    Base,
    DocumentRow,
    KnowledgeUnitRow,
    RevisionRow,
    SourceRow,
)

SECRET = "private_DSN_uri_locator_author_metadata_43bc"
OLD = "# Rules\n保持本版本的原文。\n\n# Quota\n限额为 10。\n"
NEW = "# Rules\n保持本版本的原文。\n\n# Quota\n限额为 20。\n\n# Extra\n新增规则。\n"


@dataclass
class Store:
    engine: Engine
    factory: SessionFactory
    library: KnowledgeLibrary
    service: McpReadOnlyService
    old_id: UUID
    new_id: UUID
    old_units: tuple[UUID, ...]
    new_units: tuple[UUID, ...]


@pytest.fixture(params=["file", "memory"])
def store(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Store]:
    url = (
        "sqlite+pysqlite:///:memory:"
        if request.param == "memory"
        else f"sqlite+pysqlite:///{tmp_path / '知识库 with spaces.db'}"
    )
    engine = create_sqlite_engine(url)
    create_schema(engine)
    factory = create_session_factory(engine)
    library = KnowledgeLibrary(factory)
    source = tmp_path / "rules.md"
    source.write_text(OLD, encoding="utf-8")
    first = library.import_path(source).imported[0].result
    source.write_text(NEW, encoding="utf-8")
    second = library.import_path(source).imported[0].result
    with engine.begin() as connection:
        connection.execute(
            update(SourceRow).values(uri=SECRET, title=SECRET, metadata_json={"raw": SECRET})
        )
        connection.execute(
            update(DocumentRow).values(locator=SECRET, metadata_json={"raw": SECRET})
        )
        connection.execute(
            update(KnowledgeUnitRow).values(metadata_json={"raw": SECRET}, heading=SECRET)
        )
        for row in connection.execute(select(RevisionRow.id, RevisionRow.payload)):
            connection.execute(
                update(RevisionRow)
                .where(RevisionRow.id == row.id)
                .values(author=SECRET, payload={**row.payload, "raw": SECRET, "href": SECRET})
            )
    try:
        yield Store(
            engine,
            factory,
            library,
            McpReadOnlyService(factory),
            first.ingestion.document.id,
            second.ingestion.document.id,
            tuple(unit.id for unit in first.units),
            tuple(unit.id for unit in second.units),
        )
    finally:
        engine.dispose()


def snapshot(engine: Engine) -> str:
    with engine.connect() as connection:
        records: dict[str, Any] = {
            table.name: sorted(
                (dict(row) for row in connection.execute(select(table)).mappings()),
                key=lambda row: json.dumps(row, default=str, sort_keys=True),
            )
            for table in Base.metadata.sorted_tables
        }
        records["sqlite_master"] = [
            tuple(row)
            for row in connection.execute(
                text("SELECT type, name, sql FROM sqlite_master ORDER BY name")
            )
        ]
        records["fts"] = [
            tuple(row)
            for row in connection.execute(
                text("SELECT * FROM knowledge_units_fts ORDER BY unit_id")
            )
        ]
    return json.dumps(records, default=str, sort_keys=True)


def lineage_id(store: Store) -> UUID:
    return store.service.get_evidence(GetEvidenceInput(unit_id=store.old_units[1])).lineage_id


def all_outputs(store: Store) -> tuple[models.McpModel, ...]:
    return (
        store.service.search(SearchInput(query="限额")),
        store.service.build_context(BuildContextInput(query="限额")),
        store.service.get_evidence(GetEvidenceInput(unit_id=store.old_units[1])),
        store.service.get_lineage(GetLineageInput(lineage_id=lineage_id(store))),
        store.service.compare_documents(
            CompareDocumentsInput(old_document_id=store.old_id, new_document_id=store.new_id)
        ),
    )


def test_query_only_blocks_writes_and_does_not_poison_pool(store: Store) -> None:
    before = snapshot(store.engine)
    with pytest.raises(OperationalError), store.service.read_session() as session:
        assert session.scalar(text("PRAGMA query_only")) == 1
        raw = session.connection().connection.driver_connection
        assert isinstance(raw, sqlite3.Connection) and raw.in_transaction
        session.execute(update(SourceRow).values(title="should_not_write"))
    assert snapshot(store.engine) == before
    with store.engine.begin() as connection:
        assert connection.scalar(text("PRAGMA query_only")) == 0
        connection.execute(update(SourceRow).values(title="writer_still_works"))


def test_file_mode_ro_still_blocks_writes_when_query_only_disabled(store: Store) -> None:
    if store.engine.url.database == ":memory:":
        pytest.skip("匿名内存库使用独立 query_only 快照; mode=ro 仅适用于文件")
    with pytest.raises(OperationalError), store.service.read_session() as session:
        session.execute(text("PRAGMA query_only=OFF"))
        session.execute(update(SourceRow).values(title="should_not_write"))


@pytest.mark.parametrize("existing", [False, True])
def test_new_or_empty_database_never_creates_schema(tmp_path: Path, existing: bool) -> None:
    path = tmp_path / "empty.db"
    if existing:
        path.touch()
    engine = create_sqlite_engine(f"sqlite+pysqlite:///{path}")
    try:
        service = McpReadOnlyService(create_session_factory(engine))
        assert path.exists() is existing  # 构造不 checkout bind。
        with pytest.raises(McpReadError) as caught:
            service.search(SearchInput(query="missing"))
        assert caught.value.code == "mcp_storage_unavailable"
        assert str(path) not in str(caught.value)
        assert path.exists() is existing
        if existing:
            assert path.read_bytes() == b""
            with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
                assert connection.execute("SELECT name FROM sqlite_master").fetchall() == []
    finally:
        engine.dispose()


def test_no_auto_fts_or_additive_upgrade(store: Store) -> None:
    with store.engine.begin() as connection:
        for suffix in ("ai", "au", "ad"):
            connection.execute(text(f"DROP TRIGGER knowledge_units_fts_{suffix}"))
        connection.execute(text("DROP TABLE knowledge_units_fts"))
        connection.execute(text("DROP INDEX ix_knowledge_units_lineage_id"))
        connection.execute(text("ALTER TABLE knowledge_units DROP COLUMN lineage_id"))
    with pytest.raises(McpReadError, match="mcp_storage_unavailable"):
        store.service.search(SearchInput(query="限额"))
    with store.engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM sqlite_master WHERE name='knowledge_units_fts'")
            )
            == 0
        )
        columns = [row[1] for row in connection.execute(text("PRAGMA table_info(knowledge_units)"))]
        assert "lineage_id" not in columns


def test_missing_fts_with_empty_corpus_is_error_not_silent_success(tmp_path: Path) -> None:
    engine = create_sqlite_engine(f"sqlite+pysqlite:///{tmp_path / 'empty-corpus.db'}")
    try:
        create_schema(engine)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE knowledge_units_fts"))
        service = McpReadOnlyService(create_session_factory(engine))
        with pytest.raises(McpReadError, match="mcp_storage_unavailable"):
            service.search(SearchInput(query="!!!"))
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "model, data",
    [
        (SearchInput, {"query": "规则"}),
        (BuildContextInput, {"query": "规则"}),
        (GetEvidenceInput, {"unit_id": str(UUID(int=1))}),
        (GetLineageInput, {"lineage_id": str(UUID(int=1))}),
        (
            CompareDocumentsInput,
            {"old_document_id": str(UUID(int=1)), "new_document_id": str(UUID(int=2))},
        ),
    ],
)
def test_input_schemas_are_extra_forbidden(
    model: type[models.McpModel], data: dict[str, object]
) -> None:
    assert model.model_validate_json(json.dumps(data))
    assert model.model_json_schema()["additionalProperties"] is False
    for extra in ({"raw": SECRET}, {"mode": "vector"}, {"include_stale": True}):
        with pytest.raises(ValidationError):
            model.model_validate({**data, **extra})


@pytest.mark.parametrize(
    "data",
    [
        {"query": " "},
        {"query": "x", "top_k": 0},
        {"query": "x", "top_k": True},
        {"query": "x", "top_k": 101},
        {"query": "x", "candidate_limit": 1},
        {"query": "x", "at": "2026-01-01T00:00:00"},
    ],
)
def test_invalid_search_budgets_rejected(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SearchInput.model_validate(data)


@pytest.mark.parametrize("model", [SearchInput, BuildContextInput])
@pytest.mark.parametrize("at", [True, 1, 1.5, "1", "1767225600", "2026-01-01T00:00:00"])
def test_datetime_input_rejects_timestamp_coercion(model: type[SearchInput], at: object) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({"query": "规则", "at": at})


@pytest.mark.parametrize("model", [SearchInput, BuildContextInput])
def test_datetime_input_accepts_aware_python_value_and_wire_datetime(
    model: type[SearchInput],
) -> None:
    at = datetime(2026, 1, 1, tzinfo=UTC)
    assert model.model_validate({"query": "规则", "at": at}).at == at
    assert model.model_validate_json('{"query":"规则","at":"2026-01-01T00:00:00Z"}').at == at
    assert model.model_validate({"query": "规则", "at": None}).at is None


def test_output_white_list_recursive_and_frozen(store: Store) -> None:
    forbidden = {"uri", "source_uri", "locator", "metadata", "href", "links", "context_text"}

    def check(data: Any) -> None:
        if isinstance(data, dict):
            assert not forbidden.intersection(data)
            for value in data.values():
                check(value)
        elif isinstance(data, list):
            for value in data:
                check(value)

    for dto in all_outputs(store):
        encoded = dto.model_dump_json()
        assert SECRET not in encoded and str(store.engine.url) not in encoded
        check(json.loads(encoded))
        schema = json.dumps(type(dto).model_json_schema())
        assert "ResourceLink" not in schema
        for definition in type(dto).model_json_schema().get("$defs", {}).values():
            if definition.get("type") == "object":
                assert definition["additionalProperties"] is False
                assert not forbidden.intersection(definition["properties"])
        with pytest.raises(ValidationError):
            type(dto).model_validate({**dto.model_dump(), "metadata": {"raw": SECRET}})
        with pytest.raises(ValidationError):
            setattr(dto, next(iter(type(dto).model_fields)), "changed")
    packet = store.service.build_context(BuildContextInput(query="限额"))
    assert packet.blocks and isinstance(packet.blocks[0], models.SanitizedEvidenceBlock)
    assert "20" in packet.blocks[0].text and packet.blocks[0].label == "[1]"
    assert packet.used_chars == sum(len(block.text) for block in packet.blocks)


def test_context_exact_whole_blocks_and_character_budget(store: Store) -> None:
    full = store.service.build_context(BuildContextInput(query="规则", top_k=10))
    assert full.blocks
    tiny = store.service.build_context(BuildContextInput(query="规则", max_chars=0))
    assert tiny.blocks == () and tiny.used_chars == 0
    assert tiny.skipped and all(item.reason == "budget" for item in tiny.skipped)
    exact_size = len(full.blocks[0].text)
    exact = store.service.build_context(
        BuildContextInput(query="规则", max_chars=exact_size, max_units=1)
    )
    assert exact.blocks[0].text == full.blocks[0].text
    assert exact.used_chars <= exact.max_chars


def test_search_fixed_lexical_and_stale_excluded(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from konwledge.retrieval import RetrievalMode, RetrievalService

    original = RetrievalService.search
    calls: list[dict[str, Any]] = []

    def spy(self: RetrievalService, query: str, **kwargs: Any) -> Any:
        calls.append(kwargs)
        assert self.indexing_service is None
        return original(self, query, **kwargs)

    monkeypatch.setattr(RetrievalService, "search", spy)
    first = store.service.search(SearchInput(query="限额"))
    assert len(first.hits) == 1 and first.hits[0].unit_id == store.new_units[1]
    store.library.lifecycle.mark_stale(store.new_units[1], reason=SECRET)
    assert store.service.search(SearchInput(query="限额")).hits == ()
    assert store.service.build_context(BuildContextInput(query="限额")).blocks == ()
    assert all(call["mode"] is RetrievalMode.LEXICAL for call in calls)
    assert all(call["include_stale"] is False for call in calls)
    # 明确 unit ID 的历史证据不应用 search 的当前 active 过滤。
    assert "20" in store.service.get_evidence(GetEvidenceInput(unit_id=store.new_units[1])).text


def test_historical_evidence_exact_ids_hashes_and_unchanged_fallback(store: Store) -> None:
    old = store.service.get_evidence(GetEvidenceInput(unit_id=store.old_units[1]))
    new = store.service.get_evidence(GetEvidenceInput(unit_id=store.new_units[1]))
    assert old.document_id == store.old_id and new.document_id == store.new_id
    assert old.lineage_id == new.lineage_id
    assert old.text == OLD[old.start_char : old.end_char]
    assert new.text == NEW[new.start_char : new.end_char]
    assert "10" in old.text and "20" not in old.text
    assert old.content_hash == hashlib.sha256(old.text.encode()).hexdigest()
    assert old.document_checksum != new.document_checksum
    unchanged = store.service.get_evidence(GetEvidenceInput(unit_id=store.new_units[0]))
    assert unchanged.document_id == store.new_id and unchanged.unit_id == store.new_units[0]
    assert unchanged.text == NEW[unchanged.start_char : unchanged.end_char]
    with store.engine.connect() as connection:
        anchors = connection.execute(
            select(RevisionRow.entity_type, RevisionRow.payload).where(
                RevisionRow.id.in_(unchanged.revision_ids)
            )
        ).all()
    assert any(
        row.entity_type == "source"
        and row.payload["document_id"] == str(store.new_id)
        and row.payload["document_checksum"] == unchanged.document_checksum
        for row in anchors
    )
    assert any(row.payload.get("content_hash") == unchanged.content_hash for row in anchors)


@pytest.mark.parametrize(
    "corruption",
    ["text", "range", "checksum", "raw_payload", "hash", "document_id", "no_anchor"],
)
def test_corrupt_history_fails_closed(store: Store, corruption: str) -> None:
    identifier = store.old_units[1]
    with store.engine.begin() as connection:
        if corruption == "text":
            value = connection.scalar(
                select(KnowledgeUnitRow.text).where(KnowledgeUnitRow.id == identifier)
            )
            assert isinstance(value, str)
            connection.execute(
                update(KnowledgeUnitRow)
                .where(KnowledgeUnitRow.id == identifier)
                .values(text=value.replace("10", "99"))
            )
        elif corruption == "range":
            connection.execute(
                update(KnowledgeUnitRow)
                .where(KnowledgeUnitRow.id == identifier)
                .values(end_char=999)
            )
        elif corruption == "checksum":
            connection.execute(
                update(DocumentRow).where(DocumentRow.id == store.old_id).values(checksum="d" * 64)
            )
        elif corruption == "raw_payload":
            connection.execute(update(RevisionRow).values(payload=[SECRET]))
        elif corruption == "no_anchor":
            connection.execute(delete(RevisionRow))
        else:
            for row in connection.execute(select(RevisionRow.id, RevisionRow.payload)):
                if row.payload.get("unit_id") == str(identifier):
                    patch = (
                        {"content_hash": "d" * 64}
                        if corruption == "hash"
                        else {"document_id": str(store.new_id)}
                    )
                    connection.execute(
                        update(RevisionRow)
                        .where(RevisionRow.id == row.id)
                        .values(payload={**row.payload, **patch})
                    )
    with pytest.raises(McpReadError) as caught:
        store.service.get_evidence(GetEvidenceInput(unit_id=identifier))
    assert caught.value.status == (410 if corruption == "no_anchor" else 409)
    assert SECRET not in str(caught.value)


def test_unchanged_fallback_requires_exact_publication_checksum(store: Store) -> None:
    with store.engine.begin() as connection:
        for row in connection.execute(select(RevisionRow.id, RevisionRow.payload)):
            if row.payload.get("document_id") == str(store.new_id):
                payload = {**row.payload, "document_checksum": "invalid"}
                connection.execute(
                    update(RevisionRow).where(RevisionRow.id == row.id).values(payload=payload)
                )
    with pytest.raises(McpReadError, match="historical_evidence_invalid"):
        store.service.get_evidence(GetEvidenceInput(unit_id=store.new_units[0]))


def test_lineage_and_diff_keep_pagination(store: Store) -> None:
    identifier = lineage_id(store)
    page = store.service.get_lineage(GetLineageInput(lineage_id=identifier, limit=1, offset=1))
    assert page.versions.total == 2 and page.versions.limit == 1 and page.versions.offset == 1
    assert page.versions.items[0].document_id == store.new_id
    empty = store.service.get_lineage(GetLineageInput(lineage_id=identifier, offset=2))
    assert empty.versions.items == () and empty.versions.total == 2
    full = store.service.compare_documents(
        CompareDocumentsInput(old_document_id=store.old_id, new_document_id=store.new_id)
    )
    assert full.counts.model_dump() == {
        "added": 1,
        "modified": 1,
        "moved": 0,
        "unchanged": 1,
        "removed": 0,
    }
    for offset in range(4):
        diff = store.service.compare_documents(
            CompareDocumentsInput(
                old_document_id=store.old_id, new_document_id=store.new_id, limit=1, offset=offset
            )
        )
        assert diff.changes.total == 3
        assert diff.changes.items == full.changes.items[offset : offset + 1]


def test_unknown_identifiers_fail_with_fixed_codes(store: Store) -> None:
    with pytest.raises(McpReadError, match="unit_not_found"):
        store.service.get_evidence(GetEvidenceInput(unit_id=uuid4()))
    with pytest.raises(McpReadError, match="lineage_not_found"):
        store.service.get_lineage(GetLineageInput(lineage_id=uuid4()))
    with pytest.raises(McpReadError, match="document_not_found"):
        store.service.compare_documents(
            CompareDocumentsInput(old_document_id=uuid4(), new_document_id=store.new_id)
        )


def test_all_reads_no_data_schema_fts_commits_or_factory_hooks(store: Store) -> None:
    before = snapshot(store.engine)
    commits: list[object] = []
    hooks: list[object] = []

    def record_commit(connection: object) -> None:
        commits.append(connection)

    def record_hook(*args: object) -> None:
        hooks.append(args)

    event.listen(store.engine, "commit", record_commit)
    event.listen(store.factory, "after_begin", record_hook)
    try:
        all_outputs(store)
        assert snapshot(store.engine) == before
        assert commits == [] and hooks == []
    finally:
        event.remove(store.engine, "commit", record_commit)
        event.remove(store.factory, "after_begin", record_hook)


def test_parallel_reads_and_pending_writer_do_not_poison_pool(store: Store) -> None:
    before = snapshot(store.engine)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _index: all_outputs(store), range(8)))
    assert all(result[0].hits for result in results)  # type: ignore[attr-defined]
    assert snapshot(store.engine) == before
    with ThreadPoolExecutor(max_workers=1) as executor, store.engine.connect() as writer:
        writer.execute(update(SourceRow).values(title="pending_writer"))
        pending = executor.submit(store.service.search, SearchInput(query="限额"))
        assert writer.scalar(select(SourceRow.title)) == "pending_writer"
        assert writer.scalar(text("PRAGMA query_only")) == 0
        writer.commit()
        assert pending.result(timeout=10).hits
    with store.engine.connect() as connection:
        assert connection.scalar(select(SourceRow.title)) == "pending_writer"


def test_service_import_does_not_load_optional_sdks() -> None:
    code = (
        "import sys; import konwledge.mcp.service; "
        "assert not any(name.split('.')[0] in "
        "{'mcp', 'openai', 'langchain_openai', 'lancedb'} for name in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_snapshot_stays_open_through_retrieval_and_anchor_validation(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = store.service.read_session
    statements: list[str] = []

    @contextmanager
    def traced() -> Iterator[Session]:
        with original() as session:
            raw = session.connection().connection.driver_connection
            assert isinstance(raw, sqlite3.Connection) and raw.in_transaction
            raw.set_trace_callback(statements.append)
            yield session
            assert raw.in_transaction  # 核心 UoW 的 rollback 不结束外部 BEGIN。
            assert session.scalar(text("PRAGMA query_only")) == 1

    monkeypatch.setattr(store.service, "read_session", traced)
    all_outputs(store)
    forbidden = ("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "REPLACE", "COMMIT")
    assert statements
    assert not any(sql.lstrip().upper().startswith(forbidden) for sql in statements)
    assert any(sql.startswith("ROLLBACK TO SAVEPOINT") for sql in statements)
    assert any(sql == "ROLLBACK" for sql in statements)


def test_wal_commits_visible_next_session_but_not_inside_snapshot(store: Store) -> None:
    if store.engine.url.database == ":memory:":
        pytest.skip("WAL 只适用于文件库")
    with store.engine.connect() as connection:
        assert connection.scalar(text("PRAGMA journal_mode=WAL")) == "wal"
    with store.service.read_session() as session:
        before = session.scalar(select(SourceRow.title))
        with store.engine.begin() as writer:
            writer.execute(update(SourceRow).values(title="committed_in_wal"))
        assert session.scalar(select(SourceRow.title)) == before
        assert store.service._search(session, SearchInput(query="限额")).hits
        assert session.scalar(select(SourceRow.title)) == before
    with store.service.read_session() as session:
        assert session.scalar(select(SourceRow.title)) == "committed_in_wal"


def test_missing_lineage_column_with_intact_fts_is_not_upgraded(store: Store) -> None:
    with store.engine.begin() as connection:
        connection.execute(text("DROP INDEX ix_knowledge_units_lineage_id"))
        connection.execute(text("ALTER TABLE knowledge_units DROP COLUMN lineage_id"))
    with pytest.raises(McpReadError, match="mcp_storage_unavailable"):
        store.service.search(SearchInput(query="限额"))
    with store.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM knowledge_units_fts")) == 5
        assert "lineage_id" not in {
            row[1] for row in connection.execute(text("PRAGMA table_info(knowledge_units)"))
        }


def test_unopened_memory_factory_not_initialized_by_reader() -> None:
    engine = create_sqlite_engine("sqlite+pysqlite:///:memory:")
    try:
        service = McpReadOnlyService(create_session_factory(engine))
        assert "connection" not in vars(engine.pool)
        with pytest.raises(McpReadError, match="mcp_storage_unavailable"):
            service.search(SearchInput(query="x"))
        assert "connection" not in vars(engine.pool)
    finally:
        engine.dispose()


def test_cross_source_diff_rejected(store: Store, tmp_path: Path) -> None:
    other = tmp_path / "other.md"
    other.write_text("# Other\n无关来源。\n", encoding="utf-8")
    other_id = store.library.import_path(other).imported[0].result.ingestion.document.id
    with pytest.raises(McpReadError, match="diff_source_mismatch"):
        store.service.compare_documents(
            CompareDocumentsInput(old_document_id=other_id, new_document_id=store.new_id)
        )


@pytest.mark.parametrize("missing", ["document", "source"])
def test_orphan_evidence_not_fabricated(store: Store, missing: str) -> None:
    with store.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            if missing == "document":
                connection.execute(delete(DocumentRow).where(DocumentRow.id == store.old_id))
            else:
                source_id = connection.scalar(
                    select(DocumentRow.source_id).where(DocumentRow.id == store.old_id)
                )
                connection.execute(delete(SourceRow).where(SourceRow.id == source_id))
            connection.commit()
        finally:
            connection.rollback()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
    with pytest.raises(McpReadError) as caught:
        store.service.get_evidence(GetEvidenceInput(unit_id=store.old_units[1]))
    assert caught.value.status == 410
    assert caught.value.code == f"historical_{missing}_unavailable"
