from __future__ import annotations

import io
import json
import os
import pty
import select
import sqlite3
import subprocess
import sys
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

import pytest

from knowledge.mcp import approval_cli
from knowledge.mcp.controlled import open_controlled_runtime
from knowledge.mcp.controlled_models import ApprovalGrantDTO
from test_mcp_controlled_service import ACTOR, DemoSeed, counts, make_demo, preview


@pytest.fixture
def seed(tmp_path: Path) -> DemoSeed:
    return make_demo(tmp_path)


def arguments(seed: DemoSeed, preview_id: UUID, key: UUID) -> list[str]:
    return [
        "--database",
        str(seed.database),
        "--mutation-manifest",
        str(seed.manifest),
        "--actor",
        ACTOR,
        "--demo-root",
        str(seed.root),
        "--preview-id",
        str(preview_id),
        "--idempotency-key",
        str(key),
    ]


class TtyStream(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.mark.parametrize("stdin_tty,stderr_tty", [(False, False), (True, False), (False, True)])
def test_noninteractive_denied(
    seed: DemoSeed, monkeypatch: pytest.MonkeyPatch, stdin_tty: bool, stderr_tty: bool
) -> None:
    stdin = TtyStream() if stdin_tty else io.StringIO()
    stderr = TtyStream() if stderr_tty else io.StringIO()
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(sys, "stdout", stdout)
    before = seed.database.read_bytes()
    assert approval_cli.main(arguments(seed, uuid4(), uuid4())) == 1
    assert "mcp_approval_terminal_required" in stderr.getvalue()
    assert stdout.getvalue() == "" and seed.database.read_bytes() == before


@pytest.mark.parametrize("flag", ["--yes", "--confirmed", "--approval-token", "--demo-ro"])
def test_no_auto_confirmation_arguments(
    seed: DemoSeed, flag: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stderr, stdout = TtyStream(), io.StringIO()
    monkeypatch.setattr(sys, "stdin", TtyStream("APPROVE\n"))
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(sys, "stdout", stdout)
    before = seed.database.read_bytes()
    assert approval_cli.main([*arguments(seed, uuid4(), uuid4()), flag]) == 1
    assert stdout.getvalue() == "" and seed.database.read_bytes() == before
    assert flag not in stderr.getvalue()


def tty_cli(seed: DemoSeed, *, correct: bool) -> tuple[int, str, str]:
    """PTY 同意仅是隔离测试数据，不是用户对真实库的授权。"""
    with open_controlled_runtime(
        seed.database, seed.manifest, ACTOR, demo_root=seed.root
    ) as runtime:
        value = preview(runtime.service, "# Demo\n\nhello \x1b[31m bidi\u202e control\x07")
        key = uuid4()
        phrase = runtime.service.review_approval(value.preview_id, key).approval_phrase
    master, slave = pty.openpty()
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "knowledge.mcp.approval_cli",
            *arguments(seed, value.preview_id, key),
        ],
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
            if monotonic() >= deadline or child.poll() is not None:
                raise AssertionError("PTY review unavailable")
            if select.select([master], [], [], 0.2)[0]:
                transcript += os.read(master, 65536)
        # 审批 review 转义正文控制字符，不回显 token。
        assert b"\x1b" not in transcript and b"\xe2\x80\xae" not in transcript
        assert value.confirmation_token.encode() not in transcript
        os.write(master, ((phrase if correct else phrase + " wrong") + "\n").encode())
        stdout, _ = child.communicate(timeout=20)
        while select.select([master], [], [], 0)[0]:
            try:
                data = os.read(master, 65536)
            except OSError:
                break
            if not data:
                break
            transcript += data
        return child.returncode, stdout, transcript.decode("utf-8")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)


def test_pty_exact_phrase_private_grant_no_stdout_secret(seed: DemoSeed) -> None:
    before = counts(seed)
    code, stdout, terminal = tty_cli(seed, correct=True)
    assert code == 0, terminal
    result = json.loads(stdout)
    target = Path(result["approval_file"])
    assert target.parent == seed.manifest.parent / "mcp-approvals"
    assert target.name == result["approval_id"] + ".json"
    grant = ApprovalGrantDTO.model_validate_json(target.read_text())
    assert grant.approval_token not in stdout and grant.approval_token not in terminal
    assert "hello" not in stdout and "confirmation_token" not in terminal
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.parent.stat().st_mode & 0o777 == 0o700
    assert target.stat().st_uid == os.getuid() and target.stat().st_nlink == 1
    assert counts(seed) == before
    with sqlite3.connect(seed.database) as db:
        assert db.execute("SELECT count(*) FROM mcp_approvals").fetchone()[0] == 1
        assert db.execute("SELECT consumed_at FROM mcp_approvals").fetchone()[0] is None


