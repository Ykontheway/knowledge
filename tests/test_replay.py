from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from scripts.export_replay import main
from sqlalchemy import Engine, event

from konwledge.api.management_service import ManagementService
from konwledge.replay import ReplayBundle, ReplayError, export_replay, load_validate, producer
from konwledge.replay.bundle import MAX_BYTES, loads_validate
from konwledge.replay.corpus import DOCUMENT_TEXTS, SEGMENTS
from konwledge.storage.full_text import fts_document


@pytest.fixture(scope="module")
def static_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("public-replay")
    previous = Path.cwd()
    os.chdir(root)
    try:
        output = root / "replay.json"
        export_replay(output)
        return output
    finally:
        os.chdir(previous)


@pytest.fixture
def raw(static_file: Path) -> dict[str, Any]:
    return json.loads(static_file.read_bytes())  # type: ignore[no-any-return]


def encoded(raw: dict[str, Any]) -> bytes:
    return json.dumps(raw, ensure_ascii=False).encode()


def snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_real_story_frozen_pins_metrics_history_and_exact_b1(static_file: Path) -> None:
    bundle = load_validate(static_file)
    r = bundle.resources
    jobs = {job.id: job for job in r.jobs}
    sequence = tuple(
        jobs[identifier]
        for identifier in (
            bundle.story.reference_job_id,
            bundle.story.candidate_job_id,
            bundle.story.recovery_job_id,
        )
    )
    assert [job.status.value for job in sequence] == ["passed", "failed", "passed"]
    assert [job.error_code for job in sequence] == [None, "QUALITY_GATE_FAILED", None]
    assert [job.report.metrics.mean_recall for job in sequence if job.report] == [1, 2 / 3, 1]
    assert len({(j.dataset_id, j.dataset_version, j.dataset_hash) for j in sequence}) == 1
    assert len({(j.config_generation, j.config_fingerprint) for j in sequence}) == 1
    assert len(r.documents) == 4 and len(r.units) == 12 and len(r.lineages) == 3
    assert len(r.revisions) == 16 and len(r.evidence) == 12 and len(r.diffs) == 16
    assert {d.checksum for d in r.documents} == set(DOCUMENT_TEXTS)
    assert bundle.generated_at.utcoffset() is not None
    assert all(rev.created_at < bundle.generated_at for rev in r.revisions)
    for doc in r.documents:
        assert doc.units.limit == 100 and doc.units.offset == 0
        assert doc.units.total == len(doc.units.items)
    for lineage in r.lineages:
        assert lineage.versions.total == len(lineage.versions.items) == 4
    for diff in r.diffs:
        assert diff.changes.total == len(diff.changes.items) == 3
    for ev in r.evidence:
        assert (ev.document_checksum, ev.start_char, ev.end_char, ev.text) in SEGMENTS
        assert ev.content_hash == hashlib.sha256(ev.text.encode()).hexdigest()
    text = static_file.read_text()
    for denied in (
        str(static_file.parent),
        "sqlite+pysqlite:",
        "localcache",
        "metadata",
        "rawquery",
        "credentials",
        "locator",
        "baseline",
        "results",
    ):
        assert denied not in text
    assert static_file.stat().st_size < MAX_BYTES
    report = next(static_file.parent.glob(".konwledge/replay/*/report.json"))
    assert stat.S_IMODE(report.stat().st_mode) == 0o600
    assert stat.S_IMODE(report.parent.stat().st_mode) == 0o700
    assert json.loads(report.read_text())["bundle_bytes"] == static_file.stat().st_size


