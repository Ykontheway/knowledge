from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import mutation_workbench_acceptance as acceptance
from scripts import prepare_mutation_demo as prepare


def test_child_failure_always_cleanup_and_redacts_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = acceptance.Driver()
    child = driver.children.start(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        acceptance.ROOT,
        acceptance.safe_environment(),
    )

    def fail() -> None:
        raise RuntimeError("TOKEN user body /absolute/private/location RAW_STACK")

    monkeypatch.setattr(driver, "execute", fail)
    report, path = driver.run()
    assert path is None and report["status"] == "failed"
    assert report["children_stopped"] and child.poll() is not None
    rendered = json.dumps(report)
    assert not any(value in rendered for value in ("TOKEN", "body", "/absolute", "RAW_STACK"))
    acceptance.safe_report(report)


def test_child_start_failure_closes_log(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("secret")

    monkeypatch.setattr(subprocess, "Popen", fail)
    children = acceptance.Children()
    with pytest.raises(acceptance.AcceptanceError, match="CHILD_START_FAILED"):
        children.start(["missing"], Path.cwd(), {})
    assert children.close() == []


def test_timeout_cleanup_terminates_process_group() -> None:
    children = acceptance.Children()
    child = children.start(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        Path.cwd(),
        acceptance.safe_environment(),
    )
    try:
        with pytest.raises(acceptance.AcceptanceError, match="CHILD_READY_TIMEOUT"):
            acceptance.wait_ready(child, lambda: (_ for _ in ()).throw(RuntimeError()), timeout=0)
    finally:
        summary = children.close()
    assert summary[0]["stopped"] and child.poll() is not None


def test_environment_only_toolchain_and_generated_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "KNOWLEDGE_API_KEY",
        "KNOWLEDGE_MUTATION_KEY",
        "VITE_SECRET",
        "HTTP_PROXY",
        "PYTHONPATH",
    ):
        monkeypatch.setenv(name, "shared-secret")
    environment = acceptance.safe_environment()
    assert not any(
        name in environment
        for name in (
            "KNOWLEDGE_API_KEY",
            "KNOWLEDGE_MUTATION_KEY",
            "VITE_SECRET",
            "HTTP_PROXY",
            "PYTHONPATH",
        )
    )
    driver = acceptance.Driver()
    assert driver.read_credential != driver.write_credential
    assert driver.read_credential != "shared-secret"
    assert (
        "KNOWLEDGE_API_KEY" not in os.environ or os.environ["KNOWLEDGE_API_KEY"] == "shared-secret"
    )


def test_only_fixed_vitest_file_no_optional_argv() -> None:
    assert acceptance.vitest_argv() == ["pnpm", "exec", "vitest", "run", acceptance.FIXED_TEST]
    result = subprocess.run(
        [sys.executable, str(Path(acceptance.__file__)), "--vitest-argv", "evil"],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 2


@pytest.mark.parametrize(
    "origin",
    [
        "http://example.com:9000",
        "http://127.0.0.1:5175",
        "http://127.0.0.1:8015",
        "http://127.0.0.1:65536",
        "http://127.0.0.1:9000?key=secret",
        "http://secret@127.0.0.1:9000",
        "https://127.0.0.1:9000",
    ],
)
def test_loopback_only_and_reserved_ports(origin: str) -> None:
    with pytest.raises(acceptance.AcceptanceError):
        acceptance.validate_origin(origin)


def test_generated_port_is_ephemeral_not_shared() -> None:
    port = acceptance.free_port()
    assert 1 <= port <= 65535 and port not in {5175, 8015}


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "secret"},
        {"confirmation_token": "secret"},
        {"raw_stack": "secret"},
        {"status": "/absolute/path"},
        {"checks": {"okay": {"api_key": "secret"}}},
        {"status": "raw error body"},
        {"actor_id": "demo-editor"},
    ],
)
def test_report_rejects_sensitive_fields_and_arbitrary_strings(payload: object) -> None:
    with pytest.raises(acceptance.AcceptanceError):
        acceptance.safe_report(payload)


