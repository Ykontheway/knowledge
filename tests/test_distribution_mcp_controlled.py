"""B6 分发守卫单元/合成 helper 测试；真正 wheel/sdist 通过由 installer 判定。"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from scripts import installed_mcp_controlled_smoke as smoke
from scripts import installed_mcp_smoke as b5
from scripts import verify_distribution as distribution

from test_distribution import (
    NAME,
    RESOURCE,
    SDIST_ROOT,
    VERSION,
    WHEEL_METADATA,
    write_sdist,
    write_wheel,
)


def safe_summary() -> dict[str, Any]:
    return {
        "version": VERSION,
        "passed": True,
        "mode": "controlled_extra",
        "sdk_version": "1.30.0",
        "pydantic_version": "2.14.1",
        "checks": list(smoke.CHECKS),
        "counts": {
            "runtime_modules": 9,
            "tools": 10,
            "quality_cases": 4,
            "commands": 3,
            "jobs": 3,
            "passed_jobs": 2,
            "failed_jobs": 1,
            "consumed_grants": 3,
            "sessions": 5,
            "pty_approvals": 3,
            "rejected_calls": 16,
            "successful_calls": 30,
            "protocol_responses": 52,
            "seed_files": 7,
        },
    }


def test_explicit_runtime_and_sdist_contract() -> None:
    assert tuple(f"konwledge/mcp/{name}.py" for name in smoke.MODULES) == distribution.MCP_MODULES
    assert len(distribution.MCP_MODULES) == 9
    assert distribution.MCP_CONTROLLED_CHECKS == smoke.CHECKS
    assert {
        "scripts/installed_mcp_controlled_smoke.py",
        "tests/test_mcp_controlled_service.py",
        "tests/test_mcp_approval_cli.py",
        "tests/test_mcp_controlled_protocol.py",
        "tests/test_distribution_mcp_controlled.py",
        "docs/mcp-controlled.md",
    } <= set(distribution.MCP_SDIST_FILES)
    assert len(b5.TOOLS) == 5 and "apply_document_update" not in b5.TOOLS


@pytest.mark.parametrize("module", smoke.MODULES)
@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_each_b6_module_is_required(tmp_path: Path, module: str, kind: str) -> None:
    packaged = f"konwledge/mcp/{module}.py"
    if kind == "wheel":
        artifact = tmp_path / "bad.whl"
        write_wheel(artifact, omit=(packaged,))
        with pytest.raises(ValueError, match="missing packaged file"):
            distribution.inspect_wheel(artifact, NAME, VERSION, (RESOURCE,))
    else:
        artifact = tmp_path / "bad.tar.gz"
        write_sdist(artifact, omit=(f"{SDIST_ROOT}/src/{packaged}",))
        with pytest.raises(ValueError, match="missing source file"):
            distribution.inspect_sdist(artifact, NAME, VERSION)


@pytest.mark.parametrize("filename", distribution.MCP_SDIST_FILES)
def test_each_test_doc_smoke_is_required_without_missing_doc_bypass(
    tmp_path: Path,
    filename: str,
) -> None:
    artifact = tmp_path / "bad.tar.gz"
    write_sdist(artifact, omit=(f"{SDIST_ROOT}/{filename}",))
    with pytest.raises(ValueError, match="missing source file"):
        distribution.inspect_sdist(artifact, NAME, VERSION)


@pytest.mark.parametrize("dependency", ["pytest", "ruff", "mypy", "jsonschema", "openai"])
@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_no_dev_group_becomes_runtime(tmp_path: Path, dependency: str, kind: str) -> None:
    metadata = WHEEL_METADATA + f"Requires-Dist: {dependency}\n"
    if kind == "wheel":
        artifact = tmp_path / "bad.whl"
        write_wheel(artifact, overrides={"konwledge-0.1.0.dist-info/METADATA": metadata})
        with pytest.raises(ValueError, match="SDK/test runtime"):
            distribution.inspect_wheel(artifact, NAME, VERSION, (RESOURCE,))
    else:
        artifact = tmp_path / "bad.tar.gz"
        write_sdist(artifact, overrides={f"{SDIST_ROOT}/PKG-INFO": metadata})
        with pytest.raises(ValueError, match="SDK/test runtime"):
            distribution.inspect_sdist(artifact, NAME, VERSION)


def test_safe_summary_only_names_counts_versions() -> None:
    value = safe_summary()
    assert distribution.load_mcp_controlled_summary(json.dumps(value), VERSION) == value
    rendered = json.dumps(value)
    assert "/" not in rendered and "approval_token" not in rendered


@pytest.mark.parametrize(
    "updates",
    [
        {"version": "9.9.9"},
        {"passed": False},
        {"mode": "extra"},
        {"checks": []},
        {"checks": ["/private/token"]},
        {"sdk_version": "1.29.9"},
        {"sdk_version": "2.0.0"},
        {"pydantic_version": "private exception"},
        {"approval_token": "private token"},
        {"database": "/business/knowledge.db"},
        {"raw_exception": "private SQL"},
        {"counts": {}},
    ],
)
def test_parent_rejects_untrusted_summary_without_reflection(updates: dict[str, Any]) -> None:
    with pytest.raises(RuntimeError, match="safe schema/check/count") as error:
        distribution.load_mcp_controlled_summary(json.dumps(safe_summary() | updates), VERSION)
    assert "private" not in str(error.value) and "/business" not in str(error.value)


@pytest.mark.parametrize("key", list(safe_summary()["counts"]))
@pytest.mark.parametrize("bad", [True, -1, "3", 0])
def test_parent_rejects_each_bad_count(key: str, bad: Any) -> None:
    value = safe_summary()
    value["counts"][key] = bad
    with pytest.raises(RuntimeError, match="safe schema/check/count"):
        distribution.load_mcp_controlled_summary(json.dumps(value), VERSION)


@pytest.mark.parametrize("stdout", ["private exception/token", "[]", "null"])
def test_parent_nonjson_or_wrong_shape_fails_safe(stdout: str) -> None:
    with pytest.raises(RuntimeError) as error:
        distribution.load_mcp_controlled_summary(stdout, VERSION)
    assert stdout not in str(error.value)


@pytest.mark.parametrize("returncode", [1, 130])
def test_nonzero_smoke_cannot_claim_passing_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
) -> None:
    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command == [
            str(tmp_path / "python"),
            "-I",
            str(tmp_path / "smoke.py"),
            "--expected-version",
            VERSION,
        ]
        assert kwargs["capture_output"] is True and kwargs["timeout"] == 600
        return subprocess.CompletedProcess(
            command, returncode, json.dumps(safe_summary()), "private raw exception/token"
        )

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(
        RuntimeError, match="isolated installed controlled MCP smoke failed"
    ) as error:
        distribution._run_mcp_controlled_smoke(tmp_path / "python", tmp_path / "smoke.py", VERSION)
    assert "private" not in str(error.value)


def test_smoke_failure_does_not_reflect_core_prints_or_raw_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail() -> Any:
        print("private capability stdout")
        raise RuntimeError("private absolute path /business/knowledge.db SQL")

    monkeypatch.setattr(smoke, "companion", fail)
    assert smoke.main(["--expected-version", VERSION]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "installed controlled MCP smoke failed\n"


@pytest.fixture
def seed(tmp_path: Path) -> smoke.Seed:
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return smoke.prepare_seed(tmp_path)


def test_seed_actual_quality_pinned_fresh_private_b4(seed: smoke.Seed, tmp_path: Path) -> None:
    assert (
        seed.database
        == tmp_path
        / ".konwledge"
        / "mutation-demo"
        / seed.manifest.parent.name
        / "seed"
        / "knowledge.db"
    )
    report = json.loads((seed.database.parent / "report.json").read_text())
    assert report["status"] == "passed" and report["quality_cases"] == 4
    assert all(check["passed"] for check in report["checks"])
    assert report["dataset_hash"] == seed.dataset_hash
    snapshot = smoke.rows(seed)
    assert "mcp_approvals" not in snapshot
    assert len(snapshot["mutation_commands"]) == len(snapshot["auto_evaluation_jobs"]) == 0
    for path in seed.manifest.parent.rglob("*"):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
        assert path.stat().st_uid == os.getuid()
    before = seed.database.read_bytes()
    assert smoke.rows(seed) == snapshot and seed.database.read_bytes() == before


def test_seed_cannot_forge_passed_marker_on_quality_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from konwledge.quality import QualityService

    monkeypatch.setattr(
        QualityService, "run", lambda *_args, **_kwargs: SimpleNamespace(passed=False)
    )
    with pytest.raises(AssertionError, match="actual seed quality failed"):
        smoke.prepare_seed(tmp_path)
    assert not tuple(tmp_path.rglob("report.json"))


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE documents SET checksum='" + "a" * 64 + "'",
        "DROP TABLE auto_evaluation_jobs",
        "CREATE TABLE new_audit_table (value TEXT)",
    ],
    ids=["knowledge", "outbox", "unapproved-new-table"],
)
def test_snapshot_detects_grant_knowledge_outbox_and_new_tables(
    seed: smoke.Seed, mutation: str
) -> None:
    before = smoke.rows(seed)
    before_knowledge = smoke.knowledge_rows(seed)
    with sqlite3.connect(seed.database) as connection:
        connection.execute("CREATE TABLE mcp_approvals (value TEXT)")
        connection.execute("INSERT INTO mcp_approvals VALUES ('synthetic')")
    assert smoke.rows(seed) != before
    assert smoke.knowledge_rows(seed) == before_knowledge
    with sqlite3.connect(seed.database) as connection:
        connection.execute(mutation)
    assert smoke.rows(seed) != before
    assert smoke.knowledge_rows(seed) != before_knowledge


def test_real_pty_helper_and_atomic_quality_sequence(seed: smoke.Seed) -> None:
    """验证 smoke helper 自身真实 TTY/事务流程；不代替隔离 wheel/sdist 验收。"""
    from konwledge.mcp.controlled import open_controlled_runtime
    from konwledge.mcp.controlled_models import ApplyDocumentUpdateInput, PreviewDocumentUpdateInput

    gate = smoke.Gate(b5, seed, VERSION)
    commands: list[dict[str, Any]] = []
    for revision in range(1, 4):
        with open_controlled_runtime(
            seed.database, seed.manifest, smoke.ACTOR, demo_root=seed.root
        ) as runtime:
            source = runtime.service.get_mutation_session().sources[0]
            preview = runtime.service.preview_document_update(
                PreviewDocumentUpdateInput(
                    source_id=source.source_id,
                    document_id=source.document_id,
                    expected_checksum=source.checksum,
                    text=smoke.TEXTS[revision],
                )
            ).model_dump(mode="json")
        key = str(uuid4())
        if revision == 1:
            assert smoke.approve_pty(b5, seed, preview, key, correct=False) is None
        grant = smoke.approve_pty(b5, seed, preview, key)
        assert grant is not None
        request = {
            "preview_id": preview["preview_id"],
            "confirmation_token": preview["confirmation_token"],
            "idempotency_key": key,
            "approval_token": grant["approval_token"],
        }
        if revision == 1:
            smoke.atomic_denials(gate, request | {"_approval_id": grant["approval_id"]})
        with open_controlled_runtime(
            seed.database, seed.manifest, smoke.ACTOR, demo_root=seed.root
        ) as runtime:
            result = runtime.service.apply_document_update(
                ApplyDocumentUpdateInput.model_validate(request)
            )
            after = smoke.rows(seed)
            assert (
                runtime.service.apply_document_update(
                    ApplyDocumentUpdateInput.model_validate(request)
                )
                == result
            )
            assert smoke.rows(seed) == after
            commands.append(result.model_dump(mode="json"))
    assert [command["evaluation_status"] for command in commands] == ["passed", "failed", "passed"]
    assert smoke.verify_history(seed, commands) == {
        "commands": 3,
        "jobs": 3,
        "passed_jobs": 2,
        "failed_jobs": 1,
        "consumed_grants": 3,
    }
    assert gate.rejects == 2
