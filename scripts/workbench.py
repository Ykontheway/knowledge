"""B-R2 统一入口：只读默认，受控写显式选择，原驱动在隔离子进程复用。"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

# 支持 python scripts/workbench.py；不依赖 editable install，不使用 inherited PYTHONPATH。
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import workbench_runtime as runtime


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse 默认会复述任意输入（例如错误传入的 DSN/key）；这里只打印固定码。
        self.exit(2, "invalid_arguments\n")


def port(raw: str) -> int:
    try:
        value = int(raw)
        if not 1 <= value <= 65535:
            raise ValueError
        return value
    except ValueError:
        raise argparse.ArgumentTypeError("invalid_arguments") from None


def timeout_value(raw: str) -> float:
    try:
        value = float(raw)
        if not math.isfinite(value) or not 0 < value <= 86400:
            raise ValueError
        return value
    except ValueError:
        raise argparse.ArgumentTypeError("invalid_arguments") from None


def parser() -> SafeParser:
    result = SafeParser(description=__doc__, allow_abbrev=False)
    sub = result.add_subparsers(dest="command", required=True, parser_class=SafeParser)
    sub.add_parser("list", help="列出固定入口与安全默认值", allow_abbrev=False)
    demo = sub.add_parser("demo", help="准备私有演示库，可启动 loopback GUI", allow_abbrev=False)
    demo.add_argument("--mode", choices=("readonly", "controlled"), default="readonly")
    demo.add_argument("--actor")
    demo.add_argument("--prepare-only", action="store_true")
    demo.add_argument("--web-port", type=port, default=5175)
    demo.add_argument("--api-port", type=port, default=8015)
    demo.add_argument("--timeout", type=timeout_value, default=900)
    accept = sub.add_parser("accept", help="串行运行独立验收组件", allow_abbrev=False)
    accept.add_argument(
        "--suite",
        choices=("readonly", "full", "management", "evaluation", "mutations"),
        default="readonly",
    )
    accept.add_argument("--with-distribution", action="store_true")
    accept.add_argument("--timeout", type=timeout_value, default=900)
    return result


def parse_options(argv: Sequence[str]) -> runtime.Options | None:
    args = parser().parse_args(argv)
    if args.command == "list":
        return None
    if args.command == "demo":
        options = runtime.Options(
            "demo",
            mode=args.mode,
            actor=args.actor,
            prepare_only=args.prepare_only,
            web_port=args.web_port,
            api_port=args.api_port,
            timeout=args.timeout,
        )
    else:
        options = runtime.Options(
            "accept",
            suite=args.suite,
            timeout=args.timeout,
            with_distribution=args.with_distribution,
        )
    options.validate()
    return options


def hidden_adapter(argv: Sequence[str]) -> int:
    internal = SafeParser(add_help=False, allow_abbrev=False)
    internal.add_argument("--session-id", required=True)
    internal.add_argument("--component", required=True, choices=runtime.COMPONENTS)
    internal.add_argument("--invocation-id", required=True)
    args = internal.parse_args(argv)
    runtime.canonical_uuid(args.session_id)
    runtime.canonical_uuid(args.invocation_id)
    raw = sys.stdin.buffer.read(4097)
    if len(raw) > 4096:
        raise runtime.RuntimeErrorCode("invalid_arguments")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise runtime.RuntimeErrorCode("invalid_arguments")
            result[key] = value
        return result

    request = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(request, dict):
        raise runtime.RuntimeErrorCode("invalid_arguments")
    return runtime.adapter(args.session_id, args.component, args.invocation_id, request)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["_adapter"]:
        # 子进程路径无 console 输出；receipt 失败只能体现为退出码。
        try:
            return hidden_adapter(arguments[1:])
        except Exception:
            return 1
    try:
        options = parse_options(arguments)
        if options is None:
            print("demo: readonly (default); controlled requires --actor; --prepare-only")
            print("demo loopback: web=5175 api=8015; timeout=900/component (0..86400]")
            print(
                "accept: readonly (default)=management+evaluation; "
                "full/management/evaluation/mutations"
            )
            print("accept --with-distribution: isolated distribution smoke")
            return 0
        path, summary, code = runtime.execute(options)
        print(f"summary {path.relative_to(runtime.ROOT).as_posix()}")
        print(f"status {summary['status']}")
        return code
    except runtime.RuntimeErrorCode as error:
        print(error.code, file=sys.stderr)
        return 2 if error.code == "invalid_arguments" else 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 1
    except Exception:
        print("runtime_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
