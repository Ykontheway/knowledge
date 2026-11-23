"""隔离发行 MCP smoke：合成 fixture 准备可写，真实 stdio 会话全程只读。

仅输出固定 schema 的安全汇总；不接收业务数据库、SQL 或网络 transport 参数。
可从 checkout 外用 venv Python -I 执行，无 pytest、源码路径或相邻脚本依赖。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import queue
import re
import site
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BASE_CHECKS = (
    "installed_core_identity",
    "no_optional_sdk",
    "lazy_root_cli_help",
    "console_missing_extra_safe",
    "cli_missing_extra_safe",
    "missing_database_not_created",
)
EXTRA_CHECKS = (
    "installed_mcp_extra",
    "no_unrelated_extras",
    "console_cli_module_stdio",
    "initialize_server_metadata",
    "list_all_five_tools",
    "input_schema_limits",
    "call_all_five_tools",
    "exact_historical_evidence",
    "context_and_page_limits",
    "output_metadata_allowlist",
    "invalid_arguments_safe",
    "stdout_jsonrpc_only",
    "stderr_sanitized",
    "database_hash_and_files_unchanged",
    "shutdown_eof",
)
TOOLS = ("search", "build_context", "get_evidence", "get_lineage", "compare_documents")
SECRET = "synthetic_mcp_private_metadata_never_echo"
OLD = "# Rules\nKeep exact historical evidence.\n\n# Quota\nquota is 10.\n"
NEW = "# Rules\nKeep exact historical evidence.\n\n# Quota\nquota is 20.\n\n# Extra\nNew rule.\n"
FORBIDDEN_KEYS = {"uri", "locator", "metadata", "metadata_json", "raw", "sql", "dsn"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def environment() -> dict[str, str]:
    result = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
        result.pop(name, None)
    for name in tuple(result):
        if name.startswith("KNOWLEDGE_"):
            result.pop(name)
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result["PYTHONNOUSERSITE"] = "1"
    return result


def is_installed(path: Path) -> bool:
    resolved = path.resolve()
    return resolved.is_relative_to(Path(sys.prefix).resolve()) and any(
        resolved.is_relative_to(Path(directory).resolve()) for directory in site.getsitepackages()
    )


def console(name: str) -> str:
    suffix = ".exe" if os.name == "nt" else ""
    path = Path(sys.executable).parent / f"{name}{suffix}"
    require(path.is_file(), "installed console missing")
    return str(path)


def verify_identity(expected_version: str, mode: str) -> str | None:
    import konwledge
    import konwledge.cli
    import konwledge.mcp

    require(konwledge.__version__ == expected_version, "installed version mismatch")
    require(importlib.metadata.version("konwledge") == expected_version, "metadata mismatch")
    for module in (konwledge, konwledge.cli, konwledge.mcp):
        require(
            module.__file__ is not None and is_installed(Path(module.__file__)), "not installed"
        )
    require("mcp" not in sys.modules, "eager SDK import")
    require("konwledge.mcp.server" not in sys.modules, "eager server import")
    for package in ("fastapi", "psycopg", "tiktoken", "lancedb", "pyarrow", "openai"):
        require(importlib.util.find_spec(package) is None, "unrelated extra installed")
    if mode == "base":
        for package in ("mcp", "httpx", "uvicorn"):
            require(importlib.util.find_spec(package) is None, "core leaked SDK")
        return None
    sdk = importlib.import_module("mcp")
    require(sdk.__file__ is not None and is_installed(Path(sdk.__file__)), "SDK not installed")
    sdk_version = importlib.metadata.version("mcp")
    require(re.fullmatch(r"\d+\.\d+\.\d+", sdk_version) is not None, "invalid SDK version")
    parts = tuple(int(part) for part in sdk_version.split("."))
    require((1, 30, 0) <= parts < (2, 0, 0), "SDK outside public range")
    return sdk_version


def fingerprint(root: Path) -> dict[str, str]:
    """清单含目录、所有文件和 SQLite sidecar；仅在内存比较，不输出路径/hash。"""
    return {
        item.relative_to(root).as_posix(): (
            hashlib.sha256(item.read_bytes()).hexdigest() if item.is_file() else "directory"
        )
        for item in root.rglob("*")
    }


def run_base(root: Path) -> dict[str, int]:
    before = fingerprint(root)
    code = """
import sys
import konwledge
import konwledge.cli
assert 'mcp' not in sys.modules
assert 'konwledge.mcp.server' not in sys.modules
for arguments in (['--version'], ['--help'], ['serve', '--help'],
                  ['mcp', '--help'], ['mcp', 'serve', '--help']):
    assert konwledge.cli.main(arguments) == 0
