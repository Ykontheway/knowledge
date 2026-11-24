from __future__ import annotations

import importlib
import json
import os
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from knowledge.application import KnowledgeLibrary
from knowledge.domain import EvaluationItem, EvaluationSet
from knowledge.evaluation import EvaluationService
from knowledge.mcp.controlled import (
    CONTROLLED_TOOL_ANNOTATIONS,
    CONTROLLED_TOOL_INPUTS,
    CONTROLLED_TOOL_OUTPUTS,
    McpControlledError,
    McpControlledService,
    open_controlled_runtime,
)
from knowledge.mcp.controlled_models import (
    ApplyDocumentUpdateInput,
    EmptyInput,
    GetMutationCommandInput,
    GetMutationDocumentInput,
    McpCommandDTO,
    McpPreviewDTO,
    PreviewDocumentUpdateInput,
)
from knowledge.mcp.controlled_tables import McpApprovalRow
from knowledge.mcp.models import McpModel
from knowledge.mutations.tables import create_mutation_schema
from knowledge.storage import create_schema, create_session_factory, create_sqlite_engine
from knowledge.storage.tables import Base

ACTOR = "demo-editor"


@dataclass(frozen=True)
class DemoSeed:
    root: Path
    manifest: Path
    database: Path


def make_demo(tmp_path: Path) -> DemoSeed:
    """复制最小 B4 核心 fixture；全新隔离库，不 import scripts/旧 tests。"""
    root = tmp_path / ".knowledge" / "mutation-demo"
    root.mkdir(parents=True, mode=0o700)
    scope = root / str(uuid4())
    scope.mkdir(mode=0o700)
    seed = scope / ("seed-" + uuid4().hex)
    seed.mkdir(mode=0o700)
    content, database = seed / "demo.md", seed / "knowledge.db"
    content.write_text("# Demo\n\nhello", encoding="utf-8")
    content.chmod(0o600)
    engine = create_sqlite_engine(f"sqlite+pysqlite:///{database.as_posix()}")
    try:
        create_schema(engine)
        create_mutation_schema(engine)
        library = KnowledgeLibrary(create_session_factory(engine))
        result = library.import_path(content).imported[0].result
        dataset = EvaluationSet(
            id=uuid4(),
            name="B6 isolated test",
            version=1,
            created_at=result.ingestion.document.ingested_at,
            items=(
                EvaluationItem(
                    id="hello",
                    query="hello",
                    expected_lineage_ids=frozenset(
                        {
                            result.units[0].lineage_id,
                        }
                    ),
                ),
            ),
        )
        EvaluationService(library._session_factory, library._retrieval).import_set(dataset)
        library.automatic_evaluation.enable(dataset.id, version=1)
        manifest = scope / "mutation-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "kind": "knowledge-mutation-demo-v1",
                    "scope_id": scope.name,
                    "database": database.relative_to(scope).as_posix(),
                    "allowed_source_ids": [str(result.ingestion.document.source_id)],
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        manifest.chmod(0o600)
        report = seed / "report.json"
        report.write_text(
            json.dumps(
                {
                    "status": "passed",
                    "artifacts": {
                        "database": "knowledge.db",
                    },
                }
            ),
            encoding="utf-8",
        )
        report.chmod(0o600)
        database.chmod(0o600)
        return DemoSeed(root, manifest, database)
    finally:
        engine.dispose()


@pytest.fixture
def seed(tmp_path: Path) -> DemoSeed:
    return make_demo(tmp_path)


@pytest.fixture
def service(seed: DemoSeed) -> Iterator[McpControlledService]:
    with open_controlled_runtime(
        seed.database,
        seed.manifest,
        ACTOR,
        demo_root=seed.root,
    ) as runtime:
        yield runtime.service


def counts(seed: DemoSeed) -> tuple[int, ...]:
    with sqlite3.connect(seed.database.as_uri() + "?mode=ro", uri=True) as db:
        return tuple(
            db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "documents",
                "knowledge_units",
                "revisions",
                "mutation_commands",
                "auto_evaluation_jobs",
                "knowledge_units_fts",
            )
        )


