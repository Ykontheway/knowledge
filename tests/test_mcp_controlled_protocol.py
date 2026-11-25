"""B6 协议边界：实际 SDK stdio、显式绑定、带外 TTY 批准与未知结果恢复。"""

from __future__ import annotations

import io
import json
import logging
import os
import pty
import select
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr
from pathlib import Path
from time import monotonic
from typing import Any
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from knowledge.mcp.controlled import (
    CONTROLLED_TOOL_ANNOTATIONS,
    CONTROLLED_TOOL_INPUTS,
    CONTROLLED_TOOL_OUTPUTS,
    McpControlledError,
    McpControlledService,
    open_controlled_runtime,
)
from knowledge.mcp.server import TOOL_INPUTS, TOOL_OUTPUTS, create_server
from knowledge.mcp.service import McpReadOnlyService
from test_mcp_controlled_service import ACTOR, DemoSeed, counts, make_demo
from test_mcp_protocol import (
    SECRET,
    TOOLS,
    ProtocolClient,
    _assert_safe_error,
    _environment,
    _payload,
    _require_mcp,
    _run_python,
    _session,
)

CONTROLLED = {
    "get_mutation_session",
    "get_mutation_document",
    "preview_document_update",
    "apply_document_update",
    "get_mutation_command",
}
UPDATED = "# Demo\n\nhello changed: 中文正文。\n"


@pytest.fixture
def seed(tmp_path: Path) -> DemoSeed:
    # 已读取并确认 owner helper 的 API；仅创建 tmp 下隔离的私有 demo scope。
    return make_demo(tmp_path)


def _options(seed: DemoSeed) -> list[str]:
    return [
        "--database",
        str(seed.database),
        "--mutation-manifest",
        str(seed.manifest),
        "--actor",
        ACTOR,
        "--demo-root",
        str(seed.root),
    ]


@contextmanager
def _controlled(
    seed: DemoSeed, *, entry: str = "module", patch: str = ""
) -> Iterator[ProtocolClient]:
    target = "knowledge.cli" if entry == "cli" else "knowledge.mcp.server"
    args = ["mcp", "serve"] if entry == "cli" else []
    code = f"""
{patch}
from {target} import main
raise SystemExit(main({[*args, "--controlled", *_options(seed)]!r}))
"""
    with _session(seed.database, code=code) as client:
        yield client


def _preview(client: ProtocolClient, text: str = UPDATED) -> dict[str, Any]:
    source = _payload(client.call("get_mutation_session", {}))["sources"][0]
    return _payload(
        client.call(
            "preview_document_update",
            {
                "source_id": source["source_id"],
                "document_id": source["document_id"],
                "expected_checksum": source["checksum"],
                "text": text,
            },
        )
    )


def _synthetic_grant(seed: DemoSeed, value: dict[str, Any]) -> dict[str, Any]:
    # 仅测试用 operator API：不暴露为 MCP 工具，也不授权真实业务库。
    key = uuid4()
    with open_controlled_runtime(
        seed.database, seed.manifest, ACTOR, demo_root=seed.root
    ) as runtime:
        review = runtime.service.review_approval(UUID(value["preview_id"]), key)
        grant = runtime.service.issue_approval(
            UUID(value["preview_id"]), key, approval_phrase=review.approval_phrase
        )
    return {
        "preview_id": value["preview_id"],
        "confirmation_token": value["confirmation_token"],
        "idempotency_key": str(key),
        "approval_token": grant.approval_token,
    }