assert 'mcp' not in sys.modules
assert 'konwledge.mcp.server' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=root,
        env=environment(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    require(result.returncode == 0, "core help failed")
    commands = (
        [console("konwledge-mcp"), "--database", "missing.db"],
        [sys.executable, "-I", "-m", "konwledge", "mcp", "serve", "--database", "missing.db"],
    )
    for command in commands:
        result = subprocess.run(
            command,
            cwd=root,
            env=environment(),
            input="",
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        require(result.returncode == 1 and result.stdout == "", "missing extra exit/stdout unsafe")
        require("pip install 'konwledge[mcp]'" in result.stderr, "missing pip install hint")
        require(
            "Traceback" not in result.stderr and str(root) not in result.stderr,
            "missing extra stderr unsafe",
        )
    require(fingerprint(root) == before, "core created database or files")
    return {"help_commands": 5, "missing_extra_commands": len(commands)}


@dataclass(frozen=True)
class Store:
    database: Path
    old_document: str
    new_document: str
    old_unit: str
    lineage: str


def prepare_store(root: Path) -> Store:
    """只在新临时目录用核心 facade 准备两版本，注入合成敏感 metadata。"""
    from sqlalchemy import update

    from konwledge import KnowledgeLibrary
    from konwledge.storage import create_schema, create_session_factory, create_sqlite_engine
    from konwledge.storage.tables import DocumentRow, KnowledgeUnitRow, SourceRow

    database = root / "sandbox.db"
    engine = create_sqlite_engine(f"sqlite+pysqlite:///{database.as_posix()}")
    try:
        create_schema(engine)
        library = KnowledgeLibrary(create_session_factory(engine))
        source = root / "rules.md"
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
            database,
            str(old.ingestion.document.id),
            str(new.ingestion.document.id),
            str(old.units[1].id),
            str(old.units[1].lineage_id),
        )
    finally:
        engine.dispose()


@dataclass
class ProtocolClient:
    process: subprocess.Popen[str]
    responses: queue.Queue[Any] = field(default_factory=queue.Queue)
    stdout_lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)
    next_id: int = 0

    def pump_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.stdout_lines.append(line)
            try:
                self.responses.put(json.loads(line))
            except ValueError:
                self.responses.put(None)

    def pump_stderr(self) -> None:
        assert self.process.stderr is not None
        self.stderr_lines.extend(self.process.stderr)

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params})
        try:
            response = self.responses.get(timeout=30)
        except queue.Empty:
            raise AssertionError("protocol response timeout") from None
        if not isinstance(response, dict):
            raise AssertionError("non JSON stdout")
        require(
            response.get("jsonrpc") == "2.0" and response.get("id") == self.next_id,
            "protocol envelope mismatch",
        )
        require("result" in response and "error" not in response, "protocol request failed")
        body = response["result"]
        if not isinstance(body, dict):
            raise AssertionError("protocol result is not an object")
        return body

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments})


