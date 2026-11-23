"""可选 MCP stdio 适配器；默认只读，受控写仅绑定显式提供的 service。"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager, redirect_stdout
from io import TextIOWrapper
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from konwledge import __version__
from konwledge.mcp.models import (
    BuildContextInput,
    CompareDocumentsInput,
    ContextPacket,
    DocumentDiffDTO,
    EvidenceDTO,
    GetEvidenceInput,
    GetLineageInput,
    LineageDTO,
    McpModel,
    SearchDTO,
    SearchInput,
)
from konwledge.mcp.service import McpReadError, McpReadOnlyService

if TYPE_CHECKING:
    from mcp.server import Server

    from konwledge.mcp.controlled import McpControlledService

# 顺序与名称是对外协议；输入 schema 直接由输入模型生成。
TOOL_INPUTS: dict[str, tuple[type[McpModel], str]] = {
    "search": (SearchInput, "只读 lexical 检索；仅返回指定时点的 active 证据。"),
    "build_context": (BuildContextInput, "按字符预算构建完整证据块上下文。"),
    "get_evidence": (GetEvidenceInput, "按 unit_id 获取 exact 历史证据与校验锚点。"),
    "get_lineage": (GetLineageInput, "分页获取 lineage_id 的版本链。"),
    "compare_documents": (CompareDocumentsInput, "分页比较同一来源的两个文档版本。"),
}
TOOL_OUTPUTS: dict[str, type[McpModel]] = {
    "search": SearchDTO,
    "build_context": ContextPacket,
    "get_evidence": EvidenceDTO,
    "get_lineage": LineageDTO,
    "compare_documents": DocumentDiffDTO,
}
# 完整 CallToolResult 的 UTF-8 JSON 上限，包含 text 转义与 structuredContent。
MAX_TOOL_RESPONSE_BYTES = 2 * 1024 * 1024
# SDK 已读取整条消息；此预算仅限制解析后参数 JSON，不是 wire/峰值内存上限。
MAX_WRITE_INPUT_BYTES = 128 * 1024
_WRITE_TOOLS = frozenset({"preview_document_update", "apply_document_update"})
_ERROR_STATUSES = {
    "mcp_storage_unavailable": 503,
    "mcp_snapshot_unavailable": 503,
    "mcp_record_invalid": 409,
    "document_not_found": 404,
    "unit_not_found": 404,
    "lineage_not_found": 404,
    "diff_source_mismatch": 409,
    "historical_document_unavailable": 410,
    "historical_source_unavailable": 410,
    "historical_evidence_unavailable": 410,
    "historical_evidence_invalid": 409,
    "historical_lineage_invalid": 409,
}
# 再做协议白名单检查，不能依赖 exception 构造后属性未被污染。
_CONTROLLED_ERROR_CODES = frozenset(
    {
        "mcp_mutation_scope_invalid",
        "mcp_mutation_input_invalid",
        "mcp_mutation_unavailable",
        "mcp_mutation_outcome_unknown",
        "mcp_approval_required",
        "mcp_approval_expired",
        "mcp_approval_conflict",
        "mcp_approval_phrase_mismatch",
        "mcp_mutation_startup_invalid",
        "mcp_document_not_found",
        "mcp_historical_document",
        "mcp_source_not_allowed",
        "mcp_source_not_found",
        "mcp_checksum_conflict",
        "mcp_diff_too_large",
        "mcp_text_too_large",
        "mcp_document_uneditable",
        "mcp_mutation_schema_unavailable",
        "mcp_idempotency_conflict",
        "mcp_preview_not_found",
        "mcp_confirmation_mismatch",
        "mcp_preview_corrupt",
        "mcp_preview_expired",
        "mcp_auto_evaluation_required",
        "mcp_write_conflict",
        "mcp_scope_mismatch",
        "mcp_server_clock_invalid",
        "mcp_command_not_found",
    }
)
_CONTROLLED_ERROR_STATUSES = frozenset({400, 403, 404, 409, 410, 413, 500, 503})
_OUTCOME_GUIDANCE = (
    "提交结果未知；仅调用 get_mutation_command，command_id 使用原 idempotency_key。"
    "不要自动重试 apply_document_update；本响应不表示回滚。"
)


def create_server(
    service: McpReadOnlyService, *, controlled_service: McpControlledService | None = None
) -> Server:
    """注册实例局部工具表；批准签发永远不在 MCP 工具表中。"""

    from mcp import types
    from mcp.server import Server
    from pydantic import ValidationError

    # 必须提供 service 绑定；布尔开关不能在 create_server 中自动创建写 service。
    if isinstance(controlled_service, bool):
        raise TypeError("mcp_controlled_binding_invalid")
    server: Server = Server("konwledge", version=__version__)
    inputs = dict(TOOL_INPUTS)
    outputs = dict(TOOL_OUTPUTS)
    bindings = {name: getattr(service, name) for name in inputs}
    annotations = {
        name: types.ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        )
        for name in inputs
    }
    controlled_names: frozenset[str] = frozenset()
    controlled_error: type[McpReadError] | None = None
    if controlled_service is not None:
        from konwledge.mcp.controlled import (
            CONTROLLED_TOOL_ANNOTATIONS,
            CONTROLLED_TOOL_INPUTS,
            CONTROLLED_TOOL_OUTPUTS,
            McpControlledError,
        )

        controlled_error = McpControlledError
        controlled_names = frozenset(CONTROLLED_TOOL_INPUTS)
        inputs.update(CONTROLLED_TOOL_INPUTS)
        outputs.update(CONTROLLED_TOOL_OUTPUTS)
        bindings.update({name: getattr(controlled_service, name) for name in controlled_names})
        annotations.update(
            {
                name: types.ToolAnnotations.model_validate(hints)
                for name, hints in CONTROLLED_TOOL_ANNOTATIONS.items()
            }
        )

    tools = [
        types.Tool(
            name=name,
            description=description,
            inputSchema=model.model_json_schema(),
            outputSchema=outputs[name].model_json_schema(mode="serialization"),
            annotations=annotations[name],
        )
        for name, (model, description) in inputs.items()
    ]

    async def list_tools(_request: types.ListToolsRequest) -> types.ServerResult:
        return types.ServerResult(types.ListToolsResult(tools=tools))

    server.request_handlers[types.ListToolsRequest] = list_tools

    def error_result(code: str, status: int) -> types.ServerResult:
        payload: dict[str, object] = {"error": {"code": code, "status": status}}
        if code == "mcp_mutation_outcome_unknown":
            payload["guidance"] = _OUTCOME_GUIDANCE
        return types.ServerResult(
            types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(payload, allow_nan=False))],
                isError=True,
            )
        )

    async def call_tool(request: types.CallToolRequest) -> types.ServerResult:
        name = request.params.name
        if name not in inputs:
            return error_result("mcp_tool_not_found", 404)
        is_apply = name == "apply_document_update"
        try:
            model, _description = inputs[name]
            arguments = request.params.arguments or {}
            if name in _WRITE_TOOLS:
                # 在任何 preview/apply 变更之前，计入 UTF-8 与 JSON 转义的完整参数预算。
                encoded_input = json.dumps(
                    arguments, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                ).encode("utf-8")
                if len(encoded_input) > MAX_WRITE_INPUT_BYTES:
                    return error_result("mcp_input_too_large", 413)
            query = model.model_validate(arguments)
        except (ValidationError, UnicodeError, ValueError, TypeError, RecursionError):
            # 不反射输入、原始异常、路径或 token。
            return error_result("mcp_invalid_arguments", 400)
        except Exception:
            return error_result("mcp_internal_error", 500)
        try:
            result: McpModel = bindings[name](query)  # 仅调用一次；绝不自动重试 apply。
        except McpReadError as error:
            if (
                name in controlled_names
                and controlled_error is not None
                and isinstance(error, controlled_error)
                and isinstance(error.code, str)
                and error.code in _CONTROLLED_ERROR_CODES
                and type(error.status) is int
                and error.status in _CONTROLLED_ERROR_STATUSES
            ):
                status = 500 if error.code == "mcp_mutation_outcome_unknown" else error.status
                return error_result(error.code, status)
            read_status = _ERROR_STATUSES.get(error.code) if isinstance(error.code, str) else None
            if name not in controlled_names and read_status is not None:
                return error_result(error.code, read_status)
            return error_result(
                "mcp_mutation_outcome_unknown" if is_apply else "mcp_internal_error", 500
            )
        except Exception:
            # 只有核心可确定 precommit 失败；适配器无法推断未知异常意味着回滚。
            return error_result(
                "mcp_mutation_outcome_unknown" if is_apply else "mcp_internal_error", 500
            )
        try:
            if name in controlled_names:
                # model_copy 可绕过校验；先验证 Python DTO，避免 JSON 将 NaN 静默转为 null。
                result = outputs[name].model_validate(result.model_dump(warnings=False))
            # model_dump_json 默认可能将非有限浮点变成 null，必须显式禁止。
            payload = result.model_dump(mode="json")
            encoded = json.dumps(
                payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            )
            response = types.CallToolResult(
                content=[types.TextContent(type="text", text=encoded)],
                isError=False,  # FAILED quality 仍是成功提交，不是工具错误。
                structuredContent=payload,
            )
            size = len(response.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"))
            if size > MAX_TOOL_RESPONSE_BYTES:
                if is_apply:
                    return error_result("mcp_mutation_outcome_unknown", 500)
                return error_result("mcp_response_too_large", 413)
        except Exception:
            # apply 返回之后的序列化失败不得错误承诺未提交/回滚。
            return error_result(
                "mcp_mutation_outcome_unknown" if is_apply else "mcp_internal_error", 500
            )
        return types.ServerResult(response)

    # 标准扩展点避免 SDK jsonschema/str(exception) 将敏感输入反射到 stdout。
    server.request_handlers[types.CallToolRequest] = call_tool
    return server


class _SafeLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # SDK 的验证日志可能包含输入/traceback；保留级别但不输出任意异常详情。
        return f"{record.levelname}: MCP server event"


@contextmanager
def _stderr_logging() -> Iterator[None]:
    root = logging.getLogger()
    loggers = [root] + [
        item
        for item in logging.Logger.manager.loggerDict.values()
        if isinstance(item, logging.Logger)
    ]
    saved = [(item, item.handlers[:], item.propagate) for item in loggers]
    level = root.level
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_SafeLogFormatter())
    for item in loggers:
        item.handlers = []
        item.propagate = True
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    try:
        yield
    finally:
        for item, handlers, propagate in saved:
            item.handlers = handlers
            item.propagate = propagate
        root.setLevel(level)
        handler.close()


def run_server(
    database: Path,
    *,
    controlled: bool = False,
    mutation_manifest: Path | None = None,
    actor: str | None = None,
    demo_root: Path | None = None,
) -> None:
    """运行一次 stdio 会话，EOF/异常后清理资源；默认独立 B5 只读 engine。"""

    # 最先检测可选依赖；无 SDK 不加载受控核心、不检查或接触数据库。
    import anyio
    from mcp.server.stdio import stdio_server

    if type(controlled) is not bool:
        raise ValueError("mcp_startup_invalid")
    if not controlled and any(value is not None for value in (mutation_manifest, actor, demo_root)):
        raise ValueError("mcp_startup_invalid")
    if controlled and (
        mutation_manifest is None
        or not isinstance(actor, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,79}", actor) is None
    ):
        raise ValueError("mcp_startup_invalid")

    # SDK transport 显式持有原 stdout；其余 print/log 都落到 stderr。
    protocol_stdin = TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    try:
        protocol_stdout = TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        try:
            with redirect_stdout(sys.stderr), _stderr_logging(), ExitStack() as stack:
                path = database.expanduser().resolve()
                if not path.is_file():
                    raise ValueError("mcp_database_unavailable")
                uri = path.as_uri() + "?mode=ro"
                engine = create_engine(
                    URL.create("sqlite+pysqlite", database=str(path)),
                    creator=lambda: sqlite3.connect(uri, uri=True),
                    poolclass=NullPool,
                )
                stack.callback(engine.dispose)
                # 不用带自动评估 hooks 的 create_session_factory 或 schema 升级。
                service = McpReadOnlyService(sessionmaker(bind=engine, autoflush=False))
                if controlled:
                    # 显式开启后，且在安全 stdout/log 上下文内才加载、打开受控 runtime。
                    from konwledge.mcp.controlled import open_controlled_runtime

                    assert mutation_manifest is not None and actor is not None
                    runtime = stack.enter_context(
                        open_controlled_runtime(
                            database, mutation_manifest, actor, demo_root=demo_root
                        )
                    )
                    server = create_server(service, controlled_service=runtime.service)
                else:
                    server = create_server(service)

                async def serve() -> None:
                    async with stdio_server(
                        stdin=anyio.wrap_file(protocol_stdin),
                        stdout=anyio.wrap_file(protocol_stdout),
                    ) as (read_stream, write_stream):
                        await server.run(
                            read_stream, write_stream, server.create_initialization_options()
                        )

                anyio.run(serve)
        finally:
            # transport 不拥有进程 stdio；wrapper 析构不得关闭原句柄。
            protocol_stdout.detach()
    finally:
        protocol_stdin.detach()


class _SafeParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        # argparse 默认回显非法参数/路径，入口仅输出固定消息。
        raise ValueError("mcp_startup_invalid")


def main(argv: Sequence[str] | None = None) -> int:
    """konwledge-mcp console 入口，与 knowledge mcp serve 共用 stdio 实现。"""

    parser = _SafeParser(
        description="konwledge MCP stdio 服务：默认五个只读工具；显式启用受控编辑。",
        allow_abbrev=False,
    )
    parser.add_argument("--database", "-d", type=Path, default=Path(".konwledge/knowledge.db"))
    parser.add_argument("--controlled", action="store_true", help="显式启用五个受控工具。")
    parser.add_argument("--mutation-manifest", type=Path, help="私有 mutation demo manifest JSON。")
    parser.add_argument("--actor", help="安全 ASCII 操作者标识（1-80 字符）。")
    parser.add_argument("--demo-root", type=Path, help="私有演示根目录（默认工作目录下）。")
    try:
        arguments = parser.parse_args(argv)
        run_server(
            arguments.database,
            controlled=arguments.controlled,
            mutation_manifest=arguments.mutation_manifest,
            actor=arguments.actor,
            demo_root=arguments.demo_root,
        )
    except ImportError:
        print("缺少 MCP 可选依赖；请安装：pip install 'konwledge[mcp]'", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception:
        print("MCP 服务无法启动或运行。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
