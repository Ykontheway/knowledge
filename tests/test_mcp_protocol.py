"""B5/U22：真实子进程 stdio 协议、可选依赖边界与数据库零写。"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import queue
import sqlite3
import subprocess
import sys
import threading
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr
from dataclasses import dataclass, field
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from uuid import UUID

import pytest
from sqlalchemy import URL, update

from knowledge.application import KnowledgeLibrary
from knowledge.storage import create_schema, create_session_factory, create_sqlite_engine
from knowledge.storage.tables import DocumentRow, KnowledgeUnitRow, SourceRow

PROJECT = Path(__file__).resolve().parents[1]
SECRET = "private_exception_DSN_locator_metadata_do_not_echo"
TOOLS = {"search", "build_context", "get_evidence", "get_lineage", "compare_documents"}
OLD = "# Rules\nKeep exact historical evidence.\n\n# Quota\nquota is 10.\n"
NEW = "# Rules\nKeep exact historical evidence.\n\n# Quota\nquota is 20.\n\n# Extra\nNew rule.\n"


def _require_mcp() -> None:
    if find_spec("mcp") is None:
        pytest.skip("未安装 MCP 可选依赖")
    import_module("mcp")


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(PROJECT / "src"), environment.get("PYTHONPATH", "")]
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _run_python(code: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        env=_environment(),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def _command(entry: str, database: Path) -> list[str]:
    if entry == "cli":
        return [sys.executable, "-m", "knowledge", "mcp", "serve", "--database", str(database)]
    return [sys.executable, "-m", "knowledge.mcp.server", "--database", str(database)]


@dataclass
class ProtocolClient:
    process: subprocess.Popen[str]
    responses: queue.Queue[Any] = field(default_factory=queue.Queue)
    lines: list[str] = field(default_factory=list)
    stderr: str = ""
    next_id: int = 0
    reader: threading.Thread | None = None

    def pump(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.lines.append(line)
            try:
                self.responses.put(json.loads(line))
            except ValueError as error:
                self.responses.put(error)

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        try:
            response = self.responses.get(timeout=15)
        except queue.Empty:
            pytest.fail(f"stdio response timeout: {method}")
        assert isinstance(response, dict), f"non-JSON stdout: {response}"
        assert response["jsonrpc"] == "2.0" and response["id"] == self.next_id
        return response

    def initialize(self) -> dict[str, Any]:
        response = self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "protocol-test", "version": "1.0"},
            },
        )
        assert response["result"]["serverInfo"] == {"name": "knowledge", "version": "0.1.0"}
        assert "tools" in response["result"]["capabilities"]
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return response

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.request("tools/call", {"name": name, "arguments": arguments})["result"]
        assert isinstance(result, dict)
        return result

    def finish(self) -> None:
        assert self.process.stdin is not None
        if not self.process.stdin.closed:
            self.process.stdin.close()  # EOF，不是 kill/terminate。
        self.process.wait(timeout=15)
        assert self.reader is not None
        self.reader.join(timeout=5)
        assert not self.reader.is_alive()
        assert self.process.stderr is not None
        self.stderr = self.process.stderr.read()

    def assert_clean(self) -> None:
        assert self.process.returncode == 0, self.stderr
        assert len(self.lines) == self.next_id
        for line in self.lines:
            assert json.loads(line)["jsonrpc"] == "2.0"
        assert "Traceback" not in self.stderr


@contextmanager
def _session(
    database: Path, entry: str = "module", code: str | None = None
) -> Iterator[ProtocolClient]:
    _require_mcp()
    command = (
        _command(entry, database) if code is None else [sys.executable, "-c", code, str(database)]
    )
    process = subprocess.Popen(
        command,
        cwd=database.parent,
        env=_environment(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    client = ProtocolClient(process)
    client.reader = threading.Thread(target=client.pump, daemon=True)
    client.reader.start()
    try:
        yield client
    finally:
        try:
            client.finish()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


@dataclass(frozen=True)
class Store:
    path: Path
    old_id: str
    new_id: str
    old_unit: str
    lineage_id: str


@pytest.fixture
def store(tmp_path: Path) -> Store:
    path = tmp_path / "知识 ?#%.db"
    # URL 对象绕过字符串解析，防止 ?/# 被误当成 URL 参数。
    engine = create_sqlite_engine(URL.create("sqlite+pysqlite", database=str(path)))  # type: ignore[arg-type]
    try:
        create_schema(engine)
        library = KnowledgeLibrary(create_session_factory(engine))
        source = tmp_path / "rules.md"
        source.write_text(OLD, encoding="utf-8")
        old = library.import_path(source).imported[0].result
        source.write_text(NEW, encoding="utf-8")
        new = library.import_path(source).imported[0].result
        with engine.begin() as connection:
            connection.execute(update(SourceRow).values(uri=SECRET, metadata_json={"raw": SECRET}))
            connection.execute(
                update(DocumentRow).values(locator=SECRET, metadata_json={"raw": SECRET})
            )
            connection.execute(update(KnowledgeUnitRow).values(metadata_json={"raw": SECRET}))
        return Store(
            path,
            str(old.ingestion.document.id),
            str(new.ingestion.document.id),
            str(old.units[1].id),
            str(old.units[1].lineage_id),
        )
    finally:
        engine.dispose()


def _fingerprint(path: Path) -> dict[str, str]:
    # 同时比较文件清单，捕获意外生成的 WAL/SHM/journal 或默认数据库。
    return {
        item.name: hashlib.sha256(item.read_bytes()).hexdigest()
        for item in path.parent.iterdir()
        if item.is_file()
    }


def _payload(result: dict[str, Any]) -> dict[str, Any]:
    assert result.get("isError", False) is False
    assert len(result["content"]) == 1 and result["content"][0]["type"] == "text"
    payload: dict[str, Any] = json.loads(result["content"][0]["text"])
    assert result["structuredContent"] == payload
    assert SECRET not in json.dumps(result)
    return payload


def test_pyproject_mcp_extra_and_entrypoint_are_isolated() -> None:
    project = tomllib.loads((PROJECT / "pyproject.toml").read_text())["project"]
    assert project["optional-dependencies"]["mcp"] == ["mcp>=1.30.0,<2"]
    assert project["scripts"]["knowledge-mcp"] == "knowledge.mcp.server:main"
    assert not any(dependency.startswith("mcp") for dependency in project["dependencies"])


@pytest.mark.parametrize("entry", ["module", "cli"])
def test_initialize_list_all_five_calls_eof_and_hash_unchanged(store: Store, entry: str) -> None:
    before = _fingerprint(store.path)
    with _session(store.path, entry) as client:
        client.initialize()
        tools = client.request("tools/list")["result"]["tools"]
        assert {tool["name"] for tool in tools} == TOOLS
        assert len(tools) == 5
        from jsonschema import Draft202012Validator
        from mcp import types

        from knowledge.mcp.server import TOOL_OUTPUTS

        schemas = {}
        for tool in tools:
            assert tool["inputSchema"]["additionalProperties"] is False
            assert tool["annotations"] == {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            }
            # 真实 tools/list JSON 再经 SDK DTO 解析，要求标准输出 schema 与 typed annotations。
            dto = types.Tool.model_validate(tool)
            assert isinstance(dto.annotations, types.ToolAnnotations)
            parsed = dto.model_dump(by_alias=True, exclude_none=True)
            assert parsed["annotations"] == tool["annotations"]
            schema = tool["outputSchema"]
            assert parsed["outputSchema"] == schema
            assert "_meta" not in tool
            assert schema == TOOL_OUTPUTS[tool["name"]].model_json_schema(mode="serialization")
            Draft202012Validator.check_schema(schema)
            assert schema["additionalProperties"] is False
            for definition in schema.get("$defs", {}).values():
                if definition.get("type") == "object":
                    assert definition["additionalProperties"] is False
            schemas[tool["name"]] = schema
        search = _payload(client.call("search", {"query": "quota"}))
        assert search["mode"] == "lexical" and search["include_stale"] is False
        assert len(search["hits"]) == 1 and "20" in search["hits"][0]["text"]
        context = _payload(client.call("build_context", {"query": "quota"}))
        assert context["blocks"][0]["label"] == "[1]"
        evidence = _payload(client.call("get_evidence", {"unit_id": store.old_unit}))
        assert evidence["document_id"] == store.old_id and "10" in evidence["text"]
        assert evidence["content_hash"] == hashlib.sha256(evidence["text"].encode()).hexdigest()
        lineage = _payload(client.call("get_lineage", {"lineage_id": store.lineage_id, "limit": 1}))
        assert lineage["versions"]["total"] == 2 and len(lineage["versions"]["items"]) == 1
        diff = _payload(
            client.call(
                "compare_documents",
                {"old_document_id": store.old_id, "new_document_id": store.new_id},
            )
        )
        assert diff["counts"] == {
            "added": 1,
            "modified": 1,
            "moved": 0,
            "removed": 0,
            "unchanged": 1,
        }
        payloads = {
            "search": search,
            "build_context": context,
            "get_evidence": evidence,
            "get_lineage": lineage,
            "compare_documents": diff,
        }
        for name, payload in payloads.items():
            Draft202012Validator(schemas[name]).validate(payload)
    client.assert_clean()
    assert _fingerprint(store.path) == before


@pytest.mark.parametrize("initialized", [False, True])
def test_eof_with_no_calls_cleans_up_without_writing(store: Store, initialized: bool) -> None:
    before = _fingerprint(store.path)
    with _session(store.path) as client:
        if initialized:
            client.initialize()
    client.assert_clean()
    assert _fingerprint(store.path) == before


def test_errors_are_fixed_and_do_not_reflect_inputs_or_paths(store: Store) -> None:
    before = _fingerprint(store.path)
    with _session(store.path) as client:
        client.initialize()
        requests: list[tuple[str, dict[str, Any], str, int]] = [
            (SECRET, {}, "mcp_tool_not_found", 404),
            ("search", {"query": "quota", "raw": SECRET}, "mcp_invalid_arguments", 400),
            ("search", {"query": "quota", "mode": "vector"}, "mcp_invalid_arguments", 400),
            ("search", {"query": "quota", "include_stale": True}, "mcp_invalid_arguments", 400),
            ("search", {"query": "quota", "top_k": True}, "mcp_invalid_arguments", 400),
            ("search", {"query": "quota", "candidate_limit": 1}, "mcp_invalid_arguments", 400),
            ("get_evidence", {"unit_id": str(store.path)}, "mcp_invalid_arguments", 400),
            ("get_evidence", {"unit_id": str(UUID(int=1))}, "unit_not_found", 404),
            ("get_lineage", {"lineage_id": str(UUID(int=1))}, "lineage_not_found", 404),
            (
                "compare_documents",
                {"old_document_id": str(UUID(int=1)), "new_document_id": store.new_id},
                "document_not_found",
                404,
            ),
        ]
        for name, arguments, code, status in requests:
            result = client.call(name, arguments)
            assert result["isError"] is True
            assert json.loads(result["content"][0]["text"]) == {
                "error": {"code": code, "status": status}
            }
            encoded = json.dumps(result)
            assert SECRET not in encoded
            assert str(store.path) not in encoded and "Traceback" not in encoded
    client.assert_clean()
    assert _fingerprint(store.path) == before


def test_prints_logs_and_unexpected_exceptions_never_pollute_protocol(store: Store) -> None:
    code = f"""
