from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, func, inspect, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from knowledge.application import KnowledgeLibrary
from knowledge.domain import KnowledgeUnitStatus, RevisionEntityType
from knowledge.mutations.models import (
    CommandDTO,
    CommandRequest,
    EvaluationStatus,
    MutationError,
    MutationScope,
    PreviewDTO,
    PreviewRequest,
)
from knowledge.mutations.router import build_mutation_router
from knowledge.mutations.safety import load_mutation_scope
from knowledge.mutations.service import MutationService
from knowledge.mutations.tables import MutationCommandRow, MutationPreviewRow
from knowledge.storage import UnitOfWork, create_session_factory, create_sqlite_engine
from knowledge.storage.tables import (
    AutoEvaluationJobRow,
    DocumentRow,
    KnowledgeUnitRow,
    RevisionRow,
)
from test_mutations_demo import ACTOR, ORIGIN, READ_KEY, WRITE_KEY, _client, _demo

HEADERS = {"Authorization": f"Bearer {WRITE_KEY}", "Origin": ORIGIN}
POST_HEADERS = {**HEADERS, "X-Knowledge-Intent": "document-update"}
NOW = datetime(2026, 11, 17, 12, tzinfo=UTC)


@pytest.fixture
def setup(tmp_path: Path) -> tuple[KnowledgeLibrary, Path, MutationService]:
    library, manifest, _payload = _demo(tmp_path)
    scope = load_mutation_scope(manifest, tmp_path / "knowledge.db")
    service = MutationService(library._session_factory, scope, actor_id=ACTOR)
    return library, manifest, service


def preview(service: MutationService, content: str = "# Demo\n\nhello atomicneedle") -> PreviewDTO:
    source = service.list_sources()[0]
    return service.create_preview(
        PreviewRequest(
            scope_id=service.scope.scope_id,
            source_id=source.source_id,
            document_id=source.document_id,
            expected_checksum=source.checksum,
            text=content,
        )
    )


def command(value: PreviewDTO, key: UUID | None = None) -> CommandRequest:
    return CommandRequest(
        preview_id=value.preview_id,
        confirmation_token=value.confirmation_token,
        idempotency_key=key or uuid4(),
        confirmed=True,
    )


def counts(library: KnowledgeLibrary) -> tuple[int, ...]:
    with library._session_factory() as session:
        rows = tuple(
            int(session.scalar(select(func.count()).select_from(table)) or 0)
            for table in (
                DocumentRow,
                KnowledgeUnitRow,
                RevisionRow,
                MutationCommandRow,
                AutoEvaluationJobRow,
            )
        )
        return (*rows, int(session.scalar(text("SELECT count(*) FROM knowledge_units_fts")) or 0))


def fts(library: KnowledgeLibrary, query: str) -> tuple[str, ...]:
    with library._session_factory() as session:
        return tuple(
            session.scalars(
                text(
                    "SELECT unit_id FROM knowledge_units_fts WHERE knowledge_units_fts MATCH :query"
                ),
                {"query": query},
            ).all()
        )


def api_for(service: MutationService) -> TestClient:
    app = FastAPI()
    app.include_router(
        build_mutation_router(
            service,
            mutation_key=WRITE_KEY,
            allowed_origin=ORIGIN,
            read_key=READ_KEY,
        )
    )

    @app.exception_handler(HTTPException)
    async def safe_error(_request: Any, exc: HTTPException) -> Any:
        from fastapi.responses import JSONResponse

        return JSONResponse(exc.detail, status_code=exc.status_code)

    return TestClient(app, raise_server_exceptions=False)