@contextmanager
def session(command: Sequence[str], root: Path) -> Iterator[ProtocolClient]:
    process = subprocess.Popen(
        list(command),
        cwd=root,
        env=environment(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    client = ProtocolClient(process)
    readers = [
        threading.Thread(target=target, daemon=True)
        for target in (client.pump_stdout, client.pump_stderr)
    ]
    for reader in readers:
        reader.start()
    try:
        yield client
        assert process.stdin is not None
        process.stdin.close()  # 正常 shutdown 只通过 EOF，不发送非标准 shutdown RPC。
        process.wait(timeout=30)
        for reader in readers:
            reader.join(timeout=5)
            require(not reader.is_alive(), "stdio reader not closed")
        require(process.returncode == 0, "EOF shutdown failed")
        require(len(client.stdout_lines) == client.next_id, "stdout contains non response output")
        output = "".join(client.stdout_lines + client.stderr_lines)
        require(
            SECRET not in output and str(root) not in output and "Traceback" not in output,
            "protocol or stderr leaked private data",
        )
        for line in client.stderr_lines:
            require(
                re.fullmatch(r"(?:DEBUG|INFO|WARNING|ERROR|CRITICAL): MCP server event\n", line)
                is not None,
                "stderr contains non sanitized output",
            )
        for line in client.stdout_lines:
            require(json.loads(line).get("jsonrpc") == "2.0", "non JSONRPC stdout")
    finally:
        if process.poll() is None:
            process.kill()  # 仅失败/超时清理，不能作为通过门禁的 shutdown。
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        for reader in readers:
            reader.join(timeout=5)


def assert_metadata_safe(value: Any) -> None:
    if isinstance(value, dict):
        require(not FORBIDDEN_KEYS.intersection(value), "output contains private metadata keys")
        for item in value.values():
            assert_metadata_safe(item)
    elif isinstance(value, list):
        for item in value:
            assert_metadata_safe(item)
    elif isinstance(value, str):
        require(SECRET not in value, "output leaked synthetic secret")


def payload(result: dict[str, Any], model: Any) -> dict[str, Any]:
    require(result.get("isError") is False, "tool call failed")
    content = result.get("content")
    if not isinstance(content, list) or len(content) != 1:
        raise AssertionError("content count mismatch")
    require(content[0].get("type") == "text", "non text content")
    value: dict[str, Any] = json.loads(content[0]["text"])
    require(isinstance(value, dict), "tool payload not object")
    assert_metadata_safe(value)
    model.model_validate(value)  # 输出白名单、exact span/hash、预算等实际 installed 模型门禁。
    return value


def verify_schemas(tools: list[dict[str, Any]]) -> None:
    expected_properties = {
        "search": {"query", "top_k", "candidate_limit", "rrf_k", "at", "source_id"},
        "build_context": {
            "query",
            "top_k",
            "candidate_limit",
            "rrf_k",
            "at",
            "source_id",
            "max_chars",
            "max_units",
        },
        "get_evidence": {"unit_id"},
        "get_lineage": {"lineage_id", "limit", "offset"},
        "compare_documents": {"old_document_id", "new_document_id", "limit", "offset"},
    }
    for tool in tools:
        schema = tool["inputSchema"]
        require(schema.get("additionalProperties") is False, "schema permits unknown fields")
        props = schema["properties"]
        require(set(props) == expected_properties[tool["name"]], "schema field set mismatch")
        for name, minimum, maximum in (
            ("top_k", 1, 100),
            ("max_chars", 0, 100_000),
            ("max_units", 1, 100),
            ("limit", 1, 100),
            ("offset", 0, 100_000),
            ("rrf_k", 1, 1000),
        ):
            if name in props:
                require(
                    props[name].get("minimum") == minimum and props[name].get("maximum") == maximum,
                    "schema bounds mismatch",
                )
        if "query" in props:
            require(
                props["query"].get("minLength") == 1 and props["query"].get("maxLength") == 4096,
                "query schema limits mismatch",
            )
        if "candidate_limit" in props:
            integer = next(
                item for item in props["candidate_limit"]["anyOf"] if item.get("type") == "integer"
            )
            require(
                integer.get("minimum") == 1 and integer.get("maximum") == 1000,
                "candidate schema limits mismatch",
            )


def exercise(client: ProtocolClient, store: Store, version: str) -> tuple[int, int]:
    from konwledge.mcp.models import (
        ContextPacket,
        DocumentDiffDTO,
        EvidenceDTO,
        LineageDTO,
        SearchDTO,
    )

    initialized = client.request(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "installed-distribution-smoke", "version": "1.0"},
        },
    )
    require(
        initialized["serverInfo"] == {"name": "konwledge", "version": version},
        "server metadata mismatch",
    )
    require("tools" in initialized["capabilities"], "tools capability missing")
    require(initialized.get("protocolVersion") == "2024-11-05", "protocol version mismatch")
    client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    tools = client.request("tools/list", {})["tools"]
    require(len(tools) == 5 and {tool["name"] for tool in tools} == set(TOOLS), "tool set mismatch")
    verify_schemas(tools)
    search = payload(client.call("search", {"query": "quota", "top_k": 1}), SearchDTO)
    require(
        search["mode"] == "lexical" and search["include_stale"] is False,
        "search mode/stale boundary changed",
    )
    require(len(search["hits"]) == 1 and "20" in search["hits"][0]["text"], "active hit mismatch")
    context = payload(
        client.call("build_context", {"query": "quota", "max_units": 1}), ContextPacket
    )
    require(
        len(context["blocks"]) == 1 and context["blocks"][0]["label"] == "[1]",
        "context evidence mismatch",
    )
    constrained = payload(
        client.call("build_context", {"query": "quota", "max_chars": 0}), ContextPacket
    )
    require(
        constrained["blocks"] == [] and constrained["used_chars"] == 0, "context budget ignored"
    )
    evidence = payload(client.call("get_evidence", {"unit_id": store.old_unit}), EvidenceDTO)
    require(
        evidence["document_id"] == store.old_document and "10" in evidence["text"],
        "historical evidence mismatch",
    )
    require(
        evidence["text"] == OLD[evidence["start_char"] : evidence["end_char"]],
        "historical span is not exact",
    )
    require(
        evidence["document_checksum"] == hashlib.sha256(OLD.encode()).hexdigest(),
        "historical document checksum mismatch",
    )
    lineage = payload(
        client.call("get_lineage", {"lineage_id": store.lineage, "limit": 1}), LineageDTO
    )
    require(
        lineage["versions"]["total"] == 2 and len(lineage["versions"]["items"]) == 1,
        "lineage pagination mismatch",
    )
    diff_args = {
        "old_document_id": store.old_document,
        "new_document_id": store.new_document,
        "limit": 1,
    }
    diff = payload(client.call("compare_documents", diff_args), DocumentDiffDTO)
    require(
        diff["counts"] == {"added": 1, "modified": 1, "moved": 0, "removed": 0, "unchanged": 1},
        "diff counts mismatch",
    )
    require(len(diff["changes"]["items"]) == 1, "diff pagination ignored")
    invalid: list[tuple[str, dict[str, Any]]] = [
        ("search", {"query": "quota", "raw": SECRET}),
        ("search", {"query": "quota", "mode": "vector"}),
        ("search", {"query": "quota", "include_stale": True}),
        ("search", {"query": "quota", "top_k": True}),
        ("search", {"query": "quota", "top_k": 101}),
        ("search", {"query": "quota", "candidate_limit": 1}),
        ("search", {"query": "x" * 4097}),
        ("build_context", {"query": "quota", "max_chars": -1}),
        ("build_context", {"query": "quota", "max_units": 101}),
        ("get_evidence", {"unit_id": str(store.database)}),
        ("get_lineage", {"lineage_id": store.lineage, "limit": 101}),
        ("compare_documents", {**diff_args, "offset": 100_001}),
    ]
    for name, arguments in invalid:
        result = client.call(name, arguments)
        require(result.get("isError") is True, "invalid input accepted")
        require(
            json.loads(result["content"][0]["text"])
            == {"error": {"code": "mcp_invalid_arguments", "status": 400}},
            "unsafe input error",
        )
    unknown = client.call(SECRET, {})
    require(
        unknown.get("isError") is True
        and json.loads(unknown["content"][0]["text"])
        == {"error": {"code": "mcp_tool_not_found", "status": 404}},
        "unsafe unknown tool error",
    )
    return 6, len(invalid) + 1