import logging
import sys
from knowledge.mcp.server import main
from knowledge.mcp.service import McpReadError, McpReadOnlyService
secret = {SECRET!r}
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
logger = logging.getLogger("noisy-service")
logger.addHandler(logging.StreamHandler(sys.stdout))
logger.propagate = False
def fail(self, query):
    print("accidental stdout diagnostic")
    try:
        raise RuntimeError(secret + sys.argv[1])
    except RuntimeError:
        logger.exception("private details %s", secret)
        raise
McpReadOnlyService.search = fail
def polluted_error(self, query):
    raise McpReadError(503, secret)
McpReadOnlyService.build_context = polluted_error
raise SystemExit(main(["--database", sys.argv[1]]))
"""
    before = _fingerprint(store.path)
    with _session(store.path, code=code) as client:
        client.initialize()
        for name in ("search", "build_context"):
            result = client.call(name, {"query": "quota"})
            assert result["isError"] is True
            assert json.loads(result["content"][0]["text"]) == {
                "error": {"code": "mcp_internal_error", "status": 500}
            }
    client.assert_clean()
    assert "accidental stdout diagnostic" in client.stderr
    assert "ERROR: MCP server event" in client.stderr
    assert SECRET not in client.stderr and str(store.path) not in client.stderr
    assert _fingerprint(store.path) == before


@pytest.mark.parametrize("entry", ["module", "cli"])
@pytest.mark.parametrize("existing", [False, True])
def test_missing_or_empty_database_never_created_or_upgraded(
    tmp_path: Path, entry: str, existing: bool
) -> None:
    _require_mcp()
    database = tmp_path / "unavailable.db"
    if existing:
        database.touch()
        before = _fingerprint(database)
        with _session(database, entry) as client:
            client.initialize()
            error_result = client.call("search", {"query": "quota"})
            assert error_result["isError"] is True
            error = json.loads(error_result["content"][0]["text"])["error"]
            assert error["code"] == "mcp_storage_unavailable"
        client.assert_clean()
        assert _fingerprint(database) == before and database.read_bytes() == b""
    else:
        result = subprocess.run(
            _command(entry, database),
            cwd=tmp_path,
            env=_environment(),
            input="",
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 1 and result.stdout == ""
        assert str(database) not in result.stderr and "Traceback" not in result.stderr
        assert list(tmp_path.iterdir()) == []


def test_old_schema_is_not_upgraded_during_stdio(store: Store) -> None:
    with sqlite3.connect(store.path) as connection:
        for suffix in ("ai", "au", "ad"):
            connection.execute(f"DROP TRIGGER knowledge_units_fts_{suffix}")
        connection.execute("DROP TABLE knowledge_units_fts")
        connection.execute("DROP INDEX ix_knowledge_units_lineage_id")
        connection.execute("ALTER TABLE knowledge_units DROP COLUMN lineage_id")
    before = _fingerprint(store.path)
    with _session(store.path, "cli") as client:
        client.initialize()
        result = client.call("search", {"query": "quota"})
        assert result["isError"] is True
        error = json.loads(result["content"][0]["text"])["error"]
        assert error["code"] == "mcp_storage_unavailable"
    client.assert_clean()
    assert _fingerprint(store.path) == before


@pytest.mark.parametrize("entry", ["cli", "console"])
@pytest.mark.parametrize("existing", [False, True])
def test_no_sdk_safe_stderr_exit_one_without_storage(
    tmp_path: Path, entry: str, existing: bool
) -> None:
    database = tmp_path / "missing.db"
    if existing:
        database.touch()
    before = _fingerprint(database)
    if entry == "cli":
        invocation = (
            "from knowledge.cli import main; "
            "raise SystemExit(main(['mcp', 'serve', '--database', 'missing.db']))"
        )
    else:
        invocation = (
            "from knowledge.mcp.server import main; "
            "raise SystemExit(main(['--database', 'missing.db']))"
        )
    code = f"""
