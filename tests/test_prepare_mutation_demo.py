from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from scripts import prepare_mutation_demo as demo


def make_database(path: Path, *, mutations: bool = True) -> list[str]:
    """单元测试生成全新 SQLite，不复制业务库，不生成身份声明。"""
    source_id, dataset_id = uuid4(), uuid4()
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            "CREATE TABLE sources (id TEXT, kind TEXT);"
            "CREATE TABLE documents (source_id TEXT, content_type TEXT);"
            "CREATE TABLE auto_evaluation_config (id INTEGER, enabled INTEGER, "
            "dataset_id TEXT, dataset_version INTEGER, dataset_hash TEXT);"
            "CREATE TABLE evaluation_sets (id TEXT, version INTEGER, content_hash TEXT);"
        )
        connection.execute("INSERT INTO sources VALUES (?, 'file')", (source_id.hex,))
        connection.execute("INSERT INTO documents VALUES (?, 'markdown')", (source_id.hex,))
        connection.execute(
            "INSERT INTO auto_evaluation_config VALUES (1, 1, ?, 1, ?)",
            (dataset_id.hex, "a" * 64),
        )
        connection.execute(
            "INSERT INTO evaluation_sets VALUES (?, 1, ?)", (dataset_id.hex, "a" * 64)
        )
        if mutations:
            connection.executescript(
                "CREATE TABLE mutation_previews (id TEXT);CREATE TABLE mutation_commands (id TEXT);"
            )
        connection.commit()
    finally:
        connection.close()
    path.chmod(0o600)
    return [str(source_id)]


def write_manifest(manifest: Path, payload: dict[str, Any]) -> None:
    manifest.write_text(json.dumps(payload))
    manifest.chmod(0o600)


@pytest.fixture
def owned_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setattr(demo, "ROOT", tmp_path)
    root = tmp_path / ".knowledge" / "mutation-demo"
    root.mkdir(parents=True, mode=0o700)
    scope_id = str(uuid4())
    parent = root / scope_id
    parent.mkdir(mode=0o700)
    seed = parent / ("seed-" + uuid4().hex)
    seed.mkdir(mode=0o700)
    database = seed / "knowledge.db"
    sources = make_database(database)
    report = seed / "report.json"
    report.write_text(json.dumps({"status": "passed", "artifacts": {"database": "knowledge.db"}}))
    report.chmod(0o600)
    manifest = parent / "mutation-manifest.json"
    write_manifest(
        manifest,
        {
            "kind": demo.KIND,
            "scope_id": scope_id,
            "database": database.relative_to(parent).as_posix(),
            "allowed_source_ids": sources,
            "created_at": "2026-11-17T00:00:00+00:00",
        },
    )
    return manifest, database


def test_owned_generated_scope_readonly(owned_demo: tuple[Path, Path]) -> None:
    manifest, database = owned_demo
    before = database.read_bytes()
    assert demo.validate_demo(manifest, database) == manifest
    assert database.read_bytes() == before
    assert demo.database_sources(database) == json.loads(manifest.read_text())["allowed_source_ids"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "other"),
        ("scope_id", "bad-uuid"),
        ("database", "../knowledge.db"),
        ("database", "/knowledge.db"),
        ("allowed_source_ids", ["bad-uuid"]),
        ("created_at", "not-iso"),
        ("extra", "unwanted"),
        ("allowed_source_ids", []),
    ],
)
def test_strict_backend_manifest_dto(
    owned_demo: tuple[Path, Path],
    field: str,
    value: object,
) -> None:
    manifest, database = owned_demo
    payload = json.loads(manifest.read_text())
    payload[field] = value
    write_manifest(manifest, payload)
    with pytest.raises(demo.DemoError):
        demo.validate_demo(manifest, database)


@pytest.mark.parametrize("target", ["manifest", "database", "parent", "seed"])
def test_reject_symlink_components(owned_demo: tuple[Path, Path], target: str) -> None:
    manifest, database = owned_demo
    path = {
        "manifest": manifest,
        "database": database,
        "parent": manifest.parent,
        "seed": database.parent,
    }[target]
    saved = path.with_name(path.name + "-saved")
    path.rename(saved)
    path.symlink_to(saved, target_is_directory=saved.is_dir())
    with pytest.raises(demo.DemoError):
        demo.validate_demo(manifest, database)


@pytest.mark.parametrize(
    "target,mode", [("manifest", 0o644), ("database", 0o644), ("parent", 0o755)]
)
def test_private_modes_required(owned_demo: tuple[Path, Path], target: str, mode: int) -> None:
    manifest, database = owned_demo
    {"manifest": manifest, "database": database, "parent": manifest.parent}[target].chmod(mode)
    with pytest.raises(demo.DemoError):
        demo.validate_demo(manifest, database)