def run_extra(root: Path, version: str) -> dict[str, int]:
    store = prepare_store(root)
    before = fingerprint(root)  # 写准备完成并 dispose 后才开始 MCP 零写门禁。
    commands = (
        [console("konwledge-mcp"), "--database", str(store.database)],
        [
            sys.executable,
            "-I",
            "-m",
            "konwledge",
            "mcp",
            "serve",
            "--database",
            str(store.database),
        ],
        [sys.executable, "-I", "-m", "konwledge.mcp.server", "--database", str(store.database)],
    )
    successes = rejects = responses = 0
    for command in commands:
        with session(command, root) as client:
            success, reject = exercise(client, store, version)
            successes += success
            rejects += reject
            responses += client.next_id
        require(fingerprint(root) == before, "MCP changed database or file collection")
    return {
        "tools": len(TOOLS),
        "sessions": len(commands),
        "successful_calls": successes,
        "rejected_calls": rejects,
        "protocol_responses": responses,
        "unchanged_files": sum(item.is_file() for item in root.rglob("*")),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--mode", choices=("base", "extra"), required=True)
    args = parser.parse_args(argv)
    try:
        require(
            re.fullmatch(r"\d+\.\d+\.\d+", args.expected_version) is not None,
            "invalid expected version",
        )
        # 捕获 fixture/应用意外 print；stdout 仅一次安全 summary。
        with redirect_stdout(sys.stderr):
            sdk_version = verify_identity(args.expected_version, args.mode)
            with tempfile.TemporaryDirectory(prefix="konwledge-mcp-installed-") as temporary:
                root = Path(temporary)
                counts = (
                    run_base(root)
                    if args.mode == "base"
                    else run_extra(root, args.expected_version)
                )
    except Exception:
        # 不反射异常、SQL、输入、原 secret 或绝对路径。
        print("installed MCP smoke failed", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "version": args.expected_version,
                "passed": True,
                "mode": args.mode,
                "sdk_version": sdk_version,
                "pydantic_version": importlib.metadata.version("pydantic"),
                "checks": list(BASE_CHECKS if args.mode == "base" else EXTRA_CHECKS),
                "counts": counts,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