def sql(seed: DemoSeed, statement: str, values: tuple[object, ...] = ()) -> None:
    with sqlite3.connect(seed.database) as db:
        db.execute(statement, values)


def preview(service: McpControlledService, text: str = "# Demo\n\nhello changed") -> McpPreviewDTO:
    source = service.get_mutation_session(EmptyInput()).sources[0]
    return service.preview_document_update(
        PreviewDocumentUpdateInput(
            source_id=source.source_id,
            document_id=source.document_id,
            expected_checksum=source.checksum,
            text=text,
        )
    )


def approve(
    service: McpControlledService, value: McpPreviewDTO, key: UUID | None = None
) -> ApplyDocumentUpdateInput:
    key = key or uuid4()
    review = service.review_approval(value.preview_id, key)
    grant = service.issue_approval(value.preview_id, key, approval_phrase=review.approval_phrase)
    assert grant.expires_at <= value.expires_at
    return ApplyDocumentUpdateInput(
        preview_id=value.preview_id,
        idempotency_key=key,
        confirmation_token=value.confirmation_token,
        approval_token=grant.approval_token,
    )


def unused(seed: DemoSeed) -> bool:
    with sqlite3.connect(seed.database) as db:
        return bool(
            db.execute(
                "SELECT count(*) FROM mcp_approvals WHERE consumed_at IS NOT NULL"
            ).fetchone()[0]
            == 0
        )


def test_protocol_contract() -> None:
    assert set(CONTROLLED_TOOL_INPUTS) == set(CONTROLLED_TOOL_OUTPUTS)
    assert not any("approval" in name for name in CONTROLLED_TOOL_INPUTS)
    for name, (model, _) in CONTROLLED_TOOL_INPUTS.items():
        assert issubclass(model, McpModel)
        assert issubclass(CONTROLLED_TOOL_OUTPUTS[name], McpModel)
        assert model.model_json_schema()["additionalProperties"] is False
        hints = CONTROLLED_TOOL_ANNOTATIONS[name]
        assert hints == {
            "readOnlyHint": name.startswith("get_"),
            "destructiveHint": name == "apply_document_update",
            "idempotentHint": name != "preview_document_update",
            "openWorldHint": False,
        }
    assert EmptyInput.model_validate({}) == EmptyInput()
    assert "confirmed" not in ApplyDocumentUpdateInput.model_fields


@pytest.mark.parametrize("extra", ["actor", "scope", "path", "sql", "confirmed", "target"])
def test_inputs_extra_forbid(extra: str) -> None:
    with pytest.raises(ValidationError):
        EmptyInput.model_validate({extra: True})
    with pytest.raises(ValidationError):
        PreviewDocumentUpdateInput.model_validate(
            {
                "source_id": str(uuid4()),
                "document_id": str(uuid4()),
                "expected_checksum": "a" * 64,
                "text": "hello",
                extra: True,
            }
        )


@pytest.mark.parametrize("bad", [True, 3, float("nan"), float("inf"), "\ud800", "🙂" * 16385])
def test_strict_text(bad: object) -> None:
    with pytest.raises(ValidationError):
        PreviewDocumentUpdateInput.model_validate(
            {
                "source_id": str(uuid4()),
                "document_id": str(uuid4()),
                "expected_checksum": "a" * 64,
                "text": bad,
            }
        )


