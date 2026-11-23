from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from scripts import workbench
from scripts import workbench_runtime as runtime


@pytest.mark.parametrize(
    "argv",
    [
        ["demo", "--mode", "controlled"],
        ["demo", "--mode", "controlled", "--prepare-only"],
        ["demo", "--actor", "editor"],
        ["demo", "--mode", "controlled", "--actor", "bad actor"],
        ["demo", "--web-port", "8015"],
        ["demo", "--web-port", "0"],
        ["demo", "--api-port", "65536"],
        ["demo", "--api-port", "http://localhost:8015"],
        ["demo", "--timeout", "nan"],
        ["accept", "--timeout", "inf"],
        ["accept", "--timeout", "0"],
        ["accept", "--timeout", "86401"],
        ["demo", "--database", "/tmp/existing.db"],
        ["demo", "--manifest", "/tmp/existing.json"],
        ["demo", "--dsn", "postgres://secret"],
        ["accept", "--output-root", "/tmp"],
        ["accept", "--script", "/tmp/evil.py"],
        ["demo", "--url", "https://example.invalid"],
        ["demo", "--web", "5175"],
        ["accept", "--actor", "editor"],
        ["demo", "--with-distribution"],
    ],
)
def test_invalid_before_any_side_effect(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden() -> Path:
        pytest.fail("参数拒绝前不能分配会话")

    monkeypatch.setattr(runtime, "create_session", forbidden)
    try:
        code = workbench.main(argv)
    except SystemExit as error:
        assert isinstance(error.code, int)
        code = error.code
    assert code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "invalid_arguments\n"


def test_list_dependency_free(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden() -> Any:
        pytest.fail("list 不能加载 reports 或创建目录")

    monkeypatch.setattr(runtime, "reports", forbidden)
    monkeypatch.setattr(runtime, "create_session", forbidden)
    assert workbench.main(["list"]) == 0
    output = capsys.readouterr().out
    assert "readonly" in output and "5175" in output and "8015" in output
    assert "_adapter" not in output


def test_real_script_list() -> None:
    result = subprocess.run(
        [sys.executable, str(runtime.ROOT / "scripts/workbench.py"), "list"],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert b"readonly" in result.stdout
    assert result.stderr == b""


def test_defaults_and_explicit_mutations() -> None:
    demo = workbench.parse_options(["demo"])
    assert demo is not None and demo.mode == "readonly" and demo.timeout == 900
    assert demo.components() == ["seed", "launcher"]
    prepared = workbench.parse_options(
        [
            "demo",
            "--mode",
            "controlled",
            "--actor",
            "editor",
            "--prepare-only",
            "--web-port",
            "5176",
            "--api-port",
            "8016",
        ]
    )
    assert prepared is not None and prepared.components() == ["prepare_controlled"]
    readonly = workbench.parse_options(["accept"])
    assert readonly is not None and readonly.components() == ["seed", "management", "evaluation"]
    full = workbench.parse_options(["accept", "--suite", "full", "--with-distribution"])
    assert full is not None
    assert full.components() == ["seed", "management", "evaluation", "mutations", "distribution"]


def test_main_only_safe_parent_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary_path = runtime.ROOT / ".konwledge/workbench/test/summary.json"

    def execute(options: runtime.Options) -> tuple[Path, dict[str, Any], int]:
        return summary_path, {"status": "prepared", "secret": options.actor}, 0

    monkeypatch.setattr(runtime, "execute", execute)
    assert (
        workbench.main(
            ["demo", "--mode", "controlled", "--actor", "private-actor", "--prepare-only"]
        )
        == 0
    )
    output = capsys.readouterr()
    assert "summary .konwledge/workbench/test/summary.json" in output.out
    assert "status prepared" in output.out
    assert "ready" not in output.out and "private-actor" not in output.out


def test_exception_not_echoed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def failure(options: runtime.Options) -> Any:
        raise ValueError("SENSITIVE_CREDENTIAL")

    monkeypatch.setattr(runtime, "execute", failure)
    assert workbench.main(["demo"]) == 1
    assert capsys.readouterr().err == "runtime_failed\n"


def test_hidden_adapter_not_in_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        workbench.main(["--help"])
    assert "_adapter" not in capsys.readouterr().out


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux subreaper/pidfd 验证")
def test_real_controlled_prepare_only_private_unique_and_no_overwrite() -> None:
    from scripts import prepare_mutation_demo as demo

    root = runtime.ROOT
    workbench_root = root / ".konwledge" / "workbench"
    demo_root = root / ".konwledge" / "mutation-demo"
    previous_sessions = {p.name for p in workbench_root.glob("*")}
    previous_scopes = {p.name for p in demo_root.glob("*")}
    argv = [sys.executable, str(root / "scripts/workbench.py"), "demo", "--mode", "controlled"]
    invalid = subprocess.run(
        [*argv, "--prepare-only"], capture_output=True, text=True, check=False, timeout=10
    )
    assert invalid.returncode == 2
    assert invalid.stdout == "" and invalid.stderr == "invalid_arguments\n"
    assert previous_sessions == {p.name for p in workbench_root.glob("*")}
    assert previous_scopes == {p.name for p in demo_root.glob("*")}
    env = dict(os.environ, KNOWLEDGE_MUTATION_KEY="PRIVATE_KEY", VITE_KEY="PRIVATE_KEY")
    sessions: list[str] = []
    scopes: list[str] = []
    unchanged: dict[Path, str] = {}
    for _ in range(2):
        result = subprocess.run(
            [*argv, "--actor", "PRIVATE_ACTOR", "--prepare-only", "--timeout", "120"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=150,
        )
        assert result.returncode == 0 and result.stderr == ""
        lines = result.stdout.splitlines()
        assert len(lines) == 2 and lines[0].startswith("summary ") and lines[1] == "status prepared"
        summary_path = root / lines[0].removeprefix("summary ")
        summary = runtime.reports().safe_read_json(summary_path, allowed_root=summary_path.parent)
        assert summary["status"] == "prepared" and summary["mode"] == "controlled"
        assert summary["requested_components"] == ["prepare_controlled"]
        assert len(summary["components"]) == 1  # 无 launcher、无 API/GUI 服务。
        item = summary["components"][0]
        assert item["status"] == "ready" and item["exit_code"] == 0
        assert item["cleanup_verified"] is True and item["timed_out"] is False
        assert item["error_code"] is None and item["report_paths"] == []
        assert item["job_statuses"] == [] and item["checks_passed"] == item["checks_failed"] == 0
        assert item["frontend_status"] is None and item["children_stopped"] is None
        session = summary_path.parent
        assert runtime.canonical_uuid(session.name) not in previous_sessions | set(sessions)
        sessions.append(session.name)
        assert set(summary["artifacts"]) == {"database", "manifest"}
        manifest = runtime.checked_reference(
            summary["artifacts"]["manifest"], session=session, component="prepare_controlled"
        )
        database = runtime.checked_reference(
            summary["artifacts"]["database"], session=session, component="prepare_controlled"
        )
        assert manifest.parent.parent == demo_root
        assert runtime.canonical_uuid(manifest.parent.name) not in previous_scopes | set(scopes)
        scopes.append(manifest.parent.name)
        assert demo.validate_demo(manifest, database) == manifest
        receipt_path = next(session.glob("prepare_controlled/*/receipt.json"))
        invocation = runtime.canonical_uuid(receipt_path.parent.name)
        assert invocation not in sessions + scopes
        saved = runtime.reports().safe_read_json(receipt_path, allowed_root=session)
        assert saved["status"] == "completed" and saved["report_paths"] == []
        assert saved["artifacts"] == summary["artifacts"]
        safe_output = (
            result.stdout + result.stderr + summary_path.read_text() + receipt_path.read_text()
        )
        for secret in ("PRIVATE_ACTOR", "PRIVATE_KEY", "source_ids", "allowed_source_ids"):
            assert secret not in safe_output
        original = next(database.parent.glob("original/**/*.md"))
        assert original.read_text().strip() not in safe_output
        for artifact, digest in unchanged.items():
            assert hashlib.sha256(artifact.read_bytes()).hexdigest() == digest
        for boundary in (session, manifest.parent):
            assert boundary.stat().st_mode & 0o777 == 0o700
            for artifact in boundary.rglob("*"):
                assert not artifact.is_symlink()
                if artifact.is_dir():
                    assert artifact.stat().st_mode & 0o777 == 0o700
                else:
                    assert artifact.stat().st_mode & 0o777 == 0o600
                    assert artifact.stat().st_nlink == 1
                    unchanged[artifact] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert previous_sessions <= {p.name for p in workbench_root.glob("*")}
    assert previous_scopes <= {p.name for p in demo_root.glob("*")}