def test_real_apply_atomic_fts_actor_and_exact_jobs(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
) -> None:
    library, manifest, service = setup
    with _client(library, manifest) as client:
        source = client.get("/v1/mutations/session", headers=HEADERS).json()["sources"][0]
        response = client.post(
            "/v1/mutations/previews",
            headers=POST_HEADERS,
            json={
                "scope_id": str(service.scope.scope_id),
                "source_id": source["source_id"],
                "document_id": source["document_id"],
                "expected_checksum": source["checksum"],
                "text": "# Demo\n\nhello atomicneedle",
            },
        )
        value = PreviewDTO.model_validate(response.json())
        request = command(value)
        before = counts(library)
        response = client.post(
            "/v1/mutations/commands", headers=POST_HEADERS, json=request.model_dump(mode="json")
        )
        assert response.status_code == 200, response.text
        result = CommandDTO.model_validate(response.json())
        assert result.command_id == request.idempotency_key
        assert result.committed and result.changed
        assert result.evaluation_status is EvaluationStatus.PASSED
        assert len(result.job_ids) == 1
        assert len(result.revision_ids) == 2
        after = counts(library)
        assert tuple(a - b for a, b in zip(after, before, strict=True)) == (1, 1, 2, 1, 1, 1)
        assert fts(library, "atomicneedle")
        with library._session_factory() as session:
            revisions = session.scalars(
                select(RevisionRow).where(RevisionRow.id.in_(result.revision_ids))
            ).all()
            assert {row.author for row in revisions} == {ACTOR}
            assert {row.payload["command_id"] for row in revisions} == {str(result.command_id)}
            job = session.get(AutoEvaluationJobRow, result.job_ids[0])
            assert job is not None
            assert set(job.trigger_revision_ids) == {str(item) for item in result.revision_ids}
            row = session.get(MutationCommandRow, result.command_id)
            assert row is not None and row.id == row.idempotency_key
            # This is intentionally never patched after commit. Dynamic fields
            # are read from the durable trigger chain on EVERY GET/replay.
            assert row.job_ids_json == []
        assert (
            client.get(f"/v1/mutations/commands/{request.idempotency_key}", headers=HEADERS).json()
            == response.json()
        )
        assert (
            client.post(
                "/v1/mutations/commands", headers=POST_HEADERS, json=request.model_dump(mode="json")
            ).json()
            == response.json()
        )
        assert counts(library) == after


def test_noop_fixed_id_replay_even_expired(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
) -> None:
    library, _manifest, service = setup
    value = preview(service, "# Demo\n\nhello")
    request = command(value)
    before = counts(library)
    result = service.apply_command(request)
    assert not result.changed and result.command_id == request.idempotency_key
    assert result.document_id == value.document_id
    assert result.job_ids == result.revision_ids == ()
    assert result.evaluation_status is EvaluationStatus.NOT_TRIGGERED
    service._clock = lambda: value.expires_at + timedelta(seconds=1)
    assert service.apply_command(request) == service.get_command(request.idempotency_key) == result
    assert tuple(a - b for a, b in zip(counts(library), before, strict=True)) == (0, 0, 0, 1, 0, 0)


@pytest.mark.parametrize("delta,expected", [(0, 410), (1, 410), (-1, 200)])
def test_exact_ttl_boundary(
    setup: tuple[KnowledgeLibrary, Path, MutationService], delta: int, expected: int
) -> None:
    library, _manifest, service = setup
    service._clock = lambda: NOW
    value = preview(service)
    service._clock = lambda: value.expires_at + timedelta(seconds=delta)
    with api_for(service) as client:
        response = client.post(
            "/v1/mutations/commands",
            headers=POST_HEADERS,
            json=command(value).model_dump(mode="json"),
        )
    assert response.status_code == expected
    if expected == 410:
        assert counts(library)[3] == 0


def test_token_and_idempotency_payload_conflicts(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
) -> None:
    library, _manifest, service = setup
    value = preview(service)
    request = command(value)
    with pytest.raises(MutationError) as mismatch:
        service.apply_command(request.model_copy(update={"confirmation_token": "bad"}))
    assert mismatch.value.status_code == 403
    assert counts(library)[3] == 0
    result = service.apply_command(request)
    for bad in (
        request.model_copy(update={"confirmation_token": "different"}),
        request.model_copy(update={"preview_id": uuid4()}),
    ):
        with pytest.raises(MutationError) as conflict:
            service.apply_command(bad)
        assert conflict.value.status_code == 409
    assert service.get_command(result.command_id) == result