def test_global_default_schema_isolation() -> None:
    importlib.import_module("knowledge.mcp.controlled_tables")
    assert "mcp_approvals" not in Base.metadata.tables
    engine = create_sqlite_engine("sqlite://")
    try:
        create_schema(engine)
        with engine.connect() as connection:
            from sqlalchemy import inspect

            assert "mcp_approvals" not in inspect(connection).get_table_names()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "invalid",
    [
        "wrongroot",
        "filename",
        "uuid",
        "manifest_scope",
        "businessdb",
        "missingdb",
        "manifest_mode",
        "db_mode",
        "scope_mode",
        "seed_mode",
        "root_mode",
        "symlink_scope",
        "symlink_seed",
        "symlink_manifest",
        "symlink_db",
        "hardlink_db",
        "failedreport",
        "wrongmarker",
        "disabled",
        "dataset_hash",
        "config_hash",
        "source_kind",
        "content_type",
        "allowlist",
        "missing_mutation",
        "missing_fts",
    ],
)
def test_startup_rejects_without_upgrade(seed: DemoSeed, invalid: str, tmp_path: Path) -> None:
    root, manifest, database = seed.root, seed.manifest, seed.database
    paths = {
        "manifest": manifest,
        "db": database,
        "scope": manifest.parent,
        "seed": database.parent,
        "root": root,
    }
    if invalid == "wrongroot":
        root = tmp_path
    elif invalid == "filename":
        manifest = manifest.rename(manifest.with_name("other.json"))
    elif invalid == "uuid":
        scope = manifest.parent.rename(root / "invalid-uuid")
        database, manifest = scope / database.parent.name / database.name, scope / manifest.name
    elif invalid in {"manifest_scope", "allowlist"}:
        payload = json.loads(manifest.read_text())
        payload["scope_id" if invalid == "manifest_scope" else "allowed_source_ids"] = (
            str(uuid4()) if invalid == "manifest_scope" else [str(uuid4())]
        )
        manifest.write_text(json.dumps(payload))
    elif invalid == "businessdb":
        database = tmp_path / "business.db"
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE private_business(value TEXT)")
        database.chmod(0o600)
    elif invalid == "missingdb":
        database.unlink()
    elif invalid.endswith("_mode"):
        path = paths[invalid.removesuffix("_mode")]
        path.chmod(0o755 if path.is_dir() else 0o644)
    elif invalid.startswith("symlink_"):
        path = paths[invalid.removeprefix("symlink_")]
        saved = path.rename(path.with_name(path.name + "-saved"))
        path.symlink_to(saved, target_is_directory=saved.is_dir())
    elif invalid == "hardlink_db":
        os.link(database, tmp_path / "linked.db")
    elif invalid in {"failedreport", "wrongmarker"}:
        report = database.parent / "report.json"
        report.write_text(
            json.dumps(
                {
                    "status": "failed" if invalid == "failedreport" else "passed",
                    "artifacts": {"database": "other.db"},
                }
            )
        )
    else:
        statements = {
            "disabled": "UPDATE auto_evaluation_config SET enabled=0",
            "dataset_hash": "UPDATE evaluation_sets SET content_hash='" + "f" * 64 + "'",
            "config_hash": "UPDATE auto_evaluation_config SET config_fingerprint='bad'",
            "source_kind": "UPDATE sources SET kind='manual'",
            "content_type": "UPDATE documents SET content_type='binary'",
            "missing_mutation": "DROP TABLE mutation_commands",
            "missing_fts": "DROP TABLE knowledge_units_fts",
        }
        sql(seed, statements[invalid])
    before = database.read_bytes() if database.exists() else None
    with (
        pytest.raises(McpControlledError) as error,
        open_controlled_runtime(
            database,
            manifest,
            ACTOR,
            demo_root=root,
        ),
    ):
        pytest.fail("unsafe startup accepted")
    assert error.value.code == "mcp_mutation_scope_invalid"
    if before is not None:
        assert database.read_bytes() == before
    else:
        assert not database.exists()


