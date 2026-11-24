"""本机 operator 带外批准；不连接 MCP、不依赖 SDK、不接受自动确认。

终端和私有文件只区分模型通道，不是生产 SSO 或密码学人类身份证明。
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import NoReturn
from uuid import UUID

from knowledge.mcp.controlled import (
    McpControlledError,
    McpControlledService,
    open_controlled_runtime,
)
from knowledge.mcp.controlled_models import ApprovalGrantDTO
from knowledge.mcp.controlled_safety import private_owned


class _Parser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise ValueError("mcp_approval_arguments_invalid")


def _safe_error(code: str) -> None:
    print(json.dumps({"error_code": code}, ensure_ascii=True), file=sys.stderr)


def _private_fd(descriptor: int, *, directory: bool) -> os.stat_result:
    info = os.fstat(descriptor)
    if (
        info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
        or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
        or (not directory and info.st_nlink != 1)
    ):
        raise ValueError("mcp_approval_file_invalid")
    return info


def _write_grant(service: McpControlledService, grant: ApprovalGrantDTO) -> Path:
    # 固定 scope/mcp-approvals/<UUID>.json，不接受任意 output target。
    guard = service._guard
    guard.validate()
    scope_path = guard.manifest.parent
    private_owned(scope_path, directory=True)
    scope_fd = os.open(scope_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory_fd: int | None = None
    try:
        info = _private_fd(scope_fd, directory=True)
        if (info.st_dev, info.st_ino) != guard.identities[1]:
            raise ValueError("mcp_approval_file_invalid")
        with suppress(FileExistsError):
            os.mkdir("mcp-approvals", mode=0o700, dir_fd=scope_fd)
        directory_fd = os.open(
            "mcp-approvals",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=scope_fd,
        )
        directory_info = _private_fd(directory_fd, directory=True)
        name = f"{grant.approval_id}.json"
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        try:
            _private_fd(descriptor, directory=False)
            with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                descriptor = -1  # fdopen 负责关闭。
                json.dump(grant.model_dump(mode="json"), stream, ensure_ascii=True, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
                written_info = _private_fd(stream.fileno(), directory=False)
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            os.unlink(name, dir_fd=directory_fd)
            raise
        os.fsync(directory_fd)
        guard.check_paths()
        directory_path = scope_path / "mcp-approvals"
        target = directory_path / name
        private_owned(directory_path, directory=True)
        private_owned(target)
        current_directory, current_file = directory_path.stat(), target.stat()
        if (current_directory.st_dev, current_directory.st_ino) != (
            directory_info.st_dev,
            directory_info.st_ino,
        ) or (current_file.st_dev, current_file.st_ino) != (
            written_info.st_dev,
            written_info.st_ino,
        ):
            raise ValueError("mcp_approval_file_invalid")
        return target
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
        os.close(scope_fd)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--mutation-manifest", type=Path, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--demo-root", type=Path, required=True)
    parser.add_argument("--preview-id", type=UUID, required=True)
    parser.add_argument("--idempotency-key", type=UUID, required=True)
    grant_stored = False
    try:
        args = parser.parse_args(argv)
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            _safe_error("mcp_approval_terminal_required")
            return 1
        with open_controlled_runtime(
            args.database,
            args.mutation_manifest,
            args.actor,
            demo_root=args.demo_root,
        ) as runtime:
            review = runtime.service.review_approval(args.preview_id, args.idempotency_key)
            # ensure_ascii 转义 ESC/control/bidi，正文绝不作为终端控制序列解释。
            print(
                json.dumps(review.model_dump(mode="json"), ensure_ascii=True, allow_nan=False),
                file=sys.stderr,
                flush=True,
            )
            print("Type the exact approval_phrase above:", file=sys.stderr, flush=True)
            phrase = sys.stdin.readline(513)
            if not phrase.endswith("\n") or phrase[:-1] != review.approval_phrase:
                _safe_error("mcp_approval_phrase_mismatch")
                return 1
            grant = runtime.service.issue_approval(
                args.preview_id,
                args.idempotency_key,
                approval_phrase=phrase[:-1],
            )
            grant_stored = True
            target = _write_grant(runtime.service, grant)
            # stdout 仅安全文件位置/ID；不打印正文、confirmation 或 approval token。
            print(
                json.dumps(
                    {"approval_id": str(grant.approval_id), "approval_file": str(target)},
                    ensure_ascii=True,
                    allow_nan=False,
                )
            )
            return 0
    except KeyboardInterrupt:
        _safe_error(
            "mcp_approval_interrupted_grant_stored_no_knowledge_commit"
            if grant_stored
            else "mcp_approval_interrupted"
        )
        return 130
    except McpControlledError as error:
        _safe_error(
            "mcp_approval_file_failed_grant_stored_no_knowledge_commit_reapprove"
            if grant_stored
            else error.code
        )
        return 1
    except Exception:
        _safe_error(
            "mcp_approval_file_failed_grant_stored_no_knowledge_commit_reapprove"
            if grant_stored
            else "mcp_approval_unavailable"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