@pytest.mark.parametrize(
    "resource", ["jobs", "revisions", "documents", "lineages", "units", "evidence", "diffs"]
)
def test_duplicate_resources_rejected(raw: dict[str, Any], resource: str) -> None:
    raw["resources"][resource].append(copy.deepcopy(raw["resources"][resource][0]))
    with pytest.raises(ReplayError, match="REPLAY_DUPLICATE_ID"):
        loads_validate(encoded(raw))


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_source",
        "unknown_unit",
        "missing_unit",
        "missing_evidence",
        "missing_revision",
        "missing_lineage",
        "missing_diff",
        "broken_prev",
        "foreign_href",
        "hash_anchor",
        "wrong_checksum",
        "unknown_text",
        "wrong_offset",
        "page_total",
        "page_limit",
        "page_offset",
        "broken_story",
        "changed_dataset",
        "changed_config",
        "wrong_status",
        "naive_time",
        "time_before_publication",
        "diff_count",
        "diff_unit",
        "diff_kind",
        "revision_document",
        "revision_unit",
        "report_details",
        "source_path",
        "metadata",
        "schema_bool",
        "case_count_bool",
    ],
)
def test_strict_corruption_rejected(raw: dict[str, Any], mutation: str) -> None:
    r = raw["resources"]
    unknown = str(uuid4())
    if mutation == "unknown_source":
        r["units"][0]["source_id"] = unknown
    elif mutation == "unknown_unit":
        r["evidence"][0]["unit_id"] = unknown
    elif mutation.startswith("missing_"):
        name = {
            "unit": "units",
            "evidence": "evidence",
            "revision": "revisions",
            "lineage": "lineages",
            "diff": "diffs",
        }[mutation.removeprefix("missing_")]
        r[name].pop()
    elif mutation == "broken_prev":
        r["documents"][0]["previous_document_id"] = unknown
    elif mutation == "foreign_href":
        r["units"][0]["links"][0]["href"] += "?secret=credential"
    elif mutation == "hash_anchor":
        ev = r["evidence"][0]
        rev = next(item for item in r["revisions"] if item["id"] == ev["revision_ids"][0])
        rev["navigation"]["content_hash"] = "a" * 64
    elif mutation == "wrong_checksum":
        r["documents"][0]["checksum"] = "a" * 64
    elif mutation == "unknown_text":
        r["evidence"][0]["text"] = "/private/business 原文 credentials password"
    elif mutation == "wrong_offset":
        r["evidence"][0]["start_char"] += 1
    elif mutation.startswith("page_"):
        key, value = {
            "page_total": ("total", 99),
            "page_limit": ("limit", 20),
            "page_offset": ("offset", 1),
        }[mutation]
        r["documents"][0]["units"][key] = value
    elif mutation == "broken_story":
        raw["story"]["candidate_job_id"] = unknown
    elif mutation == "changed_dataset":
        r["jobs"][0]["dataset_hash"] = "a" * 64
    elif mutation == "changed_config":
        r["jobs"][0]["config_generation"] += 1
    elif mutation == "wrong_status":
        r["jobs"][0]["status"] = "queued"
    elif mutation == "naive_time":
        raw["generated_at"] = "2026-01-01T00:00:00"
    elif mutation == "time_before_publication":
        raw["generated_at"] = "2000-01-01T00:00:00Z"
    elif mutation == "diff_count":
        r["diffs"][0]["counts"]["modified"] += 1
    elif mutation == "diff_unit":
        r["diffs"][0]["changes"]["items"][0]["new"]["id"] = unknown
    elif mutation == "diff_kind":
        r["diffs"][0]["changes"]["items"][0]["kind"] = "removed"
    elif mutation == "revision_document":
        r["revisions"][0]["navigation"]["document_id"] = unknown
    elif mutation == "revision_unit":
        r["revisions"][0]["affected_unit_ids"].append(unknown)
    elif mutation == "report_details":
        r["jobs"][0]["report"]["details"] = {"query": "business secret"}
    elif mutation == "source_path":
        r["documents"][0]["source_path"] = "/private/path"
    elif mutation == "metadata":
        r["units"][0]["metadata"] = {"credentials": "not public"}
    elif mutation == "schema_bool":
        raw["schema_version"] = True
    elif mutation == "case_count_bool":
        r["jobs"][0]["report"]["metrics"]["case_count"] = True
    else:
        raise AssertionError(mutation)
    with pytest.raises(ReplayError) as error:
        loads_validate(encoded(raw))
    assert str(error.value).startswith("REPLAY_")
    assert "business" not in str(error.value) and "/private" not in str(error.value)


@pytest.mark.parametrize(
    "data",
    [b"", b"[1]", b"{", b"\xff", b"{}", b'{"schema_version":1,"schema_version":1}', b"[" * 2000],
)
def test_invalid_json_safe(data: bytes) -> None:
    with pytest.raises(ReplayError):
        loads_validate(data)


def test_oversized_input_and_resource_limit(raw: dict[str, Any]) -> None:
    with pytest.raises(ReplayError, match="REPLAY_SIZE_INVALID"):
        loads_validate(b" " * (MAX_BYTES + 1))
    raw["resources"]["units"] *= 9
    with pytest.raises(ReplayError, match="REPLAY_SCHEMA_INVALID"):
        loads_validate(encoded(raw))