import sys
sys.modules["mcp"] = None
{invocation}
"""
    result = _run_python(code, tmp_path)
    assert result.returncode == 1 and result.stdout == ""
    assert "pip install 'knowledge-ykforward[mcp]'" in result.stderr
    assert "Traceback" not in result.stderr and str(tmp_path) not in result.stderr
    assert _fingerprint(database) == before


@pytest.mark.parametrize(
    "arguments", [["--version"], ["--help"], ["mcp", "--help"], ["mcp", "serve", "--help"]]
)
def test_cli_help_version_lazy_without_any_optional_sdk(
    tmp_path: Path, arguments: list[str]
) -> None:
    code = f"""
import sys
for name in ("mcp", "fastapi", "uvicorn", "openai", "langchain_openai", "lancedb"):
    sys.modules[name] = None
from knowledge.cli import main
assert "knowledge.mcp.server" not in sys.modules
assert main({arguments!r}) == 0
assert "knowledge.mcp.server" not in sys.modules
"""
    result = _run_python(code, tmp_path)
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_engine_disposed_on_eof_and_logging_restored(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    _require_mcp()
    from knowledge.mcp import server

    engine = create_sqlite_engine(URL.create("sqlite+pysqlite", database=str(store.path)))  # type: ignore[arg-type]
    disposed = Mock(wraps=engine.dispose)
    monkeypatch.setattr(engine, "dispose", disposed)
    monkeypatch.setattr(server, "create_engine", lambda *args, **kwargs: engine)
    stdin = io.TextIOWrapper(io.BytesIO())
    stdout = io.TextIOWrapper(io.BytesIO())
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    root = logging.getLogger()
    handlers = root.handlers[:]
    level = root.level
    before = _fingerprint(store.path)
    with redirect_stderr(io.StringIO()):
        server.run_server(store.path)
    disposed.assert_called_once()
    assert root.handlers == handlers and root.level == level
    assert not stdin.buffer.closed and not stdout.buffer.closed
    assert _fingerprint(store.path) == before


@pytest.mark.parametrize("stage", ["create_server", "dispose"])
def test_startup_and_disposal_errors_safe_and_release_engine(
    store: Store, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    _require_mcp()
    from knowledge.mcp import server

    engine = create_sqlite_engine(URL.create("sqlite+pysqlite", database=str(store.path)))  # type: ignore[arg-type]
    disposed = Mock(wraps=engine.dispose)
    if stage == "dispose":

        def fail_dispose() -> None:
            engine.pool.dispose()
            raise RuntimeError(SECRET)

        disposed = Mock(side_effect=fail_dispose)
    monkeypatch.setattr(engine, "dispose", disposed)
    monkeypatch.setattr(server, "create_engine", lambda *args, **kwargs: engine)
    if stage == "create_server":
        monkeypatch.setattr(server, "create_server", Mock(side_effect=RuntimeError(SECRET)))
    stdout = io.TextIOWrapper(io.BytesIO())
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO()))
    monkeypatch.setattr(sys, "stdout", stdout)
    stderr = io.StringIO()
    before = _fingerprint(store.path)
    with redirect_stderr(stderr):
        assert server.main(["--database", str(store.path)]) == 1
    disposed.assert_called_once()
    assert stdout.buffer.getvalue() == b""
    assert SECRET not in stderr.getvalue() and "Traceback" not in stderr.getvalue()
    assert _fingerprint(store.path) == before


def _assert_safe_error(result: dict[str, Any], code: str, status: int) -> None:
    assert result["isError"] is True
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"
    assert json.loads(result["content"][0]["text"]) == {"error": {"code": code, "status": status}}
    assert "structuredContent" not in result
    assert SECRET not in json.dumps(result)


def test_every_tool_rejects_all_injected_fields_without_logging_values(store: Store) -> None:
    arguments = {
        "search": {"query": "quota"},
        "build_context": {"query": "quota"},
        "get_evidence": {"unit_id": store.old_unit},
        "get_lineage": {"lineage_id": store.lineage_id},
        "compare_documents": {
            "old_document_id": store.old_id,
            "new_document_id": store.new_id,
        },
    }
    before = _fingerprint(store.path)
    with _session(store.path) as client:
        client.initialize()
        _assert_safe_error(client.call(SECRET, {"sql": SECRET}), "mcp_tool_not_found", 404)
        for name, valid in arguments.items():
            for field_name in ("include_stale", "mode", "sql", "path", "extra"):
                _assert_safe_error(
                    client.call(name, {**valid, field_name: SECRET}), "mcp_invalid_arguments", 400
                )
        for name in ("search", "build_context"):
            for top_k in (True, False):
                _assert_safe_error(
                    client.call(name, {"query": "quota", "top_k": top_k}),
                    "mcp_invalid_arguments",
                    400,
                )
            for at in (1700000000, 1700000000.5, "1700000000", "-1700000000", True):
                _assert_safe_error(
                    client.call(name, {"query": "quota", "at": at}), "mcp_invalid_arguments", 400
                )
            _payload(client.call(name, {"query": "quota", "at": "2026-01-01T00:00:00Z"}))
    client.assert_clean()
    assert SECRET not in client.stderr and str(store.path) not in client.stderr
    assert _fingerprint(store.path) == before


@pytest.mark.parametrize("bad_value", ["\ud800", "\udfff"])
def test_unicode_query_reaching_handler_is_safe_invalid_arguments(bad_value: str) -> None:
    _require_mcp()
    import anyio
    from mcp import types

    from knowledge.mcp.server import create_server
    from knowledge.mcp.service import McpReadOnlyService

    service = Mock(spec=McpReadOnlyService)
    server = create_server(service)

    async def call() -> None:
        request = types.CallToolRequest.model_validate(
            {
                "method": "tools/call",
                "params": {"name": "search", "arguments": {"query": bad_value}},
            }
        )
        response = await server.request_handlers[types.CallToolRequest](request)
        _assert_safe_error(
            response.model_dump(by_alias=True, exclude_none=True), "mcp_invalid_arguments", 400
        )

    anyio.run(call)
    service.search.assert_not_called()


def test_sdk_parser_rejects_escaped_surrogate_without_reflecting_input(store: Store) -> None:
    # JSONRPC 的解析仍完全交给官方 SDK；无法解析的消息没有可安全寻址的工具响应。
    with _session(store.path) as client:
        client.initialize()
        client.send(
            {
                "jsonrpc": "2.0",
                "id": SECRET,
                "method": "tools/call",
                "params": {"name": "search", "arguments": {"query": SECRET + "\ud800"}},
            }
        )
        client.next_id += 1
        client.send(
            {
                "jsonrpc": "2.0",
                "id": client.next_id,
                "method": "tools/call",
                "params": {"name": "search", "arguments": {"query": "quota"}},
            }
        )
        while True:
            response = client.responses.get(timeout=15)
            if response.get("method") == "notifications/message":
                assert response == {
                    "jsonrpc": "2.0",
                    "method": "notifications/message",
                    "params": {
                        "level": "error",
                        "data": "Internal Server Error",
                        "logger": "mcp.server.exception_handler",
                    },
                }
                continue
            assert response["id"] == client.next_id and response["jsonrpc"] == "2.0"
            _payload(response["result"])
            break
    assert client.process.returncode == 0
    # SDK 对不可解析消息额外发送一个固定、安全的日志 notification。
    assert len(client.lines) == client.next_id + 1
    assert SECRET not in "".join(client.lines) + client.stderr
    assert "Traceback" not in client.stderr


@pytest.mark.parametrize("invalid", ["unicode", "nan", "inf", "negative_inf", "oversized"])
def test_invalid_output_unicode_and_nonfinite_json_are_safe(store: Store, invalid: str) -> None:
    code = f"""