def test_default_root_and_fresh_directory_guard(
    seed: DemoSeed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(seed.root.parent.parent)
    with open_controlled_runtime(seed.database, seed.manifest, ACTOR) as runtime:
        assert runtime.service.get_mutation_session().actor_id == ACTOR
        seed.manifest.parent.chmod(0o755)
        with pytest.raises(McpControlledError):
            runtime.service.get_mutation_session()


def test_read_and_preview_and_grant_no_knowledge_job(
    seed: DemoSeed,
    service: McpControlledService,
) -> None:
    before, raw = counts(seed), seed.database.read_bytes()
    source = service.get_mutation_session().sources[0]
    document = service.get_mutation_document(
        GetMutationDocumentInput(document_id=source.document_id)
    )
    assert document.text == "# Demo\n\nhello"
    assert "metadata" not in document.model_dump() and "uri" not in document.model_dump()
    assert seed.database.read_bytes() == raw
    value = preview(service)
    assert counts(seed) == before
    request = approve(service, value)
    assert counts(seed) == before and unused(seed)
    assert request.approval_token not in repr(request)
    assert value.confirmation_token not in repr(value)
    with sqlite3.connect(seed.database) as db:
        data = str(db.execute("SELECT * FROM mcp_approvals").fetchall())
    assert request.approval_token not in data and value.confirmation_token not in data


def test_reads_no_writer_hooks(seed: DemoSeed, service: McpControlledService) -> None:
    def fail(_session: Session) -> None:
        raise AssertionError("writer hook must not run")

    factory = service._writer._session_factory
    event.listen(factory, "before_commit", fail)
    try:
        value = service.get_mutation_session().sources[0]
        service.get_mutation_document(GetMutationDocumentInput(document_id=value.document_id))
        with pytest.raises(McpControlledError) as missing:
            service.get_mutation_command(GetMutationCommandInput(command_id=uuid4()))
        assert missing.value.status == 404
    finally:
        event.remove(factory, "before_commit", fail)
    assert unused(seed)


def test_deny_before_approval(seed: DemoSeed, service: McpControlledService) -> None:
    value = preview(service)
    before = counts(seed)
    with pytest.raises(McpControlledError) as error:
        service.apply_document_update(
            ApplyDocumentUpdateInput(
                preview_id=value.preview_id,
                confirmation_token=value.confirmation_token,
                idempotency_key=uuid4(),
                approval_token="confirmed-true-not-a-grant",
            )
        )
    assert error.value.code == "mcp_approval_required" and counts(seed) == before


@pytest.mark.parametrize(
    "field",
    [
        "approval_token",
        "confirmation_token",
        "preview_id",
        "idempotency_key",
    ],
)
def test_request_binding(seed: DemoSeed, service: McpControlledService, field: str) -> None:
    request = approve(service, preview(service))
    before = counts(seed)
    bad = request.model_copy(
        update={field: uuid4() if field.endswith("id") or field.endswith("key") else "bad"}
    )
    with pytest.raises(McpControlledError):
        service.apply_document_update(bad)
    assert unused(seed) and counts(seed) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", "other-actor"),
        ("scope_id", uuid4().hex),
        ("preview_id", uuid4().hex),
        ("idempotency_key", uuid4().hex),
        ("token_hash", "f" * 64),
        ("preview_binding_hash", "f" * 64),
        ("request_fingerprint", "f" * 64),
        ("expires_at", "2099-01-01T00:00:00+00:00"),
    ],
)
def test_grant_tamper(
    seed: DemoSeed,
    service: McpControlledService,
    field: str,
    value: str,
) -> None:
    request = approve(service, preview(service))
    before = counts(seed)
    sql(seed, f"UPDATE mcp_approvals SET {field}=?", (value,))
    with pytest.raises(McpControlledError):
        service.apply_document_update(request)
    assert unused(seed) and counts(seed) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("text", "tampered"),
        ("text_fingerprint", "f" * 64),
        ("new_checksum", "f" * 64),
        ("payload_fingerprint", "f" * 64),
        ("expected_checksum", "f" * 64),
        ("token_hash", "f" * 64),
        ("expires_at", "2099-01-01T00:00:00+00:00"),
        ("source_id", uuid4().hex),
        ("document_id", uuid4().hex),
    ],
)
def test_preview_property_tamper(
    seed: DemoSeed, service: McpControlledService, field: str, value: str
) -> None:
    request = approve(service, preview(service))
    before = counts(seed)
    sql(seed, f"UPDATE mutation_previews SET {field}=?", (value,))
    for action in (
        lambda: service.review_approval(request.preview_id, request.idempotency_key),
        lambda: service.apply_document_update(request),
    ):
        with pytest.raises(McpControlledError):
            action()
    assert unused(seed) and counts(seed) == before