def test_pty_wrong_phrase_no_grant(seed: DemoSeed) -> None:
    before = counts(seed)
    code, stdout, terminal = tty_cli(seed, correct=False)
    assert code == 1 and "mcp_approval_phrase_mismatch" in terminal and stdout == ""
    assert counts(seed) == before
    with sqlite3.connect(seed.database) as db:
        assert db.execute("SELECT count(*) FROM mcp_approvals").fetchone()[0] == 0


@pytest.mark.parametrize(
    "bad",
    ["symlink_dir", "symlink_file", "hardlink_file", "file_exists", "directory_mode", "wrongowner"],
)
def test_grant_file_safety(
    seed: DemoSeed, bad: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_controlled_runtime(
        seed.database, seed.manifest, ACTOR, demo_root=seed.root
    ) as runtime:
        value, key = preview(runtime.service), uuid4()
        review = runtime.service.review_approval(value.preview_id, key)
        grant = runtime.service.issue_approval(
            value.preview_id, key, approval_phrase=review.approval_phrase
        )
        directory = seed.manifest.parent / "mcp-approvals"
        outside = tmp_path / "outside"
        outside.mkdir(mode=0o700)
        if bad == "symlink_dir":
            directory.symlink_to(outside, target_is_directory=True)
        else:
            directory.mkdir(mode=0o700)
            target = directory / f"{grant.approval_id}.json"
            external = outside / "external.json"
            external.write_text("untouched")
            external.chmod(0o600)
            if bad == "symlink_file":
                target.symlink_to(external)
            elif bad == "hardlink_file":
                os.link(external, target)
            elif bad == "file_exists":
                target.write_text("untouched")
                target.chmod(0o600)
            elif bad == "directory_mode":
                directory.chmod(0o755)
            elif bad == "wrongowner":
                uid = os.getuid()
                monkeypatch.setattr("knowledge.mcp.approval_cli.os.getuid", lambda: uid + 1)
        before = counts(seed)
        with pytest.raises((ValueError, OSError)):
            approval_cli._write_grant(runtime.service, grant)
        assert counts(seed) == before
        assert not any(outside.glob("*")) or (outside / "external.json").read_text() == "untouched"


def test_file_failure_acknowledges_stored_grant(
    seed: DemoSeed, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_controlled_runtime(
        seed.database, seed.manifest, ACTOR, demo_root=seed.root
    ) as runtime:
        value, key = preview(runtime.service), uuid4()
        phrase = runtime.service.review_approval(value.preview_id, key).approval_phrase
    stdin, stderr, stdout = TtyStream(phrase + "\n"), TtyStream(), io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(sys, "stdout", stdout)

    def fail(_service: object, _grant: object) -> Path:
        raise OSError("private path/token must not leak")

    monkeypatch.setattr(approval_cli, "_write_grant", fail)
    before = counts(seed)
    assert approval_cli.main(arguments(seed, value.preview_id, key)) == 1
    assert stdout.getvalue() == ""
    assert "grant_stored_no_knowledge_commit_reapprove" in stderr.getvalue()
    assert "private path" not in stderr.getvalue() and counts(seed) == before
    with sqlite3.connect(seed.database) as db:
        assert db.execute("SELECT count(*) FROM mcp_approvals").fetchone()[0] == 1


def test_ctrl_c_safe_exit(seed: DemoSeed, monkeypatch: pytest.MonkeyPatch) -> None:
    with open_controlled_runtime(
        seed.database, seed.manifest, ACTOR, demo_root=seed.root
    ) as runtime:
        value = preview(runtime.service)

    def interrupt(_size: int = -1) -> str:
        raise KeyboardInterrupt

    stdin, stderr, stdout = TtyStream(), TtyStream(), io.StringIO()
    monkeypatch.setattr(stdin, "readline", interrupt)
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(sys, "stdout", stdout)
    assert approval_cli.main(arguments(seed, value.preview_id, uuid4())) == 130
    assert stdout.getvalue() == "" and "mcp_approval_interrupted" in stderr.getvalue()