@pytest.mark.parametrize(
    "field,bad",
    [
        ("text", "# Tampered\n\nhello"),
        ("text_fingerprint", "f" * 64),
        ("new_checksum", "f" * 64),
        ("payload_fingerprint", "f" * 64),
        ("source_id", uuid4()),
        ("document_id", uuid4()),
        ("expected_checksum", "f" * 64),
        ("token_hash", "f" * 64),
        ("expires_at", "2099-01-01T00:00:00+00:00"),
    ],
)
def test_preview_integrity_rechecked(
    setup: tuple[KnowledgeLibrary, Path, MutationService], field: str, bad: object
) -> None:
    library, _manifest, service = setup
    value = preview(service)
    before = counts(library)
    with library._session_factory() as session:
        session.execute(
            update(MutationPreviewRow)
            .where(MutationPreviewRow.id == value.preview_id)
            .values({field: bad})
        )
        session.commit()
    with pytest.raises(MutationError) as rejected:
        service.apply_command(command(value))
    assert rejected.value.status_code in {403, 409}
    assert counts(library) == before
    with library._session_factory() as session:
        row = session.get(MutationPreviewRow, value.preview_id)
        assert row is not None
        assert value.confirmation_token not in json.dumps(
            {
                "token_hash": row.token_hash,
                "payload": row.payload_fingerprint,
                "diff": row.diff_json,
                "text": row.text,
            }
        )


def test_two_actor_scope_preview_and_key_isolation(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
) -> None:
    library, _manifest, service = setup
    value = preview(service)
    request = command(value)
    other_actor = MutationService(library._session_factory, service.scope, actor_id="other-editor")
    other_scope = MutationService(
        library._session_factory,
        MutationScope(
            scope_id=uuid4(),
            database_path=service.scope.database_path,
            allowed_source_ids=service.scope.allowed_source_ids,
        ),
        actor_id=ACTOR,
    )
    for other in (other_actor, other_scope):
        with pytest.raises(MutationError) as rejected:
            other.apply_command(request)
        assert rejected.value.status_code == 404
    service.apply_command(request)
    for other in (other_actor, other_scope):
        with pytest.raises(MutationError) as hidden:
            other.get_command(request.idempotency_key)
        assert hidden.value.status_code == 404
        with pytest.raises(MutationError) as conflict:
            other.apply_command(request)
        assert conflict.value.status_code == 409
    source = service.list_sources()[0]
    with pytest.raises(MutationError) as rejected_scope:
        service.create_preview(
            PreviewRequest(
                scope_id=other_scope.scope.scope_id,
                source_id=source.source_id,
                document_id=source.document_id,
                expected_checksum=source.checksum,
                text="hello",
            )
        )
    assert rejected_scope.value.status_code == 403


def test_expected_head_concurrent_writers(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
) -> None:
    library, _manifest, service = setup
    requests = (
        command(preview(service)),
        command(preview(service, "# Demo\n\nhello concurrentneedle")),
    )
    before = counts(library)

    def apply(request: CommandRequest) -> int:
        try:
            service.apply_command(request)
            return 200
        except MutationError as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(apply, requests)) == [200, 409]
    assert tuple(a - b for a, b in zip(counts(library), before, strict=True)) == (1, 1, 2, 1, 1, 1)


def test_before_commit_fault_rolls_back_outbox_and_fts(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
) -> None:
    library, _manifest, service = setup
    request = command(preview(service))
    before = counts(library)

    def fail(session: Session) -> None:
        # Auto-evaluation's pre-existing hook has already added the job. Flush it
        # to prove this rollback includes outbox AND FTS, not just command JSON.
        if session.get(MutationCommandRow, request.idempotency_key) is not None:
            session.flush()
            assert session.scalar(select(func.count()).select_from(AutoEvaluationJobRow)) == 1
            raise OperationalError("injected before commit", {}, RuntimeError("fault"))

    event.listen(library._session_factory, "before_commit", fail)
    try:
        with pytest.raises(MutationError) as rejected:
            service.apply_command(request)
        assert rejected.value.status_code == 503
    finally:
        event.remove(library._session_factory, "before_commit", fail)
    assert counts(library) == before
    assert not fts(library, "atomicneedle")
    assert service.apply_command(request).committed