import sys
from knowledge.mcp.server import main
from knowledge.mcp.service import McpReadOnlyService
original = McpReadOnlyService.search
def invalid_output(self, query):
    result = original(self, query)
    if query.query == "quota":
        hit = result.hits[0]
        value = {invalid!r}
        if value == "unicode":
            hit = hit.model_copy(update={{"text": {SECRET!r} + "\\ud800"}})
        elif value == "oversized":
            hit = hit.model_copy(update={{"text": "界" * (2 * 1024 * 1024)}})
        else:
            number = {{"nan": float("nan"), "inf": float("inf"),
                       "negative_inf": -float("inf")}}[value]
            hit = hit.model_copy(update={{"score": number}})
        return result.model_copy(update={{"hits": (hit,)}})
    return result
McpReadOnlyService.search = invalid_output
raise SystemExit(main(["--database", sys.argv[1]]))
"""
    before = _fingerprint(store.path)
    with _session(store.path, code=code) as client:
        client.initialize()
        if invalid == "oversized":
            _assert_safe_error(
                client.call("search", {"query": "quota"}), "mcp_response_too_large", 413
            )
        else:
            _assert_safe_error(client.call("search", {"query": "quota"}), "mcp_internal_error", 500)
        _payload(client.call("get_evidence", {"unit_id": store.old_unit}))
    client.assert_clean()
    assert SECRET not in client.stderr and str(store.path) not in client.stderr
    assert _fingerprint(store.path) == before


@pytest.mark.parametrize("fragment", ["a", "界", '"\\\n'])
def test_complete_response_limit_counts_utf8_escaping_and_structured_content(
    store: Store, fragment: str
) -> None:
    code = f"""
