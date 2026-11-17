from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from konwledge.api.app import create_app
from konwledge.application import KnowledgeLibrary
from konwledge.domain import EvaluationItem, EvaluationSet
from konwledge.evaluation import EvaluationService
from konwledge.mutations.safety import load_mutation_scope
from konwledge.mutations.tables import create_mutation_schema
from konwledge.storage import create_schema, create_session_factory, create_sqlite_engine

WRITE_KEY = "write-key"
READ_KEY = "read-key"
ORIGIN = "http://127.0.0.1:5173"
ACTOR = "demo-editor"


def _demo(tmp_path: Path) -> tuple[KnowledgeLibrary, Path, dict[str, object]]:
    content = tmp_path / "demo.md"
    content.write_text("# Demo\n\nhello", encoding="utf-8")
    database = tmp_path / "knowledge.db"
    engine = create_sqlite_engine(f"sqlite+pysqlite:///{database.as_posix()}")
    create_schema(engine)
    create_mutation_schema(engine)
    library = KnowledgeLibrary(create_session_factory(engine))
    result = library.import_path(content).imported[0].result
    source_id = result.ingestion.document.source_id
    dataset = EvaluationSet(
        id=uuid4(),
        name="mutation integration",
        version=1,
        created_at=result.ingestion.document.ingested_at,
        items=(
            EvaluationItem(
                id="hello",
                query="hello",
                expected_lineage_ids=frozenset({result.units[0].lineage_id}),
            ),
        ),
    )
    EvaluationService(library._session_factory, library._retrieval).import_set(dataset)
    library.automatic_evaluation.enable(dataset.id, version=1)
    tmp_path.chmod(0o700)
    database.chmod(0o600)
    manifest: dict[str, object] = {
        "kind": "konwledge-mutation-demo-v1",
        "scope_id": str(uuid4()),
        "database": "knowledge.db",
        "allowed_source_ids": [str(source_id)],
        "created_at": "2026-11-17T00:00:00Z",
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_path.chmod(0o600)
    return library, manifest_path, manifest


def _client(library: KnowledgeLibrary, manifest_path: Path) -> TestClient:
    return TestClient(
        create_app(
            library,
            api_key=READ_KEY,
            enable_mutations=True,
            mutation_manifest=manifest_path,
            mutation_origin=ORIGIN,
            mutation_key=WRITE_KEY,
            mutation_actor=ACTOR,
        ),
        raise_server_exceptions=False,
    )


def test_mutations_disabled_by_default_returns_404(tmp_path: Path) -> None:
    library, _manifest_path, _manifest = _demo(tmp_path)
    with TestClient(create_app(library), raise_server_exceptions=False) as client:
        response = client.get("/v1/mutations/session")
    assert response.status_code == 404


def test_manifest_loader_rejects_disjoint_database(tmp_path: Path) -> None:
    _library, manifest_path, _manifest = _demo(tmp_path)
    other = tmp_path / "other.db"
    other.write_text("", encoding="utf-8")
    try:
        load_mutation_scope(manifest_path, other)
    except ValueError as exc:
        assert "manifest" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("manifest should have been rejected")


def test_session_document_preview_auth_and_strict_headers(tmp_path: Path) -> None:
    library, manifest_path, _manifest = _demo(tmp_path)
    with _client(library, manifest_path) as client:
        base_headers = {"Authorization": f"Bearer {WRITE_KEY}", "Origin": ORIGIN}
        read_key = client.get(
            "/v1/mutations/session",
            headers={"Authorization": f"Bearer {READ_KEY}", "Origin": ORIGIN},
        )
        assert read_key.status_code == 403

        session = client.get("/v1/mutations/session", headers=base_headers)
        assert session.status_code == 200
        source = session.json()["sources"][0]
        document = client.get(
            f"/v1/mutations/documents/{source['document_id']}", headers=base_headers
        )
        assert document.status_code == 200
        assert document.json()["text"] == "# Demo\n\nhello"

        preview = client.post(
            "/v1/mutations/previews",
            headers={
                **base_headers,
                "X-Knowledge-Intent": "document-update",
                "Content-Type": "application/json",
            },
            json={
                "scope_id": session.json()["scope_id"],
                "source_id": source["source_id"],
                "document_id": source["document_id"],
                "expected_checksum": source["checksum"],
                "text": "# Demo\n\nhello world",
            },
        )
        assert preview.status_code == 200
        assert preview.json()["changed"] is True
        assert preview.json()["counts"]["modified"] == 1

        missing_intent = client.post(
            "/v1/mutations/previews",
            headers={**base_headers, "Content-Type": "application/json"},
            json={},
        )
        assert missing_intent.status_code == 400


def test_default_app_preserves_read_auth_and_never_creates_mutation_schema(tmp_path: Path) -> None:
    from sqlalchemy import inspect

    engine = create_sqlite_engine(f"sqlite+pysqlite:///{tmp_path / 'default.db'}")
    create_schema(engine)
    library = KnowledgeLibrary(create_session_factory(engine))
    before = set(inspect(engine).get_table_names())
    assert {"mutation_previews", "mutation_commands"}.isdisjoint(before)
    with TestClient(create_app(library, api_key=READ_KEY), raise_server_exceptions=False) as client:
        assert client.get("/v1/models").status_code == 401
        assert (
            client.get("/v1/models", headers={"Authorization": f"Bearer {READ_KEY}"}).status_code
            == 200
        )
        assert (
            client.get(
                "/v1/mutations/session", headers={"Authorization": f"Bearer {READ_KEY}"}
            ).status_code
            == 404
        )
    assert set(inspect(engine).get_table_names()) == before
    assert library.automatic_evaluation.status() is None
    engine.dispose()