def test_after_commit_drain_fault_restart_and_poll_recovery(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library, manifest, service = setup
    value = preview(service)
    request = command(value)

    def fail_drain() -> None:
        raise OperationalError("injected drain", {}, RuntimeError("fault"))

    with monkeypatch.context() as patch:
        patch.setattr(library.automatic_evaluation, "drain", fail_drain)
        result = service.apply_command(request)
    assert result.committed and result.job_ids
    assert result.evaluation_status is EvaluationStatus.PENDING
    before = counts(library)
    # Rebuild engine+factory as a restarted process: no observation object or
    # in-memory captured job IDs survives this boundary.
    engine = create_sqlite_engine(f"sqlite+pysqlite:///{service.scope.database_path}")
    factory = create_session_factory(engine)
    restarted = MutationService(
        factory, load_mutation_scope(manifest, service.scope.database_path), actor_id=ACTOR
    )
    assert restarted.get_command(request.idempotency_key) == result
    assert restarted.apply_command(request) == result
    assert counts(library) == before
    restarted._automatic_evaluation.drain()
    updated = restarted.get_command(request.idempotency_key)
    assert updated.evaluation_status is EvaluationStatus.PASSED
    assert updated.job_ids == result.job_ids
    assert restarted.apply_command(request) == updated
    assert counts(library) == before
    engine.dispose()


def test_after_commit_listener_error_does_not_claim_uncommitted(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
) -> None:
    library, _manifest, service = setup
    request = command(preview(service))

    def fail_after_commit(_session: Session) -> None:
        raise OperationalError("injected after commit", {}, RuntimeError("fault"))

    event.listen(library._session_factory, "after_commit", fail_after_commit)
    try:
        result = service.apply_command(request)
    finally:
        event.remove(library._session_factory, "after_commit", fail_after_commit)
    assert result.committed and result.job_ids
    assert service.get_command(request.idempotency_key).committed
    assert counts(library)[3] == 1


def test_http500_after_commit_can_be_queried_by_original_key(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library, _manifest, service = setup
    request = command(preview(service))
    with api_for(service) as client:
        with monkeypatch.context() as patch:

            def lost_reply(_command_id: UUID) -> CommandDTO:
                raise RuntimeError("reply serialization fault")

            patch.setattr(service, "get_command", lost_reply)
            response = client.post(
                "/v1/mutations/commands", headers=POST_HEADERS, json=request.model_dump(mode="json")
            )
            assert response.status_code == 500
        response = client.get(f"/v1/mutations/commands/{request.idempotency_key}", headers=HEADERS)
        assert response.status_code == 200
        result = CommandDTO.model_validate(response.json())
        assert result.committed and result.job_ids
        assert service.apply_command(request) == result
        assert counts(library)[3] == 1


@pytest.mark.parametrize("walltime_offset_days", [0, 2 * 365], ids=["current", "two-years-later"])
def test_running_lease_recover_poll_updates_status(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
    monkeypatch: pytest.MonkeyPatch,
    walltime_offset_days: int,
) -> None:
    library, _manifest, service = setup
    # Import facts already exist; write and evaluate at the same relative instant,
    # not a fixed future year that will eventually precede new mutation facts.
    clock = datetime.now(UTC) + timedelta(seconds=1)
    clock += timedelta(days=walltime_offset_days)
    service._clock = lambda: clock
    library.automatic_evaluation._replace_clock(lambda: clock)
    value = preview(service)
    assert service.get_document_text(value.document_id)[1].ingested_at < clock
    request = command(value)

    def interrupt_execute(_job_id: UUID, _token: UUID) -> None:
        raise RuntimeError("worker interrupted after durable lease claim")

    with monkeypatch.context() as patch:
        patch.setattr(library.automatic_evaluation, "_execute", interrupt_execute)
        result = service.apply_command(request)
    assert result.evaluation_status is EvaluationStatus.PENDING
    job = library.automatic_evaluation.show(result.job_ids[0])
    assert job.status.value == "running" and job.attempt_count == 1
    assert job.created_at == job.evaluated_at == job.started_at == clock
    with UnitOfWork(library._session_factory) as uow:
        document = uow.documents.get(result.document_id)
        assert document is not None and document.ingested_at == clock
        revisions = [uow.revisions.get(item) for item in result.revision_ids]
        assert revisions and all(row is not None and row.created_at == clock for row in revisions)
    assert job.lease_expires_at == clock + timedelta(minutes=10)
    assert library.automatic_evaluation.recover() == 0
    clock += timedelta(minutes=11)
    library.automatic_evaluation._replace_clock(lambda: clock)
    assert library.automatic_evaluation.recover() == 1
    assert (
        service.get_command(request.idempotency_key).evaluation_status is EvaluationStatus.PENDING
    )
    library.automatic_evaluation.drain()
    job = library.automatic_evaluation.show(result.job_ids[0])
    assert (
        service.get_command(request.idempotency_key).evaluation_status is EvaluationStatus.PASSED
    ), job.error_code
    assert job.attempt_count == 2 and job.recovery_errors


def test_real_pass_fault_restore_reuses_historical_document(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
) -> None:
    library, _manifest, service = setup
    first = service.apply_command(command(preview(service, "# Demo\n\nhello stableevidence")))
    assert first.evaluation_status is EvaluationStatus.PASSED
    with UnitOfWork(library._session_factory) as uow:
        historical = tuple(uow.knowledge_units.list_by_document(first.document_id))
    bad = service.apply_command(
        command(preview(service, "# Demo\n\ncompletely unrelated absentcontent"))
    )
    assert bad.evaluation_status is EvaluationStatus.FAILED
    failure = library.automatic_evaluation.show(bad.job_ids[0])
    before = counts(library)
    restored = service.apply_command(command(preview(service, "# Demo\n\nhello stableevidence")))
    assert restored.document_id == first.document_id
    assert restored.previous_document_id == bad.document_id
    assert restored.evaluation_status is EvaluationStatus.PASSED
    assert restored.job_ids != first.job_ids != bad.job_ids
    after = counts(library)
    assert after[0:2] == before[0:2] and after[-1] == before[-1]
    assert after[3:5] == (before[3] + 1, before[4] + 1)
    assert library.automatic_evaluation.show(bad.job_ids[0]) == failure
    assert service.get_command(bad.command_id).evaluation_status is EvaluationStatus.FAILED
    with UnitOfWork(library._session_factory) as uow:
        units = tuple(uow.knowledge_units.list_by_document(restored.document_id))
        assert tuple(unit.id for unit in units) == tuple(unit.id for unit in historical)
        assert tuple(unit.lineage_id for unit in units) == tuple(
            unit.lineage_id for unit in historical
        )
        assert {unit.status for unit in units} == {KnowledgeUnitStatus.ACTIVE}
        revisions = [uow.revisions.get(item) for item in restored.revision_ids]
        assert all(row is not None and row.payload["reverted"] for row in revisions)
        assert any(
            row is not None and row.entity_type is RevisionEntityType.SOURCE for row in revisions
        )


@pytest.mark.parametrize(
    "body",
    [
        '{"confirmed":true,"confirmed":true}',
        '{"text":NaN}',
        '{"text":"\\ud800"}',
    ],
)
def test_strict_json_rejected(
    setup: tuple[KnowledgeLibrary, Path, MutationService], body: str
) -> None:
    library, _manifest, service = setup
    with api_for(service) as client:
        response = client.post(
            "/v1/mutations/previews",
            headers={**POST_HEADERS, "Content-Type": "application/json"},
            content=body,
        )
    assert response.status_code == 400
    assert counts(library)[3] == 0


def test_strict_dto_and_get_safe_errors(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
) -> None:
    _library, _manifest, service = setup
    value = command(preview(service)).model_dump(mode="json")
    for update_values in (
        {"confirmed": 1},
        {"confirmed": "true"},
        {"confirmed": False},
        {"actor_id": "impersonation"},
    ):
        with pytest.raises(ValidationError):
            CommandRequest.model_validate({**value, **update_values})
    with api_for(service) as client:
        for endpoint in ("documents", "commands"):
            response = client.get(f"/v1/mutations/{endpoint}/{uuid4()}", headers=HEADERS)
            assert response.status_code == 404


@pytest.mark.parametrize("corruption", ["gap", "range", "unit_text", "checksum", "hash_evidence"])
def test_document_corruption_blocks_get_and_preview(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
    corruption: str,
) -> None:
    library, _manifest, service = setup
    source = service.list_sources()[0]
    with library._session_factory() as session:
        unit = session.scalar(
            select(KnowledgeUnitRow).where(KnowledgeUnitRow.document_id == source.document_id)
        )
        assert unit is not None
        if corruption == "gap":
            unit.start_char += 1
        elif corruption == "range":
            unit.end_char += 1
        elif corruption == "unit_text":
            unit.text = unit.text.replace("hello", "jello")
        elif corruption == "checksum":
            session.execute(
                update(DocumentRow)
                .where(DocumentRow.id == source.document_id)
                .values(checksum="f" * 64)
            )
        else:
            for revision in session.scalars(
                select(RevisionRow).where(RevisionRow.entity_type == "knowledge_unit")
            ):
                revision.payload = {**revision.payload, "content_hash": "f" * 64}
        session.commit()
    with api_for(service) as client:
        response = client.get(f"/v1/mutations/documents/{source.document_id}", headers=HEADERS)
    assert response.status_code == 503
    with pytest.raises(MutationError) as rejected:
        service.create_preview(
            PreviewRequest(
                scope_id=service.scope.scope_id,
                source_id=source.source_id,
                document_id=source.document_id,
                expected_checksum=source.checksum,
                text="hello updated",
            )
        )
    assert rejected.value.status_code == 503


def test_complete_long_diff_unicode_and_whitespace_not_disk(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
) -> None:
    _library, manifest, service = setup
    content = "  \n# 大标题\n\nhello " + "中文🙂 and spaces \t\n" * 1200
    value = preview(service, content)
    assert any(item.new_text is not None and len(item.new_text) > 2000 for item in value.diff)
    assert "".join(item.new_text or "" for item in value.diff) == content
    result = service.apply_command(command(value))
    (manifest.parent / "demo.md").write_text("DO NOT READ LOCATOR", encoding="utf-8")
    assert service.get_document_text(result.document_id)[2] == content
    noop = preview(service, content)
    assert "".join(item.old_text or "" for item in noop.diff) == content
    assert "".join(item.new_text or "" for item in noop.diff) == content
    assert len(noop.model_dump_json().encode("utf-8")) < 512 * 1024


def test_oversized_entries_and_request_refused_not_partial(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
) -> None:
    library, _manifest, service = setup
    before = counts(library)
    with pytest.raises(MutationError) as rejected:
        preview(service, "".join(f"# Heading {i}\n\nhello\n" for i in range(201)))
    assert rejected.value.status_code == 413
    with api_for(service) as client:
        response = client.post(
            "/v1/mutations/previews",
            headers={**POST_HEADERS, "Content-Type": "application/json"},
            content=b" " * (128 * 1024 + 1),
        )
    assert response.status_code == 413
    assert counts(library) == before


@pytest.mark.parametrize(
    "target,mode", [("manifest", 0o644), ("database", 0o644), ("parent", 0o755)]
)
def test_backend_scope_private_permissions(
    setup: tuple[KnowledgeLibrary, Path, MutationService], target: str, mode: int
) -> None:
    _library, manifest, service = setup
    {"manifest": manifest, "database": service.scope.database_path, "parent": manifest.parent}[
        target
    ].chmod(mode)
    with pytest.raises(MutationError) as rejected:
        load_mutation_scope(manifest, service.scope.database_path)
    assert rejected.value.status_code == 503


@pytest.mark.parametrize("target", ["ancestor", "nested"])
def test_backend_scope_rejects_deep_symlinks(tmp_path: Path, target: str) -> None:
    root = tmp_path / "owned"
    root.mkdir(mode=0o700)
    _library, manifest, _payload = _demo(root)
    database = root / "knowledge.db"
    if target == "ancestor":
        alias = tmp_path / "alias"
        alias.symlink_to(root, target_is_directory=True)
        manifest, database = alias / "manifest.json", alias / "knowledge.db"
    else:
        seed = root / "seed"
        seed.mkdir(mode=0o700)
        database.rename(seed / "knowledge.db")
        link = root / "indirect"
        link.symlink_to(seed, target_is_directory=True)
        payload = json.loads(manifest.read_text())
        payload["database"] = "indirect/knowledge.db"
        manifest.write_text(json.dumps(payload))
        database = seed / "knowledge.db"
    with pytest.raises(MutationError):
        load_mutation_scope(manifest, database)


@pytest.mark.parametrize("invalid", ["disabled", "schema", "config"])
def test_startup_validates_without_creating_schema(
    setup: tuple[KnowledgeLibrary, Path, MutationService], invalid: str
) -> None:
    library, manifest, service = setup
    if invalid == "disabled":
        library.automatic_evaluation.disable()
    else:
        with library._session_factory() as session:
            if invalid == "schema":
                session.execute(text("DROP TABLE mutation_commands"))
            else:
                session.execute(
                    text("UPDATE auto_evaluation_config SET config_fingerprint = :hash"),
                    {"hash": "f" * 64},
                )
            session.commit()
    with pytest.raises(MutationError):
        _client(library, manifest)
    if invalid == "schema":
        with library._session_factory() as session:
            assert "mutation_commands" not in inspect(session.get_bind()).get_table_names()
    assert service.scope.database_path.is_file()


@pytest.mark.parametrize("kind,expected", [("manual", 200), ("url", 403), ("unknown", 403)])
def test_get_source_kind_allowlist_runtime(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
    kind: str,
    expected: int,
) -> None:
    from knowledge.storage.tables import SourceRow

    library, _manifest, service = setup
    source = service.list_sources()[0]
    with library._session_factory() as session:
        session.execute(update(SourceRow).where(SourceRow.id == source.source_id).values(kind=kind))
        session.commit()
    with api_for(service) as client:
        response = client.get(f"/v1/mutations/documents/{source.document_id}", headers=HEADERS)
    assert response.status_code == expected
    if expected == 200:
        assert response.json()["text"] == "# Demo\n\nhello"


def test_exact_text_size_limit_and_oversized_existing_document(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
) -> None:
    from knowledge.ingestion.normalization import fingerprint_text

    library, _manifest, service = setup
    content = "# Demo\n\nhello "
    content += "a" * (64 * 1024 - len(content))
    value = preview(service, content)
    result = service.apply_command(command(value))
    assert service.get_document_text(result.document_id)[2] == content
    noop = preview(service, content)
    assert noop.diff[0].old_text == noop.diff[0].new_text == content
    with api_for(service) as client:
        source = service.list_sources()[0]
        response = client.post(
            "/v1/mutations/previews",
            headers=POST_HEADERS,
            json={
                "scope_id": str(service.scope.scope_id),
                "source_id": str(source.source_id),
                "document_id": str(source.document_id),
                "expected_checksum": source.checksum,
                "text": content + "x",
            },
        )
        assert response.status_code == 413
        with library._session_factory() as session:
            unit = session.scalar(
                select(KnowledgeUnitRow).where(KnowledgeUnitRow.document_id == result.document_id)
            )
            assert unit is not None
            unit.text += "x"
            unit.end_char += 1
            session.execute(
                update(DocumentRow)
                .where(DocumentRow.id == result.document_id)
                .values(checksum=fingerprint_text(content + "x"))
            )
            session.commit()
        response = client.get(f"/v1/mutations/documents/{result.document_id}", headers=HEADERS)
        assert response.status_code == 503


def test_get_and_preview_out_of_scope_source_are_safe(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
) -> None:
    library, manifest, service = setup
    other = manifest.parent / "outside.md"
    other.write_text("# Outside\n\nnot allowed", encoding="utf-8")
    imported = library.import_path(other).imported[0].result.ingestion.document
    with api_for(service) as client:
        response = client.get(f"/v1/mutations/documents/{imported.id}", headers=HEADERS)
        assert response.status_code == 403
        response = client.post(
            "/v1/mutations/previews",
            headers=POST_HEADERS,
            json={
                "scope_id": str(service.scope.scope_id),
                "source_id": str(imported.source_id),
                "document_id": str(imported.id),
                "expected_checksum": imported.checksum,
                "text": "# Outside\n\nchanged",
            },
        )
        assert response.status_code == 403


def test_full_diff_union_over_entry_bound_rejected(
    setup: tuple[KnowledgeLibrary, Path, MutationService],
) -> None:
    library, _manifest, service = setup
    # Both sides have only 110 units; the full historical revert has 220
    # added+removed entries because its persisted lineages are disjoint.
    first_text = "".join(f"# 古籍{i}\n\n山河天地古代文献天文地理历史记载\n" for i in range(110))
    second_text = "".join(f"# Modern{i}\n\nabcdefghijklmnopqrstuvwxyz\n" for i in range(110))
    first = service.apply_command(command(preview(service, first_text)))
    path = service.scope.database_path.parent / "demo.md"
    path.write_text(second_text, encoding="utf-8")
    library.import_path(path)
    current = service.list_sources()[0]
    with UnitOfWork(library._session_factory) as uow:
        old_lineages = {
            unit.lineage_id for unit in uow.knowledge_units.list_by_document(first.document_id)
        }
        new_lineages = {
            unit.lineage_id for unit in uow.knowledge_units.list_by_document(current.document_id)
        }
        assert len(old_lineages) == len(new_lineages) == 110
        assert old_lineages.isdisjoint(new_lineages)
    before = counts(library)
    with pytest.raises(MutationError) as rejected:
        preview(service, first_text)
    assert rejected.value.status_code == 413
    assert counts(library) == before