def test_report_private_exclusive_no_symlink_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    acceptance.write_report(target, {"status": "passed", "children_stopped": True})
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        acceptance.write_report(target, {"status": "failed"})
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        acceptance.write_report(link, {"status": "failed"})
    assert json.loads(target.read_text())["status"] == "passed"


def test_snapshot_is_readonly_digest_not_body(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE documents(id TEXT PRIMARY KEY, body TEXT)")
        connection.execute("INSERT INTO documents VALUES('id', 'PRIVATE_DOCUMENT_BODY')")
        connection.execute("CREATE TABLE mutation_previews(id TEXT, text TEXT)")
        connection.execute("CREATE TABLE fts_blob(id INTEGER, block BLOB)")
        connection.execute("INSERT INTO fts_blob VALUES(1, ?)", (b"private-binary",))
    before = database.read_bytes()
    result = acceptance.snapshot(database)
    assert result["counts"]["documents"] == 1
    assert result["quick_check"] and result["foreign_keys_valid"]
    assert "PRIVATE_DOCUMENT_BODY" not in json.dumps(result)
    assert before == database.read_bytes()
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO mutation_previews VALUES('preview', 'SENSITIVE')")
    assert acceptance.snapshot(database)["core_hash"] == result["core_hash"]
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE documents SET body='CHANGED'")
    assert acceptance.snapshot(database)["core_hash"] != result["core_hash"]


def test_pathownership_rejects_shared_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prepare, "ROOT", tmp_path)
    shared = tmp_path / "shared"
    shared.mkdir()
    manifest = shared / "mutation-manifest.json"
    manifest.write_text(json.dumps({"database": "knowledge.db"}))
    (shared / "knowledge.db").touch()
    with pytest.raises(prepare.DemoError, match="GENERATED_DEMO_REQUIRED"):
        acceptance.owned_database(manifest)


def test_pathownership_rejects_symlink_even_before_loading(tmp_path: Path) -> None:
    link = tmp_path / "mutation-manifest.json"
    target = tmp_path / "target.json"
    target.write_text("{}")
    link.symlink_to(target)
    with pytest.raises(prepare.DemoError, match="INVALID_DEMO_PATH"):
        acceptance.owned_database(link)


def test_default_frontend_has_exactly_one_environment_gated_live_test() -> None:
    source = (acceptance.ROOT / "web" / acceptance.FIXED_TEST).read_text()
    assert 'process.env.KNOWLEDGE_MUTATION_ACCEPTANCE === "1"' in source
    assert "describe.skipIf(!enabled)" in source
    assert source.count("  it(") == 1
    assert "vi.mock" not in source and "mockResolvedValue" not in source
    assert "new MutationHttpClient(fetcher)" in source and "createElement(ChangesPage" in source


def test_http_errors_do_not_read_error_body(monkeypatch: pytest.MonkeyPatch) -> None:
    class ErrorResponse:
        status = 403

        def __enter__(self) -> ErrorResponse:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def read(self, *args: object) -> None:
            raise AssertionError("must not read rejected body")

    class Opener:
        def open(self, *args: object, **kwargs: object) -> ErrorResponse:
            return ErrorResponse()

    monkeypatch.setattr(acceptance, "build_opener", lambda *args: Opener())
    assert (
        acceptance.http("http://127.0.0.1:9123", "/v1/mutations/previews", body={}, expected=403)
        == {}
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_report_rejects_nonfinite_metrics(value: float) -> None:
    with pytest.raises(acceptance.AcceptanceError):
        acceptance.safe_report({"metrics": {"mean_recall": value}})


def test_close_continues_after_one_cleanup_error(monkeypatch: pytest.MonkeyPatch) -> None:
    children = acceptance.Children()
    for _ in range(2):
        children.start(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            Path.cwd(),
            acceptance.safe_environment(),
        )
    real_stop = children.stop
    calls = []

    def stop(child: subprocess.Popen[bytes]) -> None:
        real_stop(child)
        calls.append(child.pid)
        if len(calls) == 1:
            raise OSError("redacted cleanup failure")

    monkeypatch.setattr(children, "stop", stop)
    report = children.close()
    assert len(calls) == 2 and not report[0]["stopped"] and report[1]["stopped"]
    acceptance.safe_report({"children": report})
