from __future__ import annotations

import argparse
import json
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from scripts import live_workbench as workbench


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "knowledge.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE existing (id INTEGER)")
    connection.close()
    return path


def free_ports() -> tuple[int, int]:
    with socket.socket() as first, socket.socket() as second:
        first.bind(("127.0.0.1", 0))
        second.bind(("127.0.0.1", 0))
        return first.getsockname()[1], second.getsockname()[1]


@pytest.mark.parametrize("value", ["0", "65536", "-1", "abc", "http://evil:3"])
def test_invalid_cli_port(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        workbench.port_number(value)


def test_preflight_existing_database_no_creation(database: Path, tmp_path: Path) -> None:
    before = database.read_bytes()
    assert workbench.preflight(database, *free_ports()) == database.resolve()
    assert database.read_bytes() == before
    missing = tmp_path / "missing" / "production.db"
    with pytest.raises(workbench.WorkbenchError):
        workbench.preflight(missing, *free_ports())
    assert not missing.parent.exists()
    invalid = tmp_path / "invalid.db"
    invalid.write_text("not sqlite")
    with pytest.raises(workbench.WorkbenchError):
        workbench.preflight(invalid, *free_ports())
    with pytest.raises(workbench.WorkbenchError):
        workbench.preflight(tmp_path, *free_ports())


@pytest.mark.parametrize("ports", [(0, 2), (2, 65536), (2, 2), (True, 2)])
def test_preflight_invalid_ports(database: Path, ports: tuple[int, int]) -> None:
    with pytest.raises(workbench.WorkbenchError):
        workbench.preflight(database, *ports)


def test_preflight_occupied_port(database: Path) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        with pytest.raises(workbench.WorkbenchError):
            workbench.preflight(database, sock.getsockname()[1], free_ports()[1])


def test_child_env_secret_only_runtime_and_parent_unchanged() -> None:
    secret = "runtime-test-value"
    parent = {
        "PATH": "/usr/bin",
        "HOME": "/home/user",
        "LANG": "C.UTF-8",
        "LC_ALL": "C",
        "KNOWLEDGE_API_KEY": "old-secret",
        "KNOWLEDGE_MANAGEMENT_ORIGIN": "http://evil:123",
        "VITE_KNOWLEDGE_API_KEY": "old-secret",
        "VITE_OTHER": secret,
        "NODE_OPTIONS": "--require attacker",
        "OTHER_TOKEN": "other-secret",
        "TERM": secret,
    }
    before = parent.copy()
    api, web = workbench.child_environments(parent, 8015, secret)
    assert parent == before
    assert api["KNOWLEDGE_API_KEY"] == web["KNOWLEDGE_API_KEY"] == secret
    assert web["KNOWLEDGE_MANAGEMENT_ORIGIN"] == "http://127.0.0.1:8015"
    assert "KNOWLEDGE_MANAGEMENT_ORIGIN" not in api
    assert all(secret not in value for key, value in web.items() if key != "KNOWLEDGE_API_KEY")
    assert not any(key.startswith("VITE_") for key in web)
    assert "OTHER_TOKEN" not in web and "NODE_OPTIONS" not in web


def test_spawn_private_process_group_and_no_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    popen = MagicMock()
    monkeypatch.setattr("scripts.live_workbench.subprocess.Popen", popen)
    environment = {"KNOWLEDGE_API_KEY": "runtime-test-value"}
    workbench.spawn(["uv", "run", "knowledge"], workbench.ROOT, environment)
    assert popen.call_args.args == (["uv", "run", "knowledge"],)
    assert popen.call_args.kwargs == {
        "cwd": workbench.ROOT,
        "env": environment,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "start_new_session": True,
    }


@pytest.fixture
def mocked_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    handlers: dict[int, Callable[[int, Any], None]] = {}
    previous = MagicMock()

    def set_signal(signum: int, handler: Callable[[int, Any], None]) -> Any:
        handlers[signum] = handler
        return previous

    monkeypatch.setattr("scripts.live_workbench.signal.signal", set_signal)
    preflight = MagicMock(return_value=Path("/existing/knowledge.db"))
    monkeypatch.setattr(workbench, "preflight", preflight)
    monkeypatch.setattr(
        "scripts.live_workbench.secrets.token_urlsafe", lambda _length: "runtime-test-value"
    )
    backend, web = MagicMock(pid=123001), MagicMock(pid=123002)
    backend.poll.return_value = web.poll.return_value = None
    spawn = MagicMock(side_effect=[backend, web])
    monkeypatch.setattr(workbench, "spawn", spawn)
    wait_backend, wait_web, cleanup = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(workbench, "wait_backend", wait_backend)
    monkeypatch.setattr(workbench, "wait_web", wait_web)
    monkeypatch.setattr(workbench, "cleanup", cleanup)
    return {
        "handlers": handlers,
        "previous": previous,
        "preflight": preflight,
        "spawn": spawn,
        "backend": backend,
        "web": web,
        "wait_backend": wait_backend,
        "wait_web": wait_web,
        "cleanup": cleanup,
    }


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_run_ready_then_signal_cleanup_secret_not_stdout(
    mocked_run: dict[str, Any], capsys: pytest.CaptureFixture[str], signum: int
) -> None:
    def ready(*_args: Any) -> None:
        assert mocked_run["spawn"].call_count == 2
        mocked_run["handlers"][signum](signum, None)

    mocked_run["wait_web"].side_effect = ready
    assert workbench.run(Path("existing.db"), 5175, 8015) == 128 + signum
    calls = mocked_run["spawn"].call_args_list
    assert calls[0].args[0] == [
        "uv",
        "run",
        "knowledge",
        "serve",
        "--enable-management",
        "--database",
        "/existing/knowledge.db",
        "--host",
        "127.0.0.1",
        "--port",
        "8015",
    ]
    assert calls[1].args[0] == [
        "pnpm",
        "run",
        "dev",
        "--host",
        "127.0.0.1",
        "--port",
        "5175",
        "--strictPort",
    ]
    assert calls[1].args[1] == workbench.ROOT / "web"
    assert calls[0].args[2]["KNOWLEDGE_API_KEY"] == "runtime-test-value"
    assert calls[1].args[2]["KNOWLEDGE_MANAGEMENT_ORIGIN"] == "http://127.0.0.1:8015"
    mocked_run["cleanup"].assert_called_once_with([mocked_run["backend"], mocked_run["web"]])
    assert mocked_run["handlers"][signal.SIGINT] is mocked_run["previous"]
    output = capsys.readouterr()
    assert "runtime-test-value" not in output.out + output.err


def test_run_emits_safe_url_after_readiness(
    mocked_run: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    mocked_run["web"].poll.side_effect = [1]
    assert workbench.run(Path("existing.db"), 5180, 8020) == 1
    output = capsys.readouterr()
    assert "http://127.0.0.1:5180/" in output.out
    assert "runtime-test-value" not in output.out + output.err


@pytest.mark.parametrize("stage", ["preflight", "wait_backend", "wait_web", "spawn"])
def test_start_failure_safe_cleanup_no_env_or_raw_stack(
    mocked_run: dict[str, Any], capsys: pytest.CaptureFixture[str], stage: str
) -> None:
    mocked_run[stage].side_effect = OSError("runtime-test-value raw-stack target env headers")
    assert workbench.run(Path("existing.db"), 5175, 8015) == 1
    if stage in ("preflight", "spawn"):
        mocked_run["cleanup"].assert_called_once_with([])
    elif stage == "wait_backend":
        assert mocked_run["spawn"].call_count == 1
        mocked_run["cleanup"].assert_called_once_with([mocked_run["backend"]])
    else:
        mocked_run["cleanup"].assert_called_once_with([mocked_run["backend"], mocked_run["web"]])
    output = capsys.readouterr()
    assert "runtime-test-value" not in output.out + output.err
    assert "raw-stack" not in output.out + output.err
    assert "已就绪" not in output.out


@pytest.mark.parametrize("stage", ["preflight", "wait_backend"])
def test_signal_during_preflight_or_readiness_does_not_start_web(
    mocked_run: dict[str, Any], stage: str
) -> None:
    def stopped(*_args: Any) -> Path:
        mocked_run["handlers"][signal.SIGTERM](signal.SIGTERM, None)
        return Path("/existing/knowledge.db")

    mocked_run[stage].side_effect = stopped
    assert workbench.run(Path("existing.db"), 5175, 8015) == 143
    assert mocked_run["spawn"].call_count == (0 if stage == "preflight" else 1)


def test_cleanup_only_own_groups_including_exited_leader(monkeypatch: pytest.MonkeyPatch) -> None:
    killpg = MagicMock()
    monkeypatch.setattr("scripts.live_workbench.os.killpg", killpg)
    backend, web = MagicMock(pid=123001), MagicMock(pid=123002)
    backend.poll.return_value = 0
    web.wait.side_effect = [subprocess.TimeoutExpired("pnpm", 5), 0]
    workbench.cleanup([backend, web])
    assert [call.args for call in killpg.call_args_list] == [
        (123002, signal.SIGTERM),
        (123001, signal.SIGTERM),
        (123002, signal.SIGKILL),
        (123001, signal.SIGKILL),
    ]
    assert web.wait.call_count == 2


def test_cleanup_missing_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.live_workbench.os.killpg", MagicMock(side_effect=ProcessLookupError)
    )
    workbench.cleanup([MagicMock(pid=123001)])


def test_backend_health_wait_bounded_no_content(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    process = MagicMock()
    process.poll.return_value = None
    client = MagicMock()
    client.getresponse.return_value.status = 200
    client.getresponse.return_value.read.return_value = b'{"status":"ok","version":"0.1.0"}'
    factory = MagicMock(return_value=client)
    monkeypatch.setattr("scripts.live_workbench.http.client.HTTPConnection", factory)
    workbench.wait_backend(process, 8015, threading.Event())
    factory.assert_called_once_with("127.0.0.1", 8015, timeout=0.5)
    client.request.assert_called_once_with("GET", "/health")
    client.getresponse.return_value.read.assert_called_once_with(2049)
    client.close.assert_called_once()
    output = capsys.readouterr()
    assert output.out == output.err == ""


def test_backend_timeout_failure_and_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    process = MagicMock()
    process.poll.return_value = None
    with pytest.raises(workbench.WorkbenchError, match="超时"):
        workbench.wait_backend(process, 8015, threading.Event(), timeout=0)
    process.poll.return_value = 1
    with pytest.raises(workbench.WorkbenchError, match="启动失败"):
        workbench.wait_backend(process, 8015, threading.Event())
    stop = threading.Event()
    stop.set()
    workbench.wait_backend(process, 8015, stop)


def test_web_wait_child_exit_and_timeout() -> None:
    child = MagicMock()
    child.poll.return_value = 1
    with pytest.raises(workbench.WorkbenchError, match="启动失败"):
        workbench.wait_web([child], 5175, threading.Event())
    with pytest.raises(workbench.WorkbenchError, match="超时"):
        workbench.wait_web([child], 5175, threading.Event(), timeout=0)


def test_second_spawn_failure_closes_backend(
    mocked_run: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    mocked_run["spawn"].side_effect = [mocked_run["backend"], OSError("runtime-test-value")]
    assert workbench.run(Path("existing.db"), 5175, 8015) == 1
    mocked_run["cleanup"].assert_called_once_with([mocked_run["backend"]])
    output = capsys.readouterr()
    assert "runtime-test-value" not in output.out + output.err


def test_real_process_group_cleanup_keeps_unrelated_process() -> None:
    command = [sys.executable, "-c", "import time; time.sleep(60)"]
    unrelated = subprocess.Popen(command, start_new_session=True)
    owned: list[subprocess.Popen[bytes]] = []
    try:
        child = workbench.spawn(command, workbench.ROOT, {})
        owned.append(child)
        workbench.cleanup(owned)
        owned.clear()
        assert child.poll() is not None
        assert unrelated.poll() is None
    finally:
        workbench.cleanup(owned)
        unrelated.terminate()
        unrelated.wait(timeout=5)


@pytest.fixture
def mutation_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    from uuid import uuid4

    from scripts import prepare_mutation_demo

    monkeypatch.setattr(prepare_mutation_demo, "ROOT", tmp_path)
    root = tmp_path / ".knowledge" / "mutation-demo"
    root.mkdir(parents=True, mode=0o700)
    scope_id = str(uuid4())
    parent = root / scope_id
    parent.mkdir(mode=0o700)
    seed = parent / ("seed-" + uuid4().hex)
    seed.mkdir(mode=0o700)
    database = seed / "knowledge.db"
    source_id, dataset_id = uuid4().hex, uuid4().hex
    with sqlite3.connect(database) as connection:
        connection.executescript(
            "CREATE TABLE sources (id TEXT, kind TEXT);"
            "CREATE TABLE documents (source_id TEXT, content_type TEXT);"
            "CREATE TABLE auto_evaluation_config (id INTEGER, enabled INTEGER, "
            "dataset_id TEXT, dataset_version INTEGER, dataset_hash TEXT);"
            "CREATE TABLE evaluation_sets (id TEXT, version INTEGER, content_hash TEXT);"
            "CREATE TABLE mutation_previews (id TEXT);"
            "CREATE TABLE mutation_commands (id TEXT);"
        )
        connection.execute("INSERT INTO sources VALUES (?, 'file')", (source_id,))
        connection.execute("INSERT INTO documents VALUES (?, 'markdown')", (source_id,))
        connection.execute(
            "INSERT INTO auto_evaluation_config VALUES (1,1,?,1,?)", (dataset_id, "a" * 64)
        )
        connection.execute("INSERT INTO evaluation_sets VALUES (?,1,?)", (dataset_id, "a" * 64))
    database.chmod(0o600)
    report = seed / "report.json"
    report.write_text(json.dumps({"status": "passed", "artifacts": {"database": "knowledge.db"}}))
    report.chmod(0o600)
    manifest = parent / "mutation-manifest.json"
    from uuid import UUID

    manifest.write_text(
        json.dumps(
            {
                "kind": "knowledge-mutation-demo-v1",
                "scope_id": scope_id,
                "database": database.relative_to(parent).as_posix(),
                "allowed_source_ids": [str(UUID(source_id))],
                "created_at": "2026-11-17T00:00:00+00:00",
            }
        )
    )
    manifest.chmod(0o600)
    return manifest, database


def test_mutation_preflight_valid_readonly(mutation_demo: tuple[Path, Path]) -> None:
    manifest, database = mutation_demo
    before = database.read_bytes()
    assert workbench.mutation_preflight(database, manifest, "demo-editor") == manifest
    assert database.read_bytes() == before


@pytest.mark.parametrize("actor", ["", " ", "../actor", "x\nHeader:bad", "编辑", "x" * 81, "-root"])
def test_mutation_unsafe_actor_no_children(
    mutation_demo: tuple[Path, Path],
    mocked_run: dict[str, Any],
    actor: str,
) -> None:
    manifest, database = mutation_demo
    assert workbench.run(database, 5180, 8020, manifest, actor) == 1
    mocked_run["spawn"].assert_not_called()
    mocked_run["cleanup"].assert_called_once_with([])


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "symlink_manifest",
        "symlink_db",
        "symlink_parent",
        "wrong_db",
        "disabled",
        "not_owned",
        "wrong_scope",
        "noncopy",
    ],
)
def test_mutation_preflight_rejects_before_spawn(
    mutation_demo: tuple[Path, Path],
    mocked_run: dict[str, Any],
    case: str,
    tmp_path: Path,
) -> None:
    manifest, database = mutation_demo
    if case == "missing":
        manifest = manifest.with_name("missing.json")
    elif case in {"symlink_manifest", "symlink_db", "symlink_parent"}:
        target = {
            "symlink_manifest": manifest,
            "symlink_db": database,
            "symlink_parent": database.parent,
        }[case]
        saved = target.with_name(target.name + "-saved")
        target.rename(saved)
        target.symlink_to(saved, target_is_directory=saved.is_dir())
    elif case in {"wrong_db", "noncopy"}:
        database = tmp_path / "business.db"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE business (id INTEGER)")
        database.chmod(0o600)
        if case == "noncopy":
            payload = json.loads(manifest.read_text())
            payload["database"] = str(database)
            manifest.write_text(json.dumps(payload))
    elif case == "disabled":
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE auto_evaluation_config SET enabled=0")
    elif case == "not_owned":
        manifest.chmod(0o644)
    elif case == "wrong_scope":
        payload = json.loads(manifest.read_text())
        payload["scope_id"] = "00000000-0000-0000-0000-000000000000"
        manifest.write_text(json.dumps(payload))
    assert workbench.run(database, 5180, 8020, manifest, "demo-editor") == 1
    mocked_run["spawn"].assert_not_called()
    mocked_run["cleanup"].assert_called_once_with([])


@pytest.mark.parametrize("manifest,actor", [(Path("manifest.json"), None), (None, "demo-editor")])
def test_mutation_args_must_be_paired(
    mocked_run: dict[str, Any],
    manifest: Path | None,
    actor: str | None,
) -> None:
    assert workbench.run(Path("db"), 5180, 8020, manifest, actor) == 1
    mocked_run["spawn"].assert_not_called()


def test_readonly_cleans_inherited_mutation_environment() -> None:
    parent = {
        "PATH": "/usr/bin",
        "KNOWLEDGE_MUTATION_ENABLED": "1",
        "KNOWLEDGE_MUTATION_KEY": "old-write",
        "KNOWLEDGE_MUTATION_ACTOR": "old-actor",
        "VITE_KNOWLEDGE_MUTATION_KEY": "old-write",
    }
    before = parent.copy()
    backend, web = workbench.child_environments(parent, 8020, "new-read")
    assert parent == before
    for child in (backend, web):
        assert not any("MUTATION" in name for name in child)


@pytest.mark.parametrize(
    "key,actor",
    [
        (None, "demo-editor"),
        ("write-test", None),
        ("read-test", "demo-editor"),
        ("write-test", "unsafe actor"),
    ],
)
def test_partial_or_equal_child_credentials_closed(key: str | None, actor: str | None) -> None:
    with pytest.raises(workbench.WorkbenchError):
        workbench.child_environments({}, 8020, "read-test", key, actor)


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_mutation_launcher_flags_private_env_and_signal_cleanup(
    mutation_demo: tuple[Path, Path],
    mocked_run: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    signum: int,
) -> None:
    manifest, database = mutation_demo
    mocked_run["preflight"].return_value = database
    monkeypatch.setattr(
        "scripts.live_workbench.secrets.token_urlsafe",
        MagicMock(side_effect=["read-test", "write-test"]),
    )

    def stopped(*_args: Any) -> None:
        mocked_run["handlers"][signum](signum, None)

    mocked_run["wait_web"].side_effect = stopped
    assert workbench.run(database, 5180, 8020, manifest, "demo-editor") == 128 + signum
    calls = mocked_run["spawn"].call_args_list
    command = calls[0].args[0]
    assert "--enable-management" in command and "--enable-mutations" in command
    assert command[command.index("--mutation-manifest") + 1] == str(manifest)
    assert command[command.index("--mutation-origin") + 1] == "http://127.0.0.1:5180"
    for call in calls:
        assert "read-test" not in call.args[0] and "write-test" not in call.args[0]
        child = call.args[2]
        assert child["KNOWLEDGE_API_KEY"] == "read-test"
        assert child["KNOWLEDGE_MUTATION_KEY"] == "write-test"
        assert child["KNOWLEDGE_MUTATION_ACTOR"] == "demo-editor"
    assert calls[1].args[2]["KNOWLEDGE_MUTATION_ENABLED"] == "1"
    assert calls[1].args[2]["KNOWLEDGE_MANAGEMENT_ORIGIN"] == "http://127.0.0.1:8020"
    mocked_run["cleanup"].assert_called_once_with([mocked_run["backend"], mocked_run["web"]])
    output = capsys.readouterr()
    assert (
        "read-test" not in output.out + output.err and "write-test" not in output.out + output.err
    )


@pytest.mark.parametrize("stage", ["spawn", "wait_backend", "wait_web"])
def test_mutation_start_failure_cleanup(
    mutation_demo: tuple[Path, Path],
    mocked_run: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest, database = mutation_demo
    mocked_run["preflight"].return_value = database
    monkeypatch.setattr(
        "scripts.live_workbench.secrets.token_urlsafe",
        MagicMock(side_effect=["read-test", "write-test"]),
    )
    mocked_run[stage].side_effect = OSError("write-test raw-stack /private/path")
    assert workbench.run(database, 5180, 8020, manifest, "demo-editor") == 1
    owned = [] if stage == "spawn" else [mocked_run["backend"]]
    if stage == "wait_web":
        owned.append(mocked_run["web"])
    mocked_run["cleanup"].assert_called_once_with(owned)
    output = capsys.readouterr()
    assert "raw-stack" not in output.err and "write-test" not in output.err


def test_equal_generated_credentials_no_spawn(
    mutation_demo: tuple[Path, Path],
    mocked_run: dict[str, Any],
) -> None:
    manifest, database = mutation_demo
    assert workbench.run(database, 5180, 8020, manifest, "demo-editor") == 1
    mocked_run["spawn"].assert_not_called()