def test_check_zero_writes_and_no_sdk_or_database(
    static_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = snapshot(static_file.parent)

    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("validation must not open SDK/database")

    monkeypatch.setattr(producer, "KnowledgeLibrary", denied)
    monkeypatch.setattr(ManagementService, "read_session", denied)
    monkeypatch.setattr(sqlite3, "connect", denied)
    assert main(["--check", "--output", str(static_file)]) == 0
    assert capsys.readouterr().out == "REPLAY_VALID\n"
    assert snapshot(static_file.parent) == before


@pytest.mark.parametrize(
    "option", ["--database", "--manifest", "--URL", "--input", "--force", "--out"]
)
def test_cli_never_accepts_business_inputs_or_reflects_arguments(
    option: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        main([option, "/private/business?credential=SECRET"])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "REPLAY_ARGUMENT_INVALID\n"


@pytest.mark.parametrize(
    "kind",
    [
        "existing",
        "dangling_symlink",
        "file_symlink",
        "parent_symlink",
        "directory",
        "fifo",
        "missing_parent",
    ],
)
def test_public_output_refusal_before_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "out.json"
    if kind == "existing":
        output.write_bytes(b"keep")
    elif kind in {"dangling_symlink", "file_symlink"}:
        target = tmp_path / "target"
        if kind == "file_symlink":
            target.write_bytes(b"keep")
        output.symlink_to(target)
    elif kind == "parent_symlink":
        target = tmp_path / "actual"
        target.mkdir()
        (tmp_path / "alias").symlink_to(target, target_is_directory=True)
        output = tmp_path / "alias" / "out.json"
    elif kind == "directory":
        output.mkdir()
    elif kind == "fifo":
        os.mkfifo(output)
    elif kind == "missing_parent":
        output = tmp_path / "absent" / "out.json"
    with pytest.raises(ReplayError):
        export_replay(output)
    assert not (tmp_path / ".konwledge").exists()
    if kind == "existing":
        assert output.read_bytes() == b"keep"


@pytest.mark.parametrize(
    "kind", ["file_symlink", "parent_symlink", "fifo", "directory", "oversized", "missing"]
)
def test_static_read_rejects_unsafe_file(tmp_path: Path, static_file: Path, kind: str) -> None:
    output = tmp_path / "replay.json"
    if kind == "file_symlink":
        output.symlink_to(static_file)
    elif kind == "parent_symlink":
        (tmp_path / "alias").symlink_to(static_file.parent, target_is_directory=True)
        output = tmp_path / "alias" / static_file.name
    elif kind == "fifo":
        os.mkfifo(output)
    elif kind == "directory":
        output.mkdir()
    elif kind == "oversized":
        with output.open("wb") as stream:
            stream.truncate(MAX_BYTES + 1)
    with pytest.raises(ReplayError):
        load_validate(output)


def test_private_root_symlink_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".konwledge").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ReplayError, match="REPLAY_FILE_UNSAFE"):
        export_replay(tmp_path / "out.json")
    assert not list(outside.iterdir()) and not (tmp_path / "out.json").exists()


def test_fresh_scopes_and_external_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    first = export_replay(tmp_path / "external-first.json")
    second = export_replay(tmp_path / "external-second.json")
    assert first.story != second.story
    assert len(list((repo / ".konwledge/replay").iterdir())) == 2
    assert not (repo / "web").exists()


def capture_seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> producer._Seed:
    monkeypatch.chdir(tmp_path)
    captured: list[producer._Seed] = []
    original = producer._collect

    def collect(seed: producer._Seed) -> ReplayBundle:
        captured.append(seed)
        return original(seed)

    with monkeypatch.context() as patch:
        patch.setattr(producer, "_collect", collect)
        export_replay(tmp_path / "replay.json")
    return captured[0]


@pytest.mark.parametrize(
    "poison",
    ["scope_outside", "foreign_source", "unknown_document", "unknown_unit", "unsafe_corpus"],
)
def test_internal_collector_refuses_scope_and_unknown_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, poison: str
) -> None:
    seed = capture_seed(tmp_path, monkeypatch)
    if poison == "scope_outside":
        seed.scope = tmp_path / "outside"
    elif poison == "foreign_source":
        seed.source_id = uuid4()
    elif poison == "unknown_document":
        seed.documents.add(uuid4())
    elif poison == "unknown_unit":
        seed.units.add(uuid4())
    elif poison == "unsafe_corpus":
        (seed.scope / "synthetic.md").write_text("business raw source; never redact this")
    with pytest.raises(ReplayError):
        producer._collect(seed)


