from __future__ import annotations

import importlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from scripts import workbench_runtime as runtime


@pytest.fixture
def session_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(runtime, "ROOT", root)
    shared = pytest.importorskip(
        "scripts.workbench_reports", reason="等待共享 reports 实现，不创建替代模块"
    )
    monkeypatch.setattr(shared, "ROOT", root)
    return root


@pytest.fixture
def session(session_root: Path) -> Path:
    return runtime.create_session()


@pytest.fixture
def light_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # 只用于 mock 投影/adapter 的运行时判定，不替代共享模块实现。
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(runtime, "ROOT", root)
    session = root / ".konwledge" / "workbench" / str(uuid4())
    session.mkdir(parents=True, mode=0o700)
    return session


def receipt(session: Path, component: str, invocation: str) -> dict[str, Any]:
    return {
        "session_id": session.name,
        "component": component,
        "invocation_id": invocation,
        "status": "completed",
        "report_paths": [],
        "artifacts": {},
        "error_code": None,
    }


def test_session_private_unique_and_no_overwrite(session: Path) -> None:
    other = runtime.create_session()
    assert session != other and session.stat().st_mode & 0o777 == 0o700
    path = session / "summary.json"
    shared = runtime.reports()
    shared.write_json_exclusive(path, {"status": "passed"}, session=session)
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(shared.WorkbenchReportError):
        shared.write_json_exclusive(path, {"status": "failed"}, session=session)
    assert json.loads(path.read_text())["status"] == "passed"