def _assert_unknown(result: dict[str, Any]) -> None:
    assert result["isError"] is True
    assert "structuredContent" not in result
    payload = json.loads(result["content"][0]["text"])
    assert payload["error"] == {"code": "mcp_mutation_outcome_unknown", "status": 500}
    assert "get_mutation_command" in payload["guidance"]
    assert "idempotency_key" in payload["guidance"]
    assert "不要自动重试" in payload["guidance"]
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("entry", ["module", "cli"])
def test_ten_tools_schemas_annotations_exact_document_preview_and_safe_errors(
    seed: DemoSeed, entry: str
) -> None:
    _require_mcp()
    from jsonschema import Draft202012Validator
    from mcp import types

    with sqlite3.connect(seed.database) as db:
        db.execute("UPDATE sources SET uri=?, metadata=?", (SECRET, json.dumps({"raw": SECRET})))
        db.execute(
            "UPDATE documents SET locator=?, metadata=?", (SECRET, json.dumps({"raw": SECRET}))
        )
    before = counts(seed)
    with _controlled(seed, entry=entry) as client:
        capabilities = client.initialize()["result"]["capabilities"]
        assert "resources" not in capabilities and "prompts" not in capabilities
        tools = client.request("tools/list")["result"]["tools"]
        assert len(tools) == 10 and {item["name"] for item in tools} == TOOLS | CONTROLLED
        schemas = {}
        for item in tools:
            name = item["name"]
            dto = types.Tool.model_validate(item)
            assert isinstance(dto.annotations, types.ToolAnnotations)
            assert item["inputSchema"]["additionalProperties"] is False
            expected = (CONTROLLED_TOOL_INPUTS if name in CONTROLLED else TOOL_INPUTS)[name][0]
            assert item["inputSchema"] == expected.model_json_schema()
            output = (CONTROLLED_TOOL_OUTPUTS if name in CONTROLLED else TOOL_OUTPUTS)[name]
            assert item["outputSchema"] == output.model_json_schema(mode="serialization")
            Draft202012Validator.check_schema(item["outputSchema"])
            for definition in [
                item["outputSchema"],
                *item["outputSchema"].get("$defs", {}).values(),
            ]:
                if definition.get("type") == "object":
                    assert definition["additionalProperties"] is False
            hints = CONTROLLED_TOOL_ANNOTATIONS.get(
                name,
                {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            )
            assert item["annotations"] == hints
            assert "_meta" not in item
            schemas[name] = item["outputSchema"]
        scope = _payload(client.call("get_mutation_session", {}))
        source = scope["sources"][0]
        assert scope["actor_id"] == ACTOR and scope["scope_id"] == seed.manifest.parent.name
        assert source["label"] == "演示文档"
        document = _payload(
            client.call("get_mutation_document", {"document_id": source["document_id"]})
        )
        assert document["text"] == "# Demo\n\nhello"
        assert document["checksum"] == source["checksum"]
        assert set(document) == {
            "scope_id",
            "source_id",
            "document_id",
            "checksum",
            "content_type",
            "text",
        }
        value = _preview(client)
        assert value["changed"] is True and value["expected_checksum"] == source["checksum"]
        assert value["diff"][0]["old_text"] == "# Demo\n\nhello"
        assert value["diff"][0]["new_text"] == UPDATED
        assert value["confirmation_token"]  # 预览 capability 是成功协议的一部分，允许输出。
        for name, payload in {
            "get_mutation_session": scope,
            "get_mutation_document": document,
            "preview_document_update": value,
        }.items():
            Draft202012Validator(schemas[name]).validate(payload)
        for name in ("issue_approval", "review_approval", "delete_document", "import_path", SECRET):
            _assert_safe_error(client.call(name, {"token": SECRET}), "mcp_tool_not_found", 404)
        denied = {
            "preview_id": value["preview_id"],
            "confirmation_token": value["confirmation_token"],
            "idempotency_key": str(uuid4()),
            "approval_token": SECRET,
        }
        _assert_safe_error(
            client.call("apply_document_update", denied), "mcp_approval_required", 403
        )
        _assert_safe_error(
            client.call("apply_document_update", {**denied, "confirmed": True}),
            "mcp_invalid_arguments",
            400,
        )
        _assert_safe_error(
            client.call(
                "apply_document_update", {k: v for k, v in denied.items() if k != "approval_token"}
            ),
            "mcp_invalid_arguments",
            400,
        )
        _assert_safe_error(
            client.call("get_mutation_document", {"document_id": str(uuid4())}),
            "mcp_document_not_found",
            404,
        )
        for name in CONTROLLED:
            for field in ("actor", "scope_id", "sql", "path", "confirmed", "raw"):
                _assert_safe_error(client.call(name, {field: SECRET}), "mcp_invalid_arguments", 400)
    client.assert_clean()
    assert SECRET not in client.stderr and value["confirmation_token"] not in client.stderr
    assert counts(seed) == before
    assert set(TOOL_INPUTS) == TOOLS and set(TOOL_OUTPUTS) == TOOLS


def _pty_approval(seed: DemoSeed, value: dict[str, Any], key: str) -> dict[str, Any]:
    args = [
        "mcp",
        "approve",
        *_options(seed),
        "--preview-id",
        value["preview_id"],
        "--idempotency-key",
        key,
    ]
    # 批准入口即使没有 MCP SDK 也可工作；stdin/stderr 必须是真正 PTY。
    code = f"""
import sys
sys.modules['mcp'] = None
from knowledge.cli import main
raise SystemExit(main({args!r}))
"""
    master, slave = pty.openpty()
    child = subprocess.Popen(
        [sys.executable, "-c", code],
        env=_environment(),
        stdin=slave,
        stderr=slave,
        stdout=subprocess.PIPE,
        text=True,
    )
    os.close(slave)
    transcript = b""
    try:
        deadline = monotonic() + 20
        while b"Type the exact approval_phrase" not in transcript:
            assert monotonic() < deadline and child.poll() is None, transcript
            if select.select([master], [], [], 0.1)[0]:
                transcript += os.read(master, 65536)
        review = json.loads(transcript.splitlines()[0])
        assert review["preview_id"] == value["preview_id"] and review["idempotency_key"] == key
        assert value["confirmation_token"].encode() not in transcript
        os.write(master, (review["approval_phrase"] + "\n").encode())
        stdout, _ = child.communicate(timeout=20)
        while select.select([master], [], [], 0)[0]:
            try:
                data = os.read(master, 65536)
            except OSError:
                break
            if not data:
                break
            transcript += data
        assert child.returncode == 0, transcript
        target = Path(json.loads(stdout)["approval_file"])
        assert target.parent == seed.manifest.parent / "mcp-approvals"
        assert target.stat().st_mode & 0o777 == 0o600
        grant: dict[str, Any] = json.loads(target.read_text())
        assert grant["approval_token"] not in stdout + transcript.decode()
        assert value["confirmation_token"] not in stdout + transcript.decode()
        assert "hello" not in stdout
        return grant
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        if child.stdout is not None:
            child.stdout.close()
        os.close(master)


def test_tty_cli_approval_apply_replay_get_and_restart_durable(seed: DemoSeed) -> None:
    before = counts(seed)
    with _controlled(seed) as client:
        client.initialize()
        value = _preview(client)
        key = str(uuid4())
        grant = _pty_approval(seed, value, key)
        assert counts(seed) == before  # 批准不提交知识/revision/outbox。
        arguments = {
            "preview_id": value["preview_id"],
            "confirmation_token": value["confirmation_token"],
            "idempotency_key": key,
            "approval_token": grant["approval_token"],
        }
        command = _payload(client.call("apply_document_update", arguments))
        assert command["committed"] is True and command["changed"] is True
        assert command["command_id"] == key and command["evaluation_status"] == "passed"
        after = counts(seed)
        assert after[0] == before[0] + 1 and after[3] == before[3] + 1
        assert _payload(client.call("apply_document_update", arguments)) == command
        assert counts(seed) == after
        assert _payload(client.call("get_mutation_command", {"command_id": key})) == command
        body = _payload(
            client.call("get_mutation_document", {"document_id": command["document_id"]})
        )
        assert body["text"] == UPDATED
    client.assert_clean()
    with _controlled(seed, entry="cli") as restarted:
        restarted.initialize()
        assert _payload(restarted.call("get_mutation_command", {"command_id": key})) == command
        assert _payload(restarted.call("apply_document_update", arguments)) == command
    restarted.assert_clean()
    assert counts(seed) == after
    for token in (value["confirmation_token"], grant["approval_token"]):
        assert token not in client.stderr + restarted.stderr
    assert "approval_token" not in json.dumps(command)


def test_grant_survives_restart_before_apply(seed: DemoSeed) -> None:
    with _controlled(seed) as client:
        client.initialize()
        args = _synthetic_grant(seed, _preview(client))
    client.assert_clean()
    with _controlled(seed) as restarted:
        restarted.initialize()
        command = _payload(restarted.call("apply_document_update", args))
        assert command["committed"] is True
    restarted.assert_clean()


def test_failed_quality_is_successful_committed_result(seed: DemoSeed) -> None:
    with _controlled(seed) as client:
        client.initialize()
        args = _synthetic_grant(seed, _preview(client, "# Different\n\nNothing matches the query."))
        command = _payload(client.call("apply_document_update", args))
        assert command["committed"] is True and command["evaluation_status"] == "failed"
        assert (
            _payload(client.call("get_mutation_command", {"command_id": args["idempotency_key"]}))
            == command
        )
    client.assert_clean()


@pytest.mark.parametrize("failure", ["exception", "unicode", "nan", "oversize"])
def test_postcommit_failure_unknown_get_recovers_without_apply_retry(
    seed: DemoSeed, failure: str
) -> None:
    patch = f"""
from knowledge.mcp.controlled import McpControlledService
original = McpControlledService.apply_document_update
def fail_after_commit(self, query):
    result = original(self, query)
    if {failure!r} == 'exception':
        raise RuntimeError({SECRET!r})
    if {failure!r} == 'unicode':
        return result.model_copy(update={{'actor_id': {SECRET!r} + '\\ud800'}})
    if {failure!r} == 'nan':
        return result.model_copy(update={{'actor_id': float('nan')}})
    return result.model_copy(update={{'actor_id': '界' * (2 * 1024 * 1024)}})
McpControlledService.apply_document_update = fail_after_commit
"""
    with _controlled(seed, patch=patch) as client:
        client.initialize()
        args = _synthetic_grant(seed, _preview(client))
        _assert_unknown(client.call("apply_document_update", args))
        command = _payload(
            client.call("get_mutation_command", {"command_id": args["idempotency_key"]})
        )
        assert command["committed"] is True
    client.assert_clean()
    with _controlled(seed) as restarted:
        restarted.initialize()
        assert (
            _payload(
                restarted.call("get_mutation_command", {"command_id": args["idempotency_key"]})
            )
            == command
        )
    restarted.assert_clean()
    assert counts(seed)[3] == 1
    assert SECRET not in client.stderr


def test_transport_dropped_after_commit_recovers_original_command_key(seed: DemoSeed) -> None:
    patch = """
import os
from knowledge.mcp.controlled import McpControlledService
original = McpControlledService.apply_document_update
def drop_after_commit(self, query):
    original(self, query)
    os._exit(0)  # 故障注入：持久提交后、SDK 发送响应之前断开进程。
McpControlledService.apply_document_update = drop_after_commit
"""
    with _controlled(seed, patch=patch) as client:
        client.initialize()
        args = _synthetic_grant(seed, _preview(client))
        client.next_id += 1
        client.send(
            {
                "jsonrpc": "2.0",
                "id": client.next_id,
                "method": "tools/call",
                "params": {"name": "apply_document_update", "arguments": args},
            }
        )
        client.process.wait(timeout=15)
    assert len(client.lines) == client.next_id - 1
    assert counts(seed)[3] == 1
    with _controlled(seed) as restarted:
        restarted.initialize()
        command = _payload(
            restarted.call("get_mutation_command", {"command_id": args["idempotency_key"]})
        )
        assert command["committed"] is True
    restarted.assert_clean()


def _handler_call(server: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    import anyio
    from mcp import types

    async def call() -> dict[str, Any]:
        request = types.CallToolRequest.model_validate(
            {
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        result = await server.request_handlers[types.CallToolRequest](request)
        response: dict[str, Any] = result.model_dump(by_alias=True, exclude_none=True)
        return response

    return anyio.run(call)


@pytest.mark.parametrize("text", ["🙂" * 16385, "\ud800", True, float("nan")])
def test_text_guard_and_invalid_json_before_service(text: Any) -> None:
    _require_mcp()
    ro, controlled = Mock(spec=McpReadOnlyService), Mock(spec=McpControlledService)
    server = create_server(ro, controlled_service=controlled)
    _assert_safe_error(
        _handler_call(
            server,
            "preview_document_update",
            {
                "source_id": str(uuid4()),
                "document_id": str(uuid4()),
                "expected_checksum": "a" * 64,
                "text": text,
            },
        ),
        "mcp_invalid_arguments",
        400,
    )
    controlled.preview_document_update.assert_not_called()
    ro.assert_not_called()


@pytest.mark.parametrize("fragment", ["a", "界", '"\\\n'])
def test_exact_128k_input_json_budget_before_any_mutation(fragment: str) -> None:
    _require_mcp()
    from knowledge.mcp.server import MAX_WRITE_INPUT_BYTES

    ro, controlled = Mock(spec=McpReadOnlyService), Mock(spec=McpControlledService)
    controlled.preview_document_update.side_effect = McpControlledError(
        "mcp_checksum_conflict", 409
    )
    server = create_server(ro, controlled_service=controlled)
    base = {
        "source_id": str(uuid4()),
        "document_id": str(uuid4()),
        "expected_checksum": "a" * 64,
        "text": "",
        "padding": "",
    }
    low, high = 0, MAX_WRITE_INPUT_BYTES
    while low < high:
        middle = (low + high + 1) // 2
        size = len(
            json.dumps(
                {**base, "padding": fragment * middle},
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if size <= MAX_WRITE_INPUT_BYTES:
            low = middle
        else:
            high = middle - 1
    # extra-field 错误证明 budget 内走 schema；相邻长度越界先拒绝，service 都未调用。
    _assert_safe_error(
        _handler_call(server, "preview_document_update", {**base, "padding": fragment * low}),
        "mcp_invalid_arguments",
        400,
    )
    _assert_safe_error(
        _handler_call(server, "preview_document_update", {**base, "padding": fragment * (low + 1)}),
        "mcp_input_too_large",
        413,
    )
    controlled.preview_document_update.assert_not_called()
    # apply 也必须先预算，哪怕超大参数并不符合 schema。
    _assert_safe_error(
        _handler_call(
            server, "apply_document_update", {"approval_token": "界" * MAX_WRITE_INPUT_BYTES}
        ),
        "mcp_input_too_large",
        413,
    )
    controlled.apply_document_update.assert_not_called()


def test_server_local_binding_readonly_404_and_no_global_pollution() -> None:
    _require_mcp()
    ro, controlled = Mock(spec=McpReadOnlyService), Mock(spec=McpControlledService)
    create_server(ro, controlled_service=controlled)
    readonly = create_server(ro)
    for name in CONTROLLED:
        _assert_safe_error(
            _handler_call(readonly, name, {"secret": SECRET}), "mcp_tool_not_found", 404
        )
    assert set(TOOL_INPUTS) == TOOLS and set(TOOL_OUTPUTS) == TOOLS
    for name in CONTROLLED:
        getattr(controlled, name).assert_not_called()
        assert not hasattr(ro, name)


@pytest.mark.parametrize("name", ["get_mutation_session", "apply_document_update"])
@pytest.mark.parametrize("pollution", ["code", "status", "generic"])
def test_polluted_errors_safe_and_apply_never_retried(name: str, pollution: str) -> None:
    _require_mcp()
    ro, controlled = Mock(spec=McpReadOnlyService), Mock(spec=McpControlledService)
    if pollution == "generic":
        error: Exception = RuntimeError(SECRET)
    else:
        error = McpControlledError("mcp_approval_required", 403)
        if pollution == "code":
            error.code = SECRET
        else:
            error.status = 599
    getattr(controlled, name).side_effect = error
    server = create_server(ro, controlled_service=controlled)
    args = (
        {}
        if name.startswith("get_")
        else {
            "preview_id": str(uuid4()),
            "confirmation_token": SECRET,
            "idempotency_key": str(uuid4()),
            "approval_token": SECRET,
        }
    )
    result = _handler_call(server, name, args)
    if name == "apply_document_update":
        _assert_unknown(result)
    else:
        _assert_safe_error(result, "mcp_internal_error", 500)
    getattr(controlled, name).assert_called_once()


def test_safe_precommit_error_and_logging_never_reflect_tokens(seed: DemoSeed) -> None:
    patch = """
import logging
from knowledge.mcp.controlled import McpControlledService, McpControlledError
def invalid(self, query):
    logging.getLogger('controlled-test').error('token %s', query.approval_token)
    raise McpControlledError('mcp_approval_expired', 410)
McpControlledService.apply_document_update = invalid
"""
    before = counts(seed)
    with _controlled(seed, patch=patch) as client:
        client.initialize()
        args = {
            "preview_id": str(uuid4()),
            "idempotency_key": str(uuid4()),
            "confirmation_token": SECRET,
            "approval_token": SECRET,
        }
        _assert_safe_error(client.call("apply_document_update", args), "mcp_approval_expired", 410)
    client.assert_clean()
    assert "ERROR: MCP server event" in client.stderr and SECRET not in client.stderr
    assert SECRET not in "".join(client.lines) and counts(seed) == before


@pytest.mark.parametrize(
    "options",
    [
        {"mutation_manifest": Path("private")},
        {"actor": SECRET},
        {"demo_root": Path("private")},
        {"controlled": True},
        {"controlled": True, "mutation_manifest": Path("private")},
        *[
            {"controlled": True, "mutation_manifest": Path("private"), "actor": actor}
            for actor in (
                "",
                "a" * 81,
                "汉字",
                "a\nsecret",
                "a\x1b[31m",
                "a b",
                "a/../b",
                "a\x00",
                "a\u202eb",
            )
        ],
    ],
)
def test_invalid_startup_before_database_or_controlled_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, options: dict[str, Any]
) -> None:
    _require_mcp()
    from knowledge.mcp import server

    opened = Mock(side_effect=AssertionError("must not open DB"))
    monkeypatch.setattr(server, "create_engine", opened)
    with pytest.raises(ValueError, match="mcp_startup_invalid"):
        server.run_server(tmp_path / "absent.db", **options)
    opened.assert_not_called()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("entry", ["module", "cli"])
def test_no_sdk_controlled_options_no_core_import_or_database(tmp_path: Path, entry: str) -> None:
    target = "knowledge.cli" if entry == "cli" else "knowledge.mcp.server"
    args = ["mcp", "serve"] if entry == "cli" else []
    options = [
        *args,
        "--controlled",
        "--database",
        SECRET,
        "--mutation-manifest",
        SECRET,
        "--actor",
        SECRET,
    ]
    code = f"""
import sys
sys.modules['mcp'] = None
from {target} import main
assert main({options!r}) == 1
assert not any(name.startswith('knowledge.mcp.controlled') for name in sys.modules)
"""
    result = _run_python(code, tmp_path)
    assert result.returncode == 0 and result.stdout == ""
    assert "pip install 'knowledge-ykforward[mcp]'" in result.stderr
    assert SECRET not in result.stderr and list(tmp_path.iterdir()) == []


def test_readonly_run_blocks_controlled_import_even_with_environment_keys(seed: DemoSeed) -> None:
    code = f"""
import os
import sys
os.environ['KNOWLEDGE_MUTATION_KEY'] = {SECRET!r}
os.environ['KNOWLEDGE_MUTATION_ACTOR'] = {ACTOR!r}
from knowledge.mcp.server import main
assert not any(name.startswith('knowledge.mcp.controlled') for name in sys.modules)
sys.modules['knowledge.mcp.controlled'] = None
sys.modules['knowledge.mutations.service'] = None
code = main(['--database', sys.argv[1]])
assert sys.modules['knowledge.mcp.controlled'] is None
raise SystemExit(code)
"""
    before = seed.database.read_bytes()
    with _session(seed.database, code=code) as client:
        client.initialize()
        assert {item["name"] for item in client.request("tools/list")["result"]["tools"]} == TOOLS
        for name in CONTROLLED:
            _assert_safe_error(client.call(name, {}), "mcp_tool_not_found", 404)
    client.assert_clean()
    assert seed.database.read_bytes() == before
    with sqlite3.connect(seed.database) as db:
        assert (
            db.execute("SELECT name FROM sqlite_master WHERE name='mcp_approvals'").fetchone()
            is None
        )


@pytest.mark.parametrize("args", [["mcp", "approve", "--help"], ["mcp", "serve", "--help"]])
def test_cli_help_lazy_without_core_or_sdk(tmp_path: Path, args: list[str]) -> None:
    result = _run_python(
        f"""
import sys
sys.modules['mcp'] = None
from knowledge.cli import main
assert main({args!r}) == 0
assert 'knowledge.mcp.server' not in sys.modules
assert 'knowledge.mcp.approval_cli' not in sys.modules
assert not any(name.startswith('knowledge.mcp.controlled') for name in sys.modules)
""",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "--demo-root" in result.stdout and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("flag", [None, "--yes", "--confirmed"])
def test_cli_approve_non_tty_or_auto_confirm_denied_without_storage(
    seed: DemoSeed, flag: str | None
) -> None:
    args = [
        "mcp",
        "approve",
        *_options(seed),
        "--preview-id",
        str(uuid4()),
        "--idempotency-key",
        str(uuid4()),
    ]
    if flag:
        args.append(flag)
    before = seed.database.read_bytes()
    result = subprocess.run(
        [sys.executable, "-m", "knowledge", *args],
        env=_environment(),
        input="APPROVE\n",
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0 and result.stdout == ""
    assert "Traceback" not in result.stderr and seed.database.read_bytes() == before


@pytest.mark.parametrize("stage", ["eof", "create_server", "runtime_exit"])
def test_controlled_runtime_and_ro_engine_cleanup_and_stdio_handles(
    seed: DemoSeed, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    _require_mcp()
    from knowledge.mcp import controlled, server
    from knowledge.storage import create_sqlite_engine

    engine = create_sqlite_engine(f"sqlite+pysqlite:///{seed.database.as_posix()}")
    disposed = Mock(wraps=engine.dispose)
    monkeypatch.setattr(engine, "dispose", disposed)
    monkeypatch.setattr(server, "create_engine", lambda *args, **kwargs: engine)
    exited = Mock()
    original = controlled.open_controlled_runtime

    @contextmanager
    def observed(*args: Any, **kwargs: Any) -> Iterator[Any]:
        try:
            with original(*args, **kwargs) as runtime:
                yield runtime
        finally:
            exited()
            if stage == "runtime_exit":
                raise RuntimeError(SECRET)

    monkeypatch.setattr(controlled, "open_controlled_runtime", observed)
    if stage == "create_server":
        monkeypatch.setattr(server, "create_server", Mock(side_effect=RuntimeError(SECRET)))
    stdin, stdout = io.TextIOWrapper(io.BytesIO()), io.TextIOWrapper(io.BytesIO())
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        assert server.main(["--controlled", *_options(seed)]) == (0 if stage == "eof" else 1)
    disposed.assert_called_once()
    exited.assert_called_once()
    assert not stdin.buffer.closed and not stdout.buffer.closed
    assert root.handlers == handlers and root.level == level
    assert stdout.buffer.getvalue() == b""
    assert SECRET not in stderr.getvalue() and "Traceback" not in stderr.getvalue()


@pytest.mark.parametrize("fragment", ["a", "界", '"\\\n'])
def test_controlled_complete_2m_response_counts_utf8_escaping_and_structured_content(
    seed: DemoSeed, fragment: str
) -> None:
    patch = f"""
import json
from mcp import types
from knowledge.mcp.controlled import McpControlledService
from knowledge.mcp.server import MAX_TOOL_RESPONSE_BYTES
original = McpControlledService.preview_document_update
fragment = {fragment!r}
def sized(self, query):
    value = original(self, query)
    def candidate(count):
        dto = value.model_copy(update={{'diff': (
            value.diff[0].model_copy(update={{'new_text': fragment * count}}),
        )}})
        payload = dto.model_dump(mode='json')
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                             separators=(',', ':'))
        result = types.CallToolResult(content=[types.TextContent(type='text', text=encoded)],
                                      isError=False, structuredContent=payload)
        size = len(result.model_dump_json(by_alias=True, exclude_none=True).encode('utf-8'))
        return dto, size
    low, high = 1, MAX_TOOL_RESPONSE_BYTES
    while low < high:
        middle = (low + high + 1) // 2
        if candidate(middle)[1] <= MAX_TOOL_RESPONSE_BYTES:
            low = middle
        else:
            high = middle - 1
    return candidate(low + (1 if query.text.endswith('above') else 0))[0]
McpControlledService.preview_document_update = sized
"""
    with _controlled(seed, patch=patch) as client:
        client.initialize()
        value = _preview(client, "# Demo\n\nhello below")
        # CallToolResult 完整 JSON 的计数，不声称 transport envelope 或 SDK 峰值内存上限。
        text = value["diff"][0]["new_text"]
        assert text == fragment * (len(text) // len(fragment))
        result = json.loads(client.lines[-1])["result"]
        size = len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        assert 2 * 1024 * 1024 - 100 < size <= 2 * 1024 * 1024
        source = _payload(client.call("get_mutation_session", {}))["sources"][0]
        _assert_safe_error(
            client.call(
                "preview_document_update",
                {
                    "source_id": source["source_id"],
                    "document_id": source["document_id"],
                    "expected_checksum": source["checksum"],
                    "text": "# Demo\n\nhello above",
                },
            ),
            "mcp_response_too_large",
            413,
        )
    client.assert_clean()
    assert counts(seed)[3] == 0


def test_official_sdk_validates_controlled_outputs_over_stdio(seed: DemoSeed) -> None:
    _require_mcp()
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "knowledge.mcp.server", "--controlled", *_options(seed)],
        env=_environment(),
    )

    async def exercise() -> None:
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == TOOLS | CONTROLLED
            source = _payload(
                (await session.call_tool("get_mutation_session", {})).model_dump(
                    by_alias=True, exclude_none=True
                )
            )["sources"][0]
            _payload(
                (
                    await session.call_tool(
                        "get_mutation_document",
                        {
                            "document_id": source["document_id"],
                        },
                    )
                ).model_dump(by_alias=True, exclude_none=True)
            )
            value = _payload(
                (
                    await session.call_tool(
                        "preview_document_update",
                        {
                            "source_id": source["source_id"],
                            "document_id": source["document_id"],
                            "expected_checksum": source["checksum"],
                            "text": UPDATED,
                        },
                    )
                ).model_dump(by_alias=True, exclude_none=True)
            )
            args = _synthetic_grant(seed, value)
            command = _payload(
                (await session.call_tool("apply_document_update", args)).model_dump(
                    by_alias=True, exclude_none=True
                )
            )
            assert command["committed"] is True
            assert (
                _payload(
                    (
                        await session.call_tool(
                            "get_mutation_command",
                            {
                                "command_id": args["idempotency_key"],
                            },
                        )
                    ).model_dump(by_alias=True, exclude_none=True)
                )
                == command
            )

    anyio.run(exercise)


@pytest.mark.parametrize("entry", ["module", "cli"])
@pytest.mark.parametrize("args", [["--unknown", SECRET], [SECRET], ["--actor"]])
def test_malformed_cli_arguments_fixed_stderr_no_paths_or_storage(
    tmp_path: Path, entry: str, args: list[str]
) -> None:
    if entry == "cli":
        target, prefix = "knowledge.cli", ["mcp", "serve"]
    else:
        target, prefix = "knowledge.mcp.server", []
    result = _run_python(
        f"from {target} import main; raise SystemExit(main({[*prefix, *args]!r}))", tmp_path
    )
    assert result.returncode != 0 and result.stdout == ""
    assert SECRET not in result.stderr and str(tmp_path) not in result.stderr
    assert "Traceback" not in result.stderr and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("controlled", [False, True])
def test_cli_and_console_forward_every_option_to_shared_run_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, controlled: bool
) -> None:
    from knowledge.cli import main as cli_main
    from knowledge.mcp import server

    database, manifest, root = tmp_path / "db", tmp_path / "manifest", tmp_path / "root"
    shared = Mock()
    monkeypatch.setattr(server, "run_server", shared)
    options = [
        "--database",
        str(database),
        "--mutation-manifest",
        str(manifest),
        "--actor",
        ACTOR,
        "--demo-root",
        str(root),
    ]
    if controlled:
        options.append("--controlled")
    expected = {
        "controlled": controlled,
        "mutation_manifest": manifest,
        "actor": ACTOR,
        "demo_root": root,
    }
    assert cli_main(["mcp", "serve", *options]) == 0
    shared.assert_called_once_with(database, **expected)
    shared.reset_mock()
    assert server.main(options) == 0
    shared.assert_called_once_with(database, **expected)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("binding", [True, False])
def test_boolean_is_not_a_controlled_service_binding(binding: Any) -> None:
    _require_mcp()
    ro = Mock(spec=McpReadOnlyService)
    with pytest.raises(TypeError, match="mcp_controlled_binding_invalid"):
        create_server(ro, controlled_service=binding)
    for name in TOOLS:
        getattr(ro, name).assert_not_called()