def test_hardlink_owner_and_dbmatch(
    owned_demo: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, database = owned_demo
    outside = tmp_path / "other.db"
    make_database(outside)
    with pytest.raises(demo.DemoError):
        demo.validate_demo(manifest, outside)
    os.link(database, tmp_path / "linked.db")
    with pytest.raises(demo.DemoError):
        demo.validate_demo(manifest, database)
    (tmp_path / "linked.db").unlink()
    uid = os.getuid()
    monkeypatch.setattr("scripts.prepare_mutation_demo.os.getuid", lambda: uid + 1)
    with pytest.raises(demo.DemoError):
        demo.validate_demo(manifest, database)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE auto_evaluation_config SET enabled=0",
        "DELETE FROM evaluation_sets",
        "UPDATE sources SET kind='database'",
        "UPDATE documents SET content_type='binary'",
        "DROP TABLE mutation_commands",
    ],
)
def test_config_and_file_source_bounds(owned_demo: tuple[Path, Path], sql: str) -> None:
    manifest, database = owned_demo
    with sqlite3.connect(database) as connection:
        connection.execute(sql)
    with pytest.raises(demo.DemoError):
        demo.validate_demo(manifest, database)


def test_duplicate_json_and_source_uuid(owned_demo: tuple[Path, Path]) -> None:
    manifest, database = owned_demo
    payload = json.loads(manifest.read_text())
    payload["allowed_source_ids"] *= 2
    write_manifest(manifest, payload)
    with pytest.raises(demo.DemoError):
        demo.validate_demo(manifest, database)
    manifest.write_text('{"kind":"a","kind":"b"}')
    with pytest.raises(demo.DemoError):
        demo.validate_demo(manifest, database)


def test_missing_dependencies_safe_no_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(demo, "ROOT", tmp_path)

    def unavailable(_name: str) -> None:
        raise ImportError("raw-stack /private/path secret")

    monkeypatch.setattr("scripts.prepare_mutation_demo.importlib.import_module", unavailable)
    assert demo.main([]) == 1
    assert "MUTATION_DEPENDENCIES_UNAVAILABLE" in capsys.readouterr().out
    assert not (tmp_path / ".knowledge").exists()


def test_core_help_without_site_dependencies() -> None:
    result = subprocess.run(
        [sys.executable, "-S", "scripts/prepare_mutation_demo.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert "Traceback" not in result.stderr


def test_local_environment_no_credentials_and_restored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_MUTATION_KEY", "test-runtime-only")
    monkeypatch.setenv("OTHER_TOKEN", "test-token")
    monkeypatch.setenv("VITE_KEY", "test-token")
    before = dict(os.environ)
    with demo.local_environment():
        assert not any(
            "KEY" in name or "TOKEN" in name or name.startswith("VITE_") for name in os.environ
        )
    assert dict(os.environ) == before


def test_prepare_runner_new_database_schema_only_and_unique(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import real_knowledge_acceptance

    from knowledge.mutations import tables

    monkeypatch.setattr(demo, "ROOT", tmp_path)
    runs: list[Path] = []
    schema_calls: list[object] = []
    original_schema = tables.create_mutation_schema

    def schema(engine: Any) -> None:
        schema_calls.append(engine)
        original_schema(engine)

    class TestRunner:
        def __init__(self, parent: Path) -> None:
            self.run_dir = parent / ("seed-" + uuid4().hex)
            self.run_dir.mkdir(mode=0o700)
            self.database = self.run_dir / "knowledge.db"
            runs.append(self.database)

        def run(self) -> Path:
            assert "KNOWLEDGE_MUTATION_KEY" not in os.environ
            make_database(self.database, mutations=False)
            report = self.run_dir / "report.json"
            report.write_text(
                json.dumps({"status": "passed", "artifacts": {"database": "knowledge.db"}})
            )
            return report

    monkeypatch.setattr(real_knowledge_acceptance, "Runner", TestRunner)
    monkeypatch.setattr(tables, "create_mutation_schema", schema)
    one, two = demo.prepare(), demo.prepare()
    assert one["status"] == two["status"] == "ready"
    assert one["scope_id"] != two["scope_id"]
    assert len(schema_calls) == len(runs) == 2
    assert set(one) == {"status", "manifest", "database", "scope_id", "source_ids"}
    for result in (one, two):
        manifest = tmp_path / str(result["manifest"])
        database = tmp_path / str(result["database"])
        assert demo.validate_demo(manifest, database) == manifest
        assert manifest.stat().st_mode & 0o777 == 0o600
        assert manifest.parent.stat().st_mode & 0o777 == 0o700
        assert set(json.loads(manifest.read_text())) == {
            "kind",
            "scope_id",
            "database",
            "allowed_source_ids",
            "created_at",
        }


def test_prepare_reject_existing_uuid_no_overwrite(
    owned_demo: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import UUID

    manifest, database = owned_demo
    before = database.read_bytes()
    monkeypatch.setattr(demo, "uuid4", lambda: UUID(manifest.parent.name))
    with pytest.raises(demo.DemoError, match="DEMO_PREPARATION_FAILED"):
        demo.prepare()
    assert database.read_bytes() == before


def test_prepare_symlink_root_no_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo, "ROOT", tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".knowledge").symlink_to(outside, target_is_directory=True)
    with pytest.raises(demo.DemoError, match="INVALID_DEMO_PATH"):
        demo.prepare()
    assert not list(outside.iterdir())