def test_management_projection_and_validation_are_zero_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = capture_seed(tmp_path, monkeypatch)
    before = snapshot(tmp_path)
    statements: list[str] = []

    def observed(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", observed)
    try:
        bundle = producer._collect(seed)
        loads_validate(bundle.model_dump_json().encode())
    finally:
        event.remove(Engine, "before_cursor_execute", observed)
    assert statements and all(s.lstrip().upper().startswith("SELECT") for s in statements)
    assert snapshot(tmp_path) == before
    assert len(seed.library.automatic_evaluation.history()) == 3


def test_failure_validates_before_any_public_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    original = producer._collect

    def broken(seed: producer._Seed) -> ReplayBundle:
        bundle = original(seed)
        ev = bundle.resources.evidence[0].model_copy(update={"text": "business secret"})
        resources = bundle.resources.model_copy(
            update={"evidence": (ev, *bundle.resources.evidence[1:])}
        )
        return bundle.model_copy(update={"resources": resources})

    monkeypatch.setattr(producer, "_collect", broken)
    output = tmp_path / "out.json"
    assert main(["--output", str(output)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "REPLAY_CORPUS_INVALID\n"
    assert not output.exists()


def test_unexpected_sdk_error_stderr_is_fixed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("/private/source credentials rawquery")

    monkeypatch.setattr(producer, "create_schema", fail)
    assert main(["--output", str(tmp_path / "out.json")]) == 1
    assert capsys.readouterr().err == "REPLAY_OPERATION_FAILED\n"


def test_optional_import_boundary() -> None:
    code = (
        "import sys, importlib.abc; "
        "blocked=('fastapi','uvicorn','mcp','tiktoken','httpx','openai','lancedb'); "
        "exec('class Block(importlib.abc.MetaPathFinder):\\n"
        " def find_spec(self, fullname, path=None, target=None):\\n"
        '  if fullname.split(".")[0] in blocked: raise AssertionError(fullname)\'); '
        "sys.meta_path.insert(0,Block()); "
        "from konwledge.replay import export_replay, load_validate; "
        "assert not any(n.split('.')[0] in blocked for n in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("kind", ["missing_links", "missing_affected", "revision_gap"])
def test_navigation_completeness_rejected(raw: dict[str, Any], kind: str) -> None:
    revision = raw["resources"]["revisions"][0]
    if kind == "missing_links":
        raw["resources"]["units"][0]["links"].pop()
    elif kind == "missing_affected":
        revision["affected_document_ids"] = []
    else:
        revision["revision"] = 99
    with pytest.raises(ReplayError):
        loads_validate(encoded(raw))


@pytest.mark.parametrize("kind", ["database_link", "extra_source", "extra_unit", "scope_collision"])
def test_owned_scope_actual_storage_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    seed = capture_seed(tmp_path, monkeypatch)
    database = seed.scope / "knowledge.db"
    if kind == "scope_collision":
        before = snapshot(tmp_path)
        monkeypatch.setattr(producer, "uuid4", lambda: UUID(seed.scope.name))
        with pytest.raises(ReplayError):
            export_replay(tmp_path / "second.json")
        assert snapshot(tmp_path) == before
        return
    if kind == "database_link":
        moved = seed.scope / "own-original.db"
        database.rename(moved)
        database.symlink_to(moved)
    else:
        with sqlite3.connect(database) as connection:
            connection.create_function("knowledge_fts_text", 1, fts_document, deterministic=True)
            if kind == "extra_source":
                connection.execute(
                    "INSERT INTO sources (id, kind, uri, created_at, metadata) "
                    "VALUES (?, 'file', '/foreign/source', '2000-01-01T00:00:00Z', '{}')",
                    (uuid4().hex,),
                )
            else:
                connection.execute(
                    "INSERT INTO knowledge_units "
                    "(id, lineage_id, document_id, ordinal, text, start_char, end_char, "
                    "heading, section_path, status, tags, metadata) "
                    "SELECT ?, lineage_id, document_id, 99, text, start_char, end_char, "
                    "heading, section_path, status, tags, metadata FROM knowledge_units LIMIT 1",
                    (uuid4().hex,),
                )
    before = snapshot(tmp_path)
    with pytest.raises(ReplayError):
        producer._collect(seed)
    assert snapshot(tmp_path) == before


def test_invalid_static_check_zero_writes_fixed_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "invalid.json"
    path.write_bytes(b'{"database":"/private/business credentials"}')
    before = snapshot(tmp_path)
    assert main(["--check", "--output", str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "REPLAY_SCHEMA_INVALID\n"
    assert snapshot(tmp_path) == before