def test_no_symlink_roots(session_root: Path, tmp_path: Path) -> None:
    (session_root / ".konwledge").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(runtime.RuntimeErrorCode):
        runtime.create_session()


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", str(uuid4())),
        ("component", "management"),
        ("invocation_id", str(uuid4())),
        ("status", "passed"),
        ("error_code", "SENSITIVE_SECRET"),
        ("artifacts", {"key": "SENSITIVE_SECRET"}),
        ("report_paths", ["/tmp/foreign.json"]),
        ("unexpected", "SENSITIVE_SECRET"),
    ],
)
def test_receipt_binding_and_allowlist(
    light_session: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    session = light_session
    invocation = str(uuid4())
    path = session / "seed" / invocation / "receipt.json"
    path.parent.mkdir(parents=True, mode=0o700)
    data = receipt(session, "seed", invocation)
    data[field] = value
    path.write_text(json.dumps(data))
    shared = MagicMock()
    shared.safe_read_json.return_value = data
    monkeypatch.setattr(runtime, "reports", lambda: shared)
    with pytest.raises(runtime.RuntimeErrorCode, match="receipt_invalid"):
        runtime.read_receipt(session, "seed", invocation, path)


def test_receipt_missing_and_foreign_path(light_session: Path) -> None:
    session = light_session
    invocation = str(uuid4())
    path = session / "seed" / invocation / "receipt.json"
    with pytest.raises(runtime.RuntimeErrorCode, match="receipt_missing"):
        runtime.read_receipt(session, "seed", invocation, path)
    with pytest.raises(runtime.RuntimeErrorCode, match="receipt_invalid"):
        runtime.read_receipt(session, "seed", str(uuid4()), path)


def test_environment_allowlist_without_global_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_API_KEY", "sensitive-token")
    before = dict(os.environ)
    result = runtime.safe_environment(
        {
            "PATH": "/usr/bin",
            "HOME": "/tmp",
            "LC_ALL": "C",
            "KNOWLEDGE_API_KEY": "secret",
            "VITE_KEY": "secret",
            "NODE_OPTIONS": "--inspect",
            "PYTHONPATH": "/evil",
            "OPENAI_API_KEY": "secret",
            "DATABASE_URL": "postgres://secret",
            "HTTP_PROXY": "http://secret",
            "AWS_SECRET_ACCESS_KEY": "secret",
        }
    )
    assert result["PATH"] == "/usr/bin" and result["LC_ALL"] == "C"
    assert set(result) == {"PATH", "HOME", "LC_ALL", "NO_COLOR", "TERM", "PYTHONDONTWRITEBYTECODE"}
    assert dict(os.environ) == before


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux ownership proof")
def test_real_process_normal_secret_output_and_env(
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PRIVATE_TEST_KEY", "SENSITIVE_SECRET")
    code = (
        "import os,sys; print('SENSITIVE_SECRET'); "
        "print('SENSITIVE_SECRET', file=sys.stderr); "
        "assert 'PRIVATE_TEST_KEY' not in os.environ; "
        "assert os.getsid(0)==os.getpid()"
    )
    result = runtime.run_process([sys.executable, "-c", code], timeout=3, grace=0.15)
    assert result == runtime.ProcessResult(0, False, False, True)
    output = capfd.readouterr()
    assert output.out == output.err == ""
    assert "SENSITIVE_SECRET" not in repr(result)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux ownership proof")
def test_real_timeout_allows_finally(tmp_path: Path) -> None:
    cleaned = tmp_path / "cleaned"
    code = (
        "import time\n"
        "try:\n    time.sleep(20)\n"
        f"finally:\n    open({str(cleaned)!r}, 'x').close()\n"
    )
    result = runtime.run_process([sys.executable, "-c", code], timeout=0.25, grace=0.25)
    assert result.timed_out and result.cleanup_verified and not result.forced
    assert cleaned.exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux ownership proof")
def test_real_signal_safe_nonzero(tmp_path: Path) -> None:
    code = (
        "import os,signal,time\n"
        "time.sleep(0.1)\n"
        "os.kill(os.getppid(),signal.SIGINT)\n"
        "time.sleep(20)\n"
    )
    result = runtime.run_process([sys.executable, "-c", code], timeout=3, grace=0.25)
    assert result.interrupted and result.cleanup_verified and result.exit_code != 0
    assert not result.timed_out


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux ownership proof")
def test_setsid_orphan_cleanup_and_foreign_survives(tmp_path: Path) -> None:
    pid_file = tmp_path / "owned_pid"
    code = (
        "import os,time\n"
        "pid=os.fork()\n"
        "if pid==0:\n"
        "    os.setsid()\n"
        f"    open({str(pid_file)!r},'w').write(str(os.getpid()))\n"
        "    time.sleep(20)\n"
        "else:\n"
        "    time.sleep(0.15)\n"
    )
    foreign = subprocess.Popen(
        [sys.executable, "-c", "import time;time.sleep(20)"], start_new_session=True
    )
    try:
        result = runtime.run_process([sys.executable, "-c", code], timeout=2, grace=0.2)
        assert result.cleanup_verified
        assert foreign.poll() is None
        pid = int(pid_file.read_text())
        assert pid not in runtime.process_table()
    finally:
        foreign.terminate()
        foreign.wait(timeout=3)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux ownership proof")
def test_force_cleanup_never_green() -> None:
    code = (
        "import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(20)"
    )
    result = runtime.run_process([sys.executable, "-c", code], timeout=0.2, grace=0.1)
    assert result.forced and result.cleanup_verified and result.timed_out


@pytest.mark.parametrize(
    "result,projection,error",
    [
        (runtime.ProcessResult(1, False, False, True), {"status": "passed"}, "driver_failed"),
        (runtime.ProcessResult(0, True, False, True), {"status": "passed"}, "timeout"),
        (runtime.ProcessResult(0, False, False, False), {"status": "passed"}, "cleanup_unknown"),
        (
            runtime.ProcessResult(0, False, False, True, True),
            {"status": "passed"},
            "cleanup_forced",
        ),
        (
            runtime.ProcessResult(0, False, False, True),
            {"status": "passed", "checks_failed": 1},
            "checks_failed",
        ),
        (
            runtime.ProcessResult(0, False, False, True),
            {"status": "passed", "children_stopped": False},
            "checks_failed",
        ),
        (runtime.ProcessResult(0, False, False, True), {"status": "failed"}, "checks_failed"),
    ],
)
def test_false_pass_rejected(
    light_session: Path,
    monkeypatch: pytest.MonkeyPatch,
    result: runtime.ProcessResult,
    projection: dict[str, Any],
    error: str,
) -> None:
    session = light_session
    shared = MagicMock()
    shared.project_report.return_value = projection
    monkeypatch.setattr(runtime, "reports", lambda: shared)
    monkeypatch.setattr(runtime, "checked_reference", lambda *a, **kw: session / "report.json")
    data = {"status": "completed", "report_paths": ["report.json"], "error_code": None}
    merged = runtime.merge_result("seed", result, data, session=session)
    assert merged["status"] != "passed" and merged["error_code"] == error
    assert merged["exit_code"] == result.exit_code
    assert merged["cleanup_verified"] == result.cleanup_verified


def test_expected_quality_failure_is_not_driver_failure(
    light_session: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = light_session
    shared = MagicMock()
    shared.project_report.return_value = {
        "status": "passed",
        "checks_passed": 3,
        "checks_failed": 0,
        "job_statuses": ["passed", "failed", "passed"],
        "mean_recall": [1.0, 0.0, 1.0],
    }
    monkeypatch.setattr(runtime, "reports", lambda: shared)
    monkeypatch.setattr(runtime, "checked_reference", lambda *a, **kw: session / "report.json")
    result = runtime.ProcessResult(0, False, False, True)
    data = {"status": "completed", "report_paths": ["report.json"], "error_code": None}
    merged = runtime.merge_result("seed", result, data, session=session)
    assert merged["status"] == "passed" and merged["job_statuses"] == ["passed", "failed", "passed"]


def test_demo_ctrl_c_stopped_not_passed(light_session: Path) -> None:
    session = light_session
    data: dict[str, Any] = {"status": "stopped", "report_paths": [], "error_code": None}
    result = runtime.ProcessResult(130, False, True, True)
    assert runtime.merge_result("launcher", result, data, session=session)["status"] == "stopped"
    assert (
        runtime.merge_result(
            "launcher", runtime.ProcessResult(130, True, True, True), data, session=session
        )["status"]
        == "failed"
    )


def test_failfast_and_safe_summary(
    session_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def run(
        session: Path, component: str, options: runtime.Options, artifacts: Any
    ) -> tuple[dict[str, Any], dict[str, str]]:
        seen.append(component)
        item = runtime.empty_component(component, status="failed")
        item.update(exit_code=1, cleanup_verified=True, error_code="driver_failed")
        return item, {}

    monkeypatch.setattr(runtime, "run_component", run)
    path, summary, code = runtime.execute(runtime.Options("accept", suite="full"))
    assert code != 0 and summary["status"] == "failed" and seen == ["seed"]
    assert [item["status"] for item in summary["components"]] == ["failed"] + ["blocked"] * 3
    assert summary["artifacts"] == {}
    assert path.stat().st_mode & 0o777 == 0o600


def test_prepared_does_not_launch_or_leak_actor(
    session_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def run(
        session: Path, component: str, options: runtime.Options, artifacts: Any
    ) -> tuple[dict[str, Any], dict[str, str]]:
        seen.append(component)
        item = runtime.empty_component(component, status="ready")
        item.update(exit_code=0, cleanup_verified=True, error_code=None)
        return item, {}

    monkeypatch.setattr(runtime, "run_component", run)
    path, summary, code = runtime.execute(
        runtime.Options(
            "demo",
            mode="controlled",
            actor="SENSITIVE_ACTOR",
            prepare_only=True,
        )
    )
    assert code == 0 and summary["status"] == "prepared" and seen == ["prepare_controlled"]
    assert "SENSITIVE_ACTOR" not in path.read_text()


def test_adapter_calls_public_api_discards_payload_and_prints(
    session: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    invocation, path = runtime.allocate_invocation(session, "seed")
    driver = MagicMock()

    def seed(output: Path) -> Path:
        output.mkdir(mode=0o700)
        report = output / "report.json"
        report.write_text('{"status":"passed","sensitive":"SENSITIVE_SECRET"}')
        report.chmod(0o600)
        (output / "knowledge.db").write_bytes(b"SQLite format 3\0")
        print("SENSITIVE_SECRET")
        print("SENSITIVE_SECRET", file=sys.stderr)
        return report

    driver.run_acceptance.side_effect = seed
    original = importlib.import_module
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: driver if name.endswith("real_knowledge_acceptance") else original(name),
    )
    code = runtime.adapter(
        session.name,
        "seed",
        invocation,
        {"artifacts": {}, "actor": None, "web_port": 5175, "api_port": 8015},
    )
    assert code == 0
    saved = runtime.read_receipt(session, "seed", invocation, path)
    assert saved["status"] == "completed" and "SENSITIVE_SECRET" not in path.read_text()
    assert capfd.readouterr().out == ""
    with pytest.raises(runtime.RuntimeErrorCode):
        runtime.adapter(
            session.name,
            "seed",
            invocation,
            {"artifacts": {}, "actor": None, "web_port": 5175, "api_port": 8015},
        )


def test_ports_of_foreign_process_never_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    owned = MagicMock()
    owned.refresh.return_value = {}
    assert not runtime.loopback_ready(owned, 5175, 8015)


def test_missing_receipt_prevents_pass(
    session: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime, "run_process", lambda *a, **kw: runtime.ProcessResult(0, False, False, True)
    )
    item, artifacts = runtime.run_component(session, "seed", runtime.Options("accept"), {})
    assert item["status"] == "failed" and item["error_code"] == "receipt_missing"
    assert not artifacts


def test_projection_cannot_override_execution(
    light_session: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = light_session
    shared = MagicMock()
    shared.project_report.return_value = {
        "status": "passed",
        "exit_code": 0,
        "timed_out": False,
        "cleanup_verified": True,
    }
    monkeypatch.setattr(runtime, "reports", lambda: shared)
    monkeypatch.setattr(runtime, "checked_reference", lambda *a, **kw: session / "report.json")
    result = runtime.ProcessResult(2, True, False, False)
    data = {"status": "completed", "report_paths": ["report.json"], "error_code": None}
    item = runtime.merge_result("seed", result, data, session=session)
    assert item["exit_code"] == 2 and item["timed_out"] and not item["cleanup_verified"]
    assert item["status"] == "unknown"


def test_signal_handlers_restore_between_stages() -> None:
    before = signal.getsignal(signal.SIGTERM)
    with runtime.session_signals() as interrupted:
        os.kill(os.getpid(), signal.SIGTERM)
        assert interrupted()
    assert signal.getsignal(signal.SIGTERM) == before


def test_unknown_adoptee_is_not_owned_with_foreign_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = os.getpid()
    identity = runtime.ProcessIdentity
    baseline = {
        parent: identity(parent, 1, parent, 1, "R"),
        90001: identity(90001, parent, 90001, 2, "S"),
    }
    current = {**baseline, 90002: identity(90002, parent, 90002, 3, "S")}
    monkeypatch.setattr(runtime, "process_table", lambda: current)
    owned = runtime.OwnedProcesses(baseline, 90002)
    # 无祖先证据且有 foreign 基线：不能向未知收养者发送信号。
    current[90003] = identity(90003, parent, 90003, 4, "S")
    found = owned.refresh()
    assert 90002 in found and 90003 not in found and not owned.verified
    assert 90001 not in found


def test_unsupported_cleanup_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "unsupported")
    with pytest.raises(runtime.RuntimeErrorCode, match="cleanup_unknown"):
        runtime.run_process([sys.executable, "-c", "pass"], timeout=1)


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf"), 86401.0, True])
def test_runtime_invalid_timeout_before_spawn(timeout: float) -> None:
    with pytest.raises(runtime.RuntimeErrorCode, match="invalid_arguments"):
        runtime.run_process([sys.executable, "-c", "pass"], timeout=timeout)


@pytest.mark.parametrize(
    "component",
    [
        "management",
        "evaluation",
        "mutations",
        "prepare_controlled",
        "distribution",
        "launcher",
    ],
)
def test_adapter_fixed_public_interfaces(
    light_session: Path,
    monkeypatch: pytest.MonkeyPatch,
    component: str,
    capfd: pytest.CaptureFixture[str],
) -> None:
    session = light_session
    root = session.parents[2]
    invocation = str(uuid4())
    directory = session / component / invocation
    directory.mkdir(parents=True, mode=0o700)
    output = directory / "driver"
    database = session / "seed" / "private" / "driver" / "knowledge.db"
    shared = MagicMock()
    shared.validate_session.return_value = session
    shared.artifact_reference.side_effect = lambda path, **kwargs: path.relative_to(root).as_posix()
    monkeypatch.setattr(runtime, "reports", lambda: shared)
    driver = MagicMock()
    scope = str(uuid4())
    controlled = root / ".konwledge" / "mutation-demo" / scope
    prepared_db = controlled / "seed" / "knowledge.db"
    prepared_manifest = controlled / "mutation-manifest.json"
    driver.Runner.return_value.run.return_value = 0
    driver.run_acceptance_flow.return_value = output / "run" / "report.json"
    driver.Driver.return_value.run.return_value = (
        {"SENSITIVE_SECRET": "raw payload must not be copied"},
        controlled / "b4-acceptance-report.json",
    )
    driver.validate_demo.return_value = prepared_manifest

    def prepare() -> dict[str, Any]:
        prepared_db.parent.mkdir(parents=True, mode=0o700)
        for path in (prepared_db, prepared_manifest, prepared_db.parent / "report.json"):
            path.touch(mode=0o600)
        return {
            "status": "ready",
            "scope_id": scope,
            "database": prepared_db.relative_to(root).as_posix(),
            "manifest": prepared_manifest.relative_to(root).as_posix(),
            "source_ids": ["SENSITIVE_SECRET"],
        }

    driver.prepare.side_effect = prepare
    driver.verify.return_value = (
        output / "build" / "wheel.whl",
        output / "build" / "sdist.tar.gz",
        (output / "wheel-smoke-summary.json", output / "sdist-smoke-summary.json"),
    )
    driver.run.return_value = 130 if component == "launcher" else 0
    original = importlib.import_module
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: driver if name.startswith("scripts.") else original(name),
    )
    request = {
        "artifacts": {"database": database.relative_to(root).as_posix()},
        "actor": "private-editor" if component == "prepare_controlled" else None,
        "web_port": 5175,
        "api_port": 8015,
    }
    exit_code = runtime.adapter(session.name, component, invocation, request)
    assert exit_code == (130 if component == "launcher" else 0)
    saved = shared.write_json_exclusive.call_args.args[1]
    assert set(saved) == runtime.RECEIPT_KEYS
    assert saved["invocation_id"] == invocation and saved["component"] == component
    assert "SENSITIVE_SECRET" not in json.dumps(saved) and "private-editor" not in json.dumps(saved)
    if component == "management":
        driver.Runner.assert_called_once_with(database, output / "report.json")
    elif component == "evaluation":
        driver.run_acceptance_flow.assert_called_once_with(output)
    elif component == "mutations":
        driver.Driver.assert_called_once_with(frontend=True)
    elif component == "prepare_controlled":
        driver.prepare.assert_called_once_with()
        driver.validate_demo.assert_called_once_with(prepared_manifest, prepared_db)
        assert saved["report_paths"] == []
        assert saved["artifacts"]["manifest"] == prepared_manifest.relative_to(root).as_posix()
    elif component == "distribution":
        driver.verify.assert_called_once_with(output, sys.executable)
        assert len(saved["report_paths"]) == 2
    else:
        driver.run.assert_called_once_with(
            database, 5175, 8015, mutation_manifest=None, mutation_actor=None
        )
        assert saved["status"] == "stopped"
    assert capfd.readouterr().out == ""


@pytest.mark.parametrize("foreign", [False, True])
def test_receipt_paths_bound_to_invocation(
    light_session: Path,
    monkeypatch: pytest.MonkeyPatch,
    foreign: bool,
) -> None:
    session = light_session
    root = session.parents[2]
    invocation = str(uuid4())
    path = session / "seed" / invocation / "receipt.json"
    path.parent.mkdir(parents=True, mode=0o700)
    path.touch(mode=0o600)
    artifact_dir = session / "seed" / (str(uuid4()) if foreign else invocation) / "driver"
    data = receipt(session, "seed", invocation)
    data["report_paths"] = [(artifact_dir / "report.json").relative_to(root).as_posix()]
    data["artifacts"] = {"database": (artifact_dir / "knowledge.db").relative_to(root).as_posix()}
    shared = MagicMock()
    shared.safe_read_json.return_value = data
    shared.artifact_reference.side_effect = lambda returned, **kw: returned.relative_to(
        root
    ).as_posix()
    monkeypatch.setattr(runtime, "reports", lambda: shared)
    if foreign:
        with pytest.raises(runtime.RuntimeErrorCode, match="receipt_invalid"):
            runtime.read_receipt(session, "seed", invocation, path)
    else:
        assert runtime.read_receipt(session, "seed", invocation, path)["status"] == "completed"


def fresh_controlled_demo(root: Path) -> dict[str, Any]:
    """测试只新建微型 SQLite；原 validate_demo 和 reports 边界均保持真实。"""
    from scripts import prepare_mutation_demo as demo

    scope, source, dataset = uuid4(), uuid4(), uuid4()
    base = root / ".konwledge" / "mutation-demo"
    base.mkdir(mode=0o700, exist_ok=True)
    parent = base / str(scope)
    parent.mkdir(mode=0o700, exist_ok=False)
    seed = parent / "seed"
    seed.mkdir(mode=0o700)
    database = seed / "knowledge.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            "CREATE TABLE sources (id TEXT, kind TEXT);"
            "CREATE TABLE documents (source_id TEXT, content_type TEXT);"
            "CREATE TABLE auto_evaluation_config (id INTEGER, enabled INTEGER, "
            "dataset_id TEXT, dataset_version INTEGER, dataset_hash TEXT);"
            "CREATE TABLE evaluation_sets (id TEXT, version INTEGER, content_hash TEXT);"
            "CREATE TABLE mutation_previews (id TEXT);CREATE TABLE mutation_commands (id TEXT);"
        )
        connection.execute("INSERT INTO sources VALUES (?, 'file')", (source.hex,))
        connection.execute("INSERT INTO documents VALUES (?, 'markdown')", (source.hex,))
        connection.execute(
            "INSERT INTO auto_evaluation_config VALUES (1, 1, ?, 1, ?)", (dataset.hex, "a" * 64)
        )
        connection.execute("INSERT INTO evaluation_sets VALUES (?, 1, ?)", (dataset.hex, "a" * 64))
    database.chmod(0o600)
    report = seed / "report.json"
    report.write_text(
        json.dumps(
            {
                "status": "passed",
                "artifacts": {"database": "knowledge.db"},
                "text": "PRIVATE_FULLTEXT",
            }
        )
    )
    report.chmod(0o600)
    manifest = parent / "mutation-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": demo.KIND,
                "scope_id": str(scope),
                "database": "seed/knowledge.db",
                "allowed_source_ids": [str(source)],
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
    )
    manifest.chmod(0o600)
    return {
        "status": "ready",
        "scope_id": str(scope),
        "database": database.relative_to(root).as_posix(),
        "manifest": manifest.relative_to(root).as_posix(),
        "source_ids": [str(source)],
        "key": "PRIVATE_KEY",
        "text": "PRIVATE_FULLTEXT",
    }


@pytest.fixture
def controlled_driver(session_root: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    from scripts import prepare_mutation_demo as demo

    monkeypatch.setattr(demo, "ROOT", session_root)

    def prepare() -> dict[str, Any]:
        print("PRIVATE_KEY PRIVATE_FULLTEXT PRIVATE_ACTOR")
        print("PRIVATE_KEY", file=sys.stderr)
        return fresh_controlled_demo(session_root)

    monkeypatch.setattr(demo, "prepare", MagicMock(side_effect=prepare))
    monkeypatch.setattr(demo, "validate_demo", MagicMock(wraps=demo.validate_demo))
    return demo


def test_controlled_receipt_empty_projection_and_strict_validation(
    session: Path, controlled_driver: ModuleType, capfd: pytest.CaptureFixture[str]
) -> None:
    invocation, path = runtime.allocate_invocation(session, "prepare_controlled")
    started = path.parent.stat().st_mtime_ns
    assert (
        runtime.adapter(
            session.name,
            "prepare_controlled",
            invocation,
            {"artifacts": {}, "actor": "PRIVATE_ACTOR", "web_port": 5175, "api_port": 8015},
        )
        == 0
    )
    saved = runtime.read_receipt(
        session, "prepare_controlled", invocation, path, started_ns=started
    )
    controlled_driver.validate_demo.assert_called()
    assert saved["status"] == "completed" and saved["report_paths"] == []
    assert set(saved["artifacts"]) == {"database", "manifest"}
    item = runtime.merge_result(
        "prepare_controlled", runtime.ProcessResult(0, False, False, True), saved, session=session
    )
    assert item["status"] == "ready" and item["report_paths"] == []
    assert item["checks_passed"] == 0 and item["job_statuses"] == []
    for secret in ("PRIVATE_ACTOR", "PRIVATE_KEY", "PRIVATE_FULLTEXT"):
        assert secret not in path.read_text() + json.dumps(item)
    output = capfd.readouterr()
    assert output.out == output.err == ""
    # 空 paths 的投影 ready 不能洗白未核实的进程清理。
    unknown = runtime.merge_result(
        "prepare_controlled", runtime.ProcessResult(0, False, False, False), saved, session=session
    )
    assert unknown["status"] == "unknown" and unknown["error_code"] == "cleanup_unknown"
    saved["report_paths"] = [
        (runtime.ROOT / saved["artifacts"]["database"]).parent.relative_to(runtime.ROOT).as_posix()
        + "/report.json"
    ]
    path.write_text(json.dumps(saved))
    with pytest.raises(runtime.RuntimeErrorCode, match="receipt_invalid"):
        runtime.read_receipt(session, "prepare_controlled", invocation, path, started_ns=started)


def test_hidden_controlled_requires_actor(session: Path, controlled_driver: ModuleType) -> None:
    invocation, path = runtime.allocate_invocation(session, "prepare_controlled")
    assert (
        runtime.adapter(
            session.name,
            "prepare_controlled",
            invocation,
            {"artifacts": {}, "actor": None, "web_port": 5175, "api_port": 8015},
        )
        == 1
    )
    controlled_driver.prepare.assert_not_called()
    saved = runtime.read_receipt(session, "prepare_controlled", invocation, path)
    assert saved["status"] == "failed" and saved["error_code"] == "invalid_arguments"
    assert saved["artifacts"] == {} and saved["report_paths"] == []


@pytest.mark.parametrize(
    "fault",
    [
        "not_ready",
        "bad_scope",
        "scope_mismatch",
        "absolute",
        "traversal",
        "session_path",
        "mixed_scopes",
        "stale_database",
        "stale_manifest",
        "stale_report",
        "future",
        "symlink",
        "hardlink",
        "public_mode",
        "bad_manifest",
        "bad_database",
        "validation_failed",
        "validation_wrong_return",
        "old_scope",
    ],
)
def test_controlled_prepare_failure_never_ready(
    session_root: Path,
    session: Path,
    controlled_driver: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    fault: str,
) -> None:
    old = fresh_controlled_demo(session_root) if fault == "old_scope" else None

    def prepare() -> dict[str, Any]:
        result = old or fresh_controlled_demo(session_root)
        database = session_root / result["database"]
        manifest = session_root / result["manifest"]
        if fault == "not_ready":
            result["status"] = "failed"
        elif fault == "bad_scope":
            result["scope_id"] = "PRIVATE_KEY"
        elif fault == "scope_mismatch":
            result["scope_id"] = str(uuid4())
        elif fault == "absolute":
            result["database"] = str(database)
        elif fault == "traversal":
            result["database"] = result["database"].replace("/seed/", "/seed/../seed/")
        elif fault == "session_path":
            target = session / "knowledge.db"
            target.write_bytes(b"new isolated invalid database")
            result["database"] = target.relative_to(session_root).as_posix()
        elif fault == "mixed_scopes":
            result["manifest"] = fresh_controlled_demo(session_root)["manifest"]
        elif fault.startswith("stale_"):
            target = {
                "stale_database": database,
                "stale_manifest": manifest,
                "stale_report": database.parent / "report.json",
            }[fault]
            os.utime(target, ns=(1, 1))
        elif fault == "future":
            future = time.time_ns() + 60_000_000_000
            os.utime(manifest, ns=(future, future))
        elif fault == "symlink":
            target = database.with_name("saved.db")
            database.rename(target)
            database.symlink_to(target)
        elif fault == "hardlink":
            os.link(database, database.with_name("linked.db"))
        elif fault == "public_mode":
            manifest.chmod(0o644)
        elif fault == "bad_manifest":
            data = json.loads(manifest.read_text())
            data["extra"] = "PRIVATE_FULLTEXT"
            manifest.write_text(json.dumps(data))
        elif fault == "bad_database":
            with sqlite3.connect(database) as connection:
                connection.execute("UPDATE auto_evaluation_config SET enabled=0")
        elif fault == "validation_failed":
            monkeypatch.setattr(
                controlled_driver,
                "validate_demo",
                MagicMock(side_effect=ValueError("PRIVATE_KEY PRIVATE_FULLTEXT")),
            )
        elif fault == "validation_wrong_return":
            monkeypatch.setattr(
                controlled_driver, "validate_demo", MagicMock(return_value=database)
            )
        elif fault == "old_scope":
            # 旧 UUID 即使全部 touch 成新鲜时间，也不属于本次调用。
            for target in (
                manifest.parent,
                database.parent,
                database,
                manifest,
                database.parent / "report.json",
            ):
                os.utime(target, None)
        return result

    monkeypatch.setattr(controlled_driver, "prepare", prepare)

    def run(argv: Any, *, timeout: float, request: bytes, on_tick: Any) -> runtime.ProcessResult:
        # 仅 mock 进程；adapter/receipt/strict validator/投影/summary 使用真实实现。
        code = runtime.adapter(argv[4], "prepare_controlled", argv[-1], json.loads(request))
        return runtime.ProcessResult(code, False, False, True)

    monkeypatch.setattr(runtime, "run_process", run)
    path, summary, code = runtime.execute(
        runtime.Options("demo", mode="controlled", actor="PRIVATE_ACTOR", prepare_only=True)
    )
    assert code == 1 and summary["status"] == "failed"
    saved = json.loads(next(path.parent.glob("prepare_controlled/*/receipt.json")).read_text())
    assert saved["status"] == "failed" and saved["artifacts"] == {}
    assert summary["artifacts"] == {}
    assert summary["components"][0]["status"] == "failed"
    assert "ready" not in path.read_text()
    for secret in ("PRIVATE_ACTOR", "PRIVATE_KEY", "PRIVATE_FULLTEXT"):
        assert secret not in path.read_text()
    output = capfd.readouterr()
    assert output.out == output.err == ""


@pytest.mark.parametrize(
    "tamper", ["missing_freshness", "old_scope", "stale", "invalid_dto", "failed_artifacts"]
)
def test_parent_revalidates_controlled_completed_receipt(
    session: Path, controlled_driver: ModuleType, tamper: str
) -> None:
    invocation, path = runtime.allocate_invocation(session, "prepare_controlled")
    started = path.parent.stat().st_mtime_ns
    result = fresh_controlled_demo(runtime.ROOT)
    data = receipt(session, "prepare_controlled", invocation)
    data["artifacts"] = {key: result[key] for key in ("database", "manifest")}
    if tamper == "failed_artifacts":
        data["status"] = "failed"
    runtime.reports().write_json_exclusive(path, data, session=session)
    scopes = frozenset({result["scope_id"]}) if tamper == "old_scope" else frozenset()
    if tamper == "stale":
        os.utime(runtime.ROOT / result["database"], ns=(1, 1))
    elif tamper == "invalid_dto":
        manifest = runtime.ROOT / result["manifest"]
        payload = json.loads(manifest.read_text())
        payload["scope_id"] = str(uuid4())
        manifest.write_text(json.dumps(payload))
    with pytest.raises(runtime.RuntimeErrorCode, match="receipt_invalid"):
        runtime.read_receipt(
            session,
            "prepare_controlled",
            invocation,
            path,
            started_ns=None if tamper == "missing_freshness" else started,
            previous_scopes=scopes,
        )