import hashlib
import json
import sys
from mcp import types
from knowledge.mcp.server import main, MAX_TOOL_RESPONSE_BYTES
from knowledge.mcp.service import McpReadOnlyService
original = McpReadOnlyService.get_evidence
fragment = {fragment!r}
def sized(self, query):
    evidence = original(self, query)
    def candidate(count):
        text = fragment * count
        dto = type(evidence).model_validate({{**evidence.model_dump(), "text": text,
              "end_char": evidence.start_char + len(text),
              "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()}})
        payload = dto.model_dump(mode="json")
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        response = types.CallToolResult(content=[types.TextContent(type="text", text=encoded)],
                                        isError=False, structuredContent=payload)
        size = len(response.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"))
        return dto, size
    low, high = 1, MAX_TOOL_RESPONSE_BYTES
    while low < high:
        middle = (low + high + 1) // 2
        if candidate(middle)[1] <= MAX_TOOL_RESPONSE_BYTES:
            low = middle
        else:
            high = middle - 1
    count = low if str(query.unit_id) == {store.old_unit!r} else low + 1
    return candidate(count)[0]
McpReadOnlyService.get_evidence = sized
raise SystemExit(main(["--database", sys.argv[1]]))
"""
    # 获取第二个真实 unit，用相邻长度的完整、有效 DTO 验证上限两侧。
    with sqlite3.connect(store.path) as connection:
        other_unit = str(
            connection.execute(
                "SELECT id FROM knowledge_units WHERE id != ? LIMIT 1",
                (store.old_unit.replace("-", ""),),
            ).fetchone()[0]
        )
    before = _fingerprint(store.path)
    with _session(store.path, code=code) as client:
        client.initialize()
        result = client.call("get_evidence", {"unit_id": store.old_unit})
        payload = _payload(result)
        wire = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        assert len(wire) <= 2 * 1024 * 1024
        assert len(wire) > 2 * 1024 * 1024 - 100
        text = payload["text"]
        assert text == fragment * (len(text) // len(fragment))
        assert payload["end_char"] - payload["start_char"] == len(text)
        assert payload["content_hash"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
        _assert_safe_error(
            client.call("get_evidence", {"unit_id": other_unit}), "mcp_response_too_large", 413
        )
        _payload(client.call("search", {"query": "quota"}))
    client.assert_clean()
    assert SECRET not in client.stderr and _fingerprint(store.path) == before


def test_official_sdk_client_validates_all_five_outputs_over_stdio(store: Store) -> None:
    _require_mcp()
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(
        command=sys.executable,
        args=_command("module", store.path)[1:],
        env=_environment(),
    )
    before = _fingerprint(store.path)

    async def exercise() -> None:
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == TOOLS
            requests = {
                "search": {"query": "quota"},
                "build_context": {"query": "quota"},
                "get_evidence": {"unit_id": store.old_unit},
                "get_lineage": {"lineage_id": store.lineage_id},
                "compare_documents": {
                    "old_document_id": store.old_id,
                    "new_document_id": store.new_id,
                },
            }
            for name, arguments in requests.items():
                result = await session.call_tool(name, arguments)
                _payload(result.model_dump(by_alias=True, exclude_none=True))

    anyio.run(exercise)
    assert _fingerprint(store.path) == before
