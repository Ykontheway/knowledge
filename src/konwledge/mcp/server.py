"""可选 MCP SDK 的 stdio 适配器；不创建 schema 或调用可写的应用 facade。"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, redirect_stdout
from io import TextIOWrapper
from pathlib import Path
from typing import TYPE_CHECKING

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


def create_server(service: McpReadOnlyService) -> Server:
    """注册 SDK Server；所有工具错误均返回固定、安全的 MCP CallToolResult。"""

    from mcp import types
    from mcp.server import Server
    from pydantic import ValidationError

    server: Server = Server("konwledge", version=__version__)
    tools = []
    for name, (model, description) in TOOL_INPUTS.items():
        schema = TOOL_OUTPUTS[name].model_json_schema(mode="serialization")
        tools.append(
            types.Tool(
                name=name,
                description=description,
                inputSchema=model.model_json_schema(),
                outputSchema=schema,
                # annotations 仅为协议提示；只读权限由 SQLite mode=ro/query_only 保证。
                annotations=types.ToolAnnotations(
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            )
        )

    async def list_tools(_request: types.ListToolsRequest) -> types.ServerResult:
        return types.ServerResult(types.ListToolsResult(tools=tools))

    server.request_handlers[types.ListToolsRequest] = list_tools

    def error_result(code: str, status: int) -> types.ServerResult:
        return types.ServerResult(
            types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text", text=json.dumps({"error": {"code": code, "status": status}})
                    )
                ],
                isError=True,
            )
        )

    async def call_tool(request: types.CallToolRequest) -> types.ServerResult:
        name = request.params.name
        if name not in TOOL_INPUTS:
            return error_result("mcp_tool_not_found", 404)
        try:
            model, _description = TOOL_INPUTS[name]
            arguments = request.params.arguments or {}
            query = model.model_validate(arguments)
        except (ValidationError, UnicodeError):
            # 不回显 Pydantic 的 input_value、输入值、文件路径或异常消息。
            return error_result("mcp_invalid_arguments", 400)
        except Exception:
            return error_result("mcp_internal_error", 500)
        try:
            result: McpModel = getattr(service, name)(query)
            # model_dump_json 默认可将非有限浮点变成 null；必须显式禁止而非静默改证据。
            payload = result.model_dump(mode="json")
            encoded = json.dumps(
                payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            )
            if len(encoded.encode("utf-8")) > MAX_TOOL_RESPONSE_BYTES:
                return error_result("mcp_response_too_large", 413)
            response = types.CallToolResult(
                content=[types.TextContent(type="text", text=encoded)],
                isError=False,
                structuredContent=payload,
            )
            if (
                len(response.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"))
                > MAX_TOOL_RESPONSE_BYTES
            ):
                return error_result("mcp_response_too_large", 413)
        except McpReadError as error:
            # 即使服务异常的 code 被污染，也只允许已知 code/status 进入协议。
            status = _ERROR_STATUSES.get(error.code)
            if status is not None:
                return error_result(error.code, status)
            return error_result("mcp_internal_error", 500)
        except Exception:
            return error_result("mcp_internal_error", 500)
        return types.ServerResult(response)

    # 使用标准 request_handlers 扩展点构造安全的 CallToolResult，
    # 避免 SDK 的 jsonschema 错误或 str(exception) 将敏感输入反射到 stdout。
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


def run_server(database: Path) -> None:
    """运行一次 stdio 会话，EOF 后释放 transport 和 engine；整个会话零写。"""

    # 先检测可选依赖；无 SDK 时不检查或接触数据库。
    import anyio
    from mcp.server.stdio import stdio_server

    # SDK transport 显式持有原 stdout；其余 print/log 都落到 stderr。
    protocol_stdin = TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    protocol_stdout = TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    try:
        with redirect_stdout(sys.stderr), _stderr_logging():
            path = database.expanduser().resolve()
            if not path.is_file():
                raise ValueError("mcp_database_unavailable")
            uri = path.as_uri() + "?mode=ro"
            engine = create_engine(
                URL.create("sqlite+pysqlite", database=str(path)),
                creator=lambda: sqlite3.connect(uri, uri=True),
                poolclass=NullPool,
            )
            try:
                # 不使用带自动评估 hooks 的 create_session_factory 或 schema 升级。
                service = McpReadOnlyService(sessionmaker(bind=engine, autoflush=False))
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
                engine.dispose()
    finally:
        # transport 不拥有进程 stdio；防止临时 UTF-8 wrapper 的析构关闭原句柄。
        protocol_stdin.detach()
        protocol_stdout.detach()


def main(argv: Sequence[str] | None = None) -> int:
    """konwledge-mcp console 入口，与 knowledge mcp serve 共用 stdio 实现。"""

    parser = argparse.ArgumentParser(description="只读 konwledge MCP stdio 服务。")
    parser.add_argument("--database", "-d", type=Path, default=Path(".konwledge/knowledge.db"))
    arguments = parser.parse_args(argv)
    try:
        run_server(arguments.database)
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