def test_actor_and_scope_isolation(seed: DemoSeed, service: McpControlledService) -> None:
    value = preview(service)
    request = approve(service, value)
    with open_controlled_runtime(
        seed.database,
        seed.manifest,
        "other",
        demo_root=seed.root,
    ) as other:
        with pytest.raises(McpControlledError):
            other.service.review_approval(value.preview_id, request.idempotency_key)
        with pytest.raises(McpControlledError):
            other.service.apply_document_update(request)
    other_seed = make_demo(seed.root.parent.parent / "other")
    with (
        open_controlled_runtime(
            other_seed.database, other_seed.manifest, ACTOR, demo_root=other_seed.root
        ) as other,
        pytest.raises(McpControlledError),
    ):
        other.service.apply_document_update(request)
    assert unused(seed)


def test_phrase_and_expiry(seed: DemoSeed, service: McpControlledService) -> None:
    value, key = preview(service), uuid4()
    review = service.review_approval(value.preview_id, key)
    assert review.approval_phrase == f"APPROVE {value.preview_id} {key} {value.new_checksum}"
    for phrase in ("confirmed", review.approval_phrase + " ", review.approval_phrase.lower()):
        with pytest.raises(McpControlledError):
            service.issue_approval(value.preview_id, key, approval_phrase=phrase)
    request = approve(service, value, key)
    service._writer._clock = lambda: datetime.now(UTC) + timedelta(seconds=121)
    with pytest.raises(McpControlledError) as expired:
        service.apply_document_update(request)
    assert expired.value.code == "mcp_approval_expired" and unused(seed)
    service._writer._clock = lambda: value.expires_at
    with pytest.raises(McpControlledError):
        service.review_approval(value.preview_id, key)


def test_commit_replay_after_expiry_one_command_job(
    seed: DemoSeed,
    service: McpControlledService,
) -> None:
    request = approve(service, preview(service))
    before = counts(seed)
    result = service.apply_document_update(request)
    assert result.committed and len(result.job_ids) == 1
    assert counts(seed)[3:5] == (before[3] + 1, before[4] + 1)
    after, raw = counts(seed), seed.database.read_bytes()
    service._writer._clock = lambda: datetime.now(UTC) + timedelta(hours=1)
    assert service.apply_document_update(request) == result
    assert (
        service.get_mutation_command(GetMutationCommandInput(command_id=request.idempotency_key))
        == result
    )
    assert counts(seed) == after and seed.database.read_bytes() == raw
    with pytest.raises(McpControlledError):
        service.apply_document_update(request.model_copy(update={"idempotency_key": uuid4()}))


def test_concurrent_same_request_no_race(seed: DemoSeed, service: McpControlledService) -> None:
    request = approve(service, preview(service))
    before = counts(seed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(service.apply_document_update, (request, request)))
    assert results[0].command_id == results[1].command_id == request.idempotency_key
    assert counts(seed)[3:5] == (before[3] + 1, before[4] + 1)


def test_stale_checksum_leaves_second_grant_unused(
    seed: DemoSeed,
    service: McpControlledService,
) -> None:
    requests = [
        approve(service, preview(service, text))
        for text in (
            "# Demo\n\nhello first",
            "# Demo\n\nhello second",
        )
    ]
    service.apply_document_update(requests[0])
    before = counts(seed)
    with pytest.raises(McpControlledError):
        service.apply_document_update(requests[1])
    assert counts(seed) == before
    with sqlite3.connect(seed.database) as db:
        assert (
            db.execute("SELECT count(*) FROM mcp_approvals WHERE consumed_at IS NULL").fetchone()[0]
            == 1
        )


def test_atomic_rollback_outbox_and_grant(seed: DemoSeed, service: McpControlledService) -> None:
    request = approve(service, preview(service))
    before = counts(seed)
    factory = service._writer._session_factory

    def fail(session: Session) -> None:
        grant = session.scalar(select(McpApprovalRow))
        assert grant is not None and grant.consumed_at is not None
        session.flush()
        raise OperationalError("private path/token/SQL", {}, RuntimeError("fault"))

    event.listen(factory, "before_commit", fail)
    try:
        with pytest.raises(McpControlledError) as error:
            service.apply_document_update(request)
        assert error.value.status == 503
        assert "private" not in str(error.value)
    finally:
        event.remove(factory, "before_commit", fail)
    assert counts(seed) == before and unused(seed)
    assert service.apply_document_update(request).committed


def test_aftercommit_drop_safe_get_recover(
    seed: DemoSeed, service: McpControlledService, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = approve(service, preview(service))

    def lost(_command_id: UUID) -> Any:
        raise RuntimeError("private reply and token")

    with monkeypatch.context() as patch:
        patch.setattr(service._writer, "get_command", lost)
        with pytest.raises(McpControlledError) as error:
            service.apply_document_update(request)
    assert (error.value.code, error.value.status) == ("mcp_mutation_outcome_unknown", 500)
    recovered = service.get_mutation_command(
        GetMutationCommandInput(command_id=request.idempotency_key)
    )
    assert recovered.committed and recovered.job_ids and not unused(seed)


def test_failed_quality_still_committed(seed: DemoSeed, service: McpControlledService) -> None:
    request = approve(service, preview(service, "# Absent\n\ncompletely unrelated absentcontent"))
    result = service.apply_document_update(request)
    assert result.committed is True and result.evaluation_status == "failed"
    assert isinstance(result, McpModel) and counts(seed)[3:5] == (1, 1)


def test_mcp_result_non_boolean_rejected(service: McpControlledService) -> None:
    value = service.apply_document_update(approve(service, preview(service)))
    for field in ("changed", "committed"):
        with pytest.raises(ValidationError):
            McpCommandDTO.model_validate({**value.model_dump(), field: 1})


def test_authoritative_expiry_inside_b4_transaction(
    seed: DemoSeed,
    service: McpControlledService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = preview(service)
    request = approve(service, value)
    before = counts(seed)
    original = service._writer._commit_command

    from knowledge.storage import UnitOfWork

    def expired_at_commit(uow: UnitOfWork, command_id: UUID, fingerprint: str) -> None:
        # B4 已创建待提交知识事实，此时最终 guard 拒绝必须一起 rollback。
        service._writer._clock = lambda: value.expires_at + timedelta(seconds=1)
        original(uow, command_id, fingerprint)

    monkeypatch.setattr(service._writer, "_commit_command", expired_at_commit)
    with pytest.raises(McpControlledError):
        service.apply_document_update(request)
    assert unused(seed) and counts(seed) == before


def test_known_generic_precommit_failure_not_unknown(
    seed: DemoSeed,
    service: McpControlledService,
) -> None:
    request = approve(service, preview(service))
    before = counts(seed)
    factory = service._writer._session_factory

    def fail(_session: Session) -> None:
        raise RuntimeError("secret private fault")

    event.listen(factory, "before_commit", fail)
    try:
        with pytest.raises(McpControlledError) as error:
            service.apply_document_update(request)
        assert (error.value.code, error.value.status) == ("mcp_mutation_unavailable", 503)
    finally:
        event.remove(factory, "before_commit", fail)
    assert unused(seed) and counts(seed) == before


def test_aftercommit_listener_failure_retains_atomic_grant(
    seed: DemoSeed,
    service: McpControlledService,
) -> None:
    request = approve(service, preview(service))
    factory = service._writer._session_factory

    def fail(_session: Session) -> None:
        raise OperationalError("secret after commit", {}, RuntimeError("fault"))

    event.listen(factory, "after_commit", fail)
    try:
        result = service.apply_document_update(request)
    finally:
        event.remove(factory, "after_commit", fail)
    assert result.committed and result.job_ids and not unused(seed)
    assert service.get_mutation_command(
        GetMutationCommandInput(command_id=request.idempotency_key)
    ).committed


def test_unused_second_grant_cannot_replay_existing_command(
    seed: DemoSeed,
    service: McpControlledService,
) -> None:
    value, key = preview(service), uuid4()
    first, second = approve(service, value, key), approve(service, value, key)
    service.apply_document_update(first)
    before = counts(seed)
    with pytest.raises(McpControlledError):
        service.apply_document_update(second)
    assert counts(seed) == before
    with sqlite3.connect(seed.database) as db:
        assert (
            db.execute("SELECT count(*) FROM mcp_approvals WHERE consumed_at IS NULL").fetchone()[0]
            == 1
        )


def test_min_preview_expiry_for_grant(service: McpControlledService) -> None:
    value, key = preview(service), uuid4()
    service._writer._clock = lambda: value.expires_at - timedelta(seconds=5)
    review = service.review_approval(value.preview_id, key)
    grant = service.issue_approval(value.preview_id, key, approval_phrase=review.approval_phrase)
    assert grant.expires_at == value.expires_at


def test_read_factory_enforces_sqlite_readonly(service: McpControlledService) -> None:
    assert not hasattr(service._reader._session_factory, "_auto_evaluation_service")
    from sqlalchemy import text

    with service._reader._session_factory() as session, pytest.raises(OperationalError):
        session.execute(text("UPDATE sources SET title='must not write'"))


def test_restart_read_only_recovery_no_jobs(seed: DemoSeed, service: McpControlledService) -> None:
    request = approve(service, preview(service))
    result = service.apply_document_update(request)
    before, raw = counts(seed), seed.database.read_bytes()
    with open_controlled_runtime(
        seed.database, seed.manifest, ACTOR, demo_root=seed.root
    ) as runtime:
        recovered = runtime.service.get_mutation_command(
            GetMutationCommandInput(command_id=request.idempotency_key)
        )
        assert recovered == result
    assert counts(seed) == before and seed.database.read_bytes() == raw


def test_strict_input_service_model_copy_bypass_denied(
    seed: DemoSeed,
    service: McpControlledService,
) -> None:
    source = service.get_mutation_session().sources[0]
    query = PreviewDocumentUpdateInput(
        source_id=source.source_id,
        document_id=source.document_id,
        expected_checksum=source.checksum,
        text="hello",
    )
    before = counts(seed)
    with pytest.raises(McpControlledError):
        service.preview_document_update(query.model_copy(update={"text": True}))
    request = approve(service, preview(service))
    with pytest.raises(McpControlledError):
        service.apply_document_update(request.model_copy(update={"approval_token": True}))
    assert unused(seed) and counts(seed) == before


def test_scope_directory_replacement_detected(
    seed: DemoSeed,
    service: McpControlledService,
) -> None:
    original = seed.manifest.parent
    original.rename(original.with_name(original.name + "-saved"))
    original.mkdir(mode=0o700)
    with pytest.raises(McpControlledError):
        service.get_mutation_session()


def test_dynamic_import_without_sdk_scripts_default_base() -> None:
    import subprocess
    import sys

    code = (
        "import importlib,sys; "
        "from knowledge.storage.tables import Base; "
        "before=set(Base.metadata.tables); "
        "importlib.import_module('knowledge.mcp.controlled'); "
        "importlib.import_module('knowledge.mcp.approval_cli'); "
        "assert before==set(Base.metadata.tables); "
        "assert 'mcp_approvals' not in Base.metadata.tables; "
        "assert 'mcp' not in sys.modules; "
        "assert not any(n.startswith('scripts') for n in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
