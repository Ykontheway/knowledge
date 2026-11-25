"""B6 真实安装门禁：新私有合成库、stdio 与 PTY；不是实际用户审批。

仅从当前解释器 site-packages 加载核心；相邻 B5 脚本只复用协议客户端，
不引用 checkout fixtures，不接受业务数据库或网络参数，不调用 LLM。
stdout 仅固定名称/计数/版本；所有正文和 capability 仅在临时测试内存/私有文件中。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import importlib.util
import io
import json
import os
import select
import sqlite3
import stat
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from types import ModuleType
from typing import Any, cast
from uuid import UUID, uuid4

CHECKS = (
    "installed_nine_mcp_modules",
    "mcp_only_dependency_boundary",
    "default_five_tools_no_controlled_imports_or_tables",
    "fresh_private_b4_seed_actual_quality_four_cases",
    "controlled_startup_approval_schema_only",
    "initialize_ten_tools_explicit_schemas_annotations",
    "session_document_reads_zero_writes",
    "preview_and_pty_approval_no_knowledge_jobs",
    "pty_exact_escaped_review_private_grant_no_token_stdout",
    "non_tty_and_wrong_phrase_denied",
    "scope_actor_expiry_token_key_confirmed_denied_unchanged",
    "approval_consume_knowledge_outbox_atomic_rollback",
    "passed_failed_passed_fixed_dataset_committed",
    "same_key_replay_no_extra_job",
    "restart_command_diff_exact_historical_evidence",
    "safe_unknown_approval_tool_errors",
    "stdio_eof_no_orphans_no_secret_output",
)
MODULES = (
    "__init__",
    "models",
    "service",
    "server",
    "controlled_models",
    "controlled_tables",
    "controlled_safety",
    "controlled",
    "approval_cli",
)
CONTROLLED_TOOLS = (
    "get_mutation_session",
    "get_mutation_document",
    "preview_document_update",
    "apply_document_update",
    "get_mutation_command",
)
ACTOR = "installed-synthetic-editor"
MARKERS = ("cobalta", "amberb", "violetc", "silverd")
# 控制字符仅用于验证终端 review 转义，不影响被冻结的检索 query/lineage。
SUFFIX = " synthetic review \x1b[31m \u202e \x07"
TEXTS = tuple(
    "".join(
        f"# Case {index + 1}\n\n{marker if revision != 2 else 'absentcontent'} "
        f"stable evidence revision {revision}.{SUFFIX}\n\n"
        for index, marker in enumerate(MARKERS)
    )
    for revision in range(4)
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def companion() -> ModuleType:
    """由发行 runner 明确复制相邻 B5 脚本；-I 不添加 checkout 到 sys.path。"""
    name = "_installed_b5_protocol"
    spec = importlib.util.spec_from_file_location(
        name,
        Path(__file__).with_name("installed_mcp_smoke.py"),
    )
    require(spec is not None and spec.loader is not None, "B5 protocol companion missing")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class Seed:
    root: Path
    manifest: Path
    database: Path
    document: str
    unit: str
    lineage: str
    dataset_hash: str
    dataset_id: UUID


def private_json(path: Path, value: Any) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=True, allow_nan=False)
        stream.write("\n")


def prepare_seed(temporary: Path) -> Seed:
    """真正运行四 case quality 后才写 passed marker；不复制库、不伪造验收结果。"""
    from knowledge import KnowledgeLibrary
    from knowledge.domain import EvaluationItem, EvaluationSet
    from knowledge.mutations.tables import create_mutation_schema
    from knowledge.storage import create_schema, create_session_factory, create_sqlite_engine

    root = temporary / ".knowledge" / "mutation-demo"
    root.mkdir(parents=True, mode=0o700)
    scope = root / str(uuid4())
    scope.mkdir(mode=0o700)
    seed = scope / "seed"
    seed.mkdir(mode=0o700)
    source = seed / "synthetic.md"
    source.write_text(TEXTS[0], encoding="utf-8")
    source.chmod(0o600)
    database = seed / "knowledge.db"
    require(not database.exists(), "seed must be fresh")
    engine = create_sqlite_engine(f"sqlite+pysqlite:///{database.as_posix()}")
    try:
        create_schema(engine)
        create_mutation_schema(engine)
        library = KnowledgeLibrary(create_session_factory(engine))
        imported = library.import_path(source).imported[0].result
        require(len(imported.units) == len(MARKERS), "four real units required")
        dataset = EvaluationSet(
            id=uuid4(),
            name="Installed B6 frozen synthetic quality",
            version=1,
            created_at=datetime.now(UTC),
            items=tuple(
                EvaluationItem(
                    id=f"case-{index + 1}",
                    query=marker,
                    expected_lineage_ids=frozenset({imported.units[index].lineage_id}),
                )
                for index, marker in enumerate(MARKERS)
            ),
        )
        library.evaluation.import_set(dataset)
        quality = library.quality.run(dataset.id, version=1)
        require(quality.passed and quality.metrics.case_count == 4, "actual seed quality failed")
        config = library.automatic_evaluation.enable(dataset.id, version=1)
        require(
            config.enabled and config.dataset_hash == dataset.content_hash, "dataset not pinned"
        )
        require(library.automatic_evaluation.history() == (), "seed created audit jobs")
        private_json(
            seed / "report.json",
            {
                "status": "passed" if quality.passed else "failed",
                "artifacts": {"database": "knowledge.db"},
                "quality_cases": quality.metrics.case_count,
                "dataset_hash": dataset.content_hash,
                "checks": [
                    {"name": check.name, "passed": check.passed} for check in quality.checks
                ],
            },
        )
        manifest = scope / "mutation-manifest.json"
        private_json(
            manifest,
            {
                "kind": "knowledge-mutation-demo-v1",
                "scope_id": scope.name,
                "database": database.relative_to(scope).as_posix(),
                "allowed_source_ids": [str(imported.ingestion.document.source_id)],
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        database.chmod(0o600)
        return Seed(
            root,
            manifest,
            database,
            str(imported.ingestion.document.id),
            str(imported.units[0].id),
            str(imported.units[0].lineage_id),
            dataset.content_hash,
            dataset.id,
        )
    finally:
        engine.dispose()


def rows(seed: Seed) -> dict[str, tuple[tuple[Any, ...], ...]]:
    """全库逻辑快照（含 FTS/command/job/grant）；拒绝前后必须逐行相同。"""
    with sqlite3.connect(seed.database.as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
            )
        ]
        return {
            name: tuple(
                sorted(
                    connection.execute(
                        'SELECT * FROM "' + name.replace('"', '""') + '"',
                    ).fetchall(),
                    key=repr,
                )
            )
            for name in names
        }


def knowledge_rows(seed: Seed) -> dict[str, tuple[tuple[Any, ...], ...]]:
    return {
        name: value
        for name, value in rows(seed).items()
        if name not in {"mutation_previews", "mcp_approvals"}
    }


def approval_arguments(seed: Seed, preview: dict[str, Any], key: str) -> list[str]:
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
        preview["preview_id"],
        "--idempotency-key",
        key,
    ]


def approve_pty(
    b5: ModuleType, seed: Seed, preview: dict[str, Any], key: str, *, correct: bool = True
) -> dict[str, Any] | None:
    """真实 knowledge mcp approve TTY gate；自动输入仅代表 synthetic human-approved 测试。"""
    import pty

    from knowledge.mcp.controlled_models import ApprovalGrantDTO, ApprovalReviewDTO

    baseline = knowledge_rows(seed)
    grant_rows = rows(seed)["mcp_approvals"]
    master, slave = pty.openpty()
    child = subprocess.Popen(
        [b5.console("knowledge"), "mcp", "approve", *approval_arguments(seed, preview, key)],
        cwd=seed.root.parent.parent,
        env=b5.environment(),
        stdin=slave,
        stderr=slave,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    os.close(slave)
    transcript = b""
    try:
        deadline = monotonic() + 30
        while b"Type the exact approval_phrase above:" not in transcript:
            require(monotonic() < deadline and child.poll() is None, "PTY review unavailable")
            if select.select([master], [], [], 0.2)[0]:
                transcript += os.read(master, 65536)
        require(
            b"\x1b" not in transcript and b"\xe2\x80\xae" not in transcript,
            "review terminal control leak",
        )
        require(b"\\u001b" in transcript and b"\\u202e" in transcript, "review not escaped")
        require(preview["confirmation_token"].encode() not in transcript, "review token leak")
        review_line = next(
            line for line in transcript.decode().splitlines() if line.startswith("{")
        )
        review = ApprovalReviewDTO.model_validate_json(review_line)
        phrase = f"APPROVE {preview['preview_id']} {key} {preview['new_checksum']}"
        require(
            review.approval_phrase == phrase and review.new_checksum == preview["new_checksum"],
            "approval review binding mismatch",
        )
        os.write(master, ((phrase if correct else phrase + " wrong") + "\n").encode())
        stdout, _ = child.communicate(timeout=30)
        while select.select([master], [], [], 0)[0]:
            try:
                data = os.read(master, 65536)
            except OSError:
                break
            if not data:
                break
            transcript += data
        require(knowledge_rows(seed) == baseline, "approval changed knowledge/outbox")
        if not correct:
            require(child.returncode == 1 and stdout == "", "wrong phrase accepted")
            require(b"mcp_approval_phrase_mismatch" in transcript, "wrong phrase unsafe error")
            require(rows(seed)["mcp_approvals"] == grant_rows, "wrong phrase issued grant")
            return None
        require(child.returncode == 0, "PTY approval failed")
        result = json.loads(stdout)
        require(set(result) == {"approval_id", "approval_file"}, "approval stdout schema changed")
        target = Path(result["approval_file"])
        require(
            target == seed.manifest.parent / "mcp-approvals" / (result["approval_id"] + ".json"),
            "grant outside fixed scope",
        )
        info = target.lstat()
        require(
            stat.S_ISREG(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_uid == os.getuid()
            and info.st_nlink == 1,
            "grant not private owned",
        )
        require(stat.S_IMODE(target.parent.stat().st_mode) == 0o700, "grant directory not private")
        grant = ApprovalGrantDTO.model_validate_json(target.read_text())
        require(
            grant.approval_token not in stdout + transcript.decode(), "approval token stdout leak"
        )
        require(
            preview["confirmation_token"] not in stdout + transcript.decode(), "preview token leak"
        )
        remaining = (grant.expires_at - datetime.now(UTC)).total_seconds()
        require(
            0 < remaining <= 120
            and grant.expires_at <= datetime.fromisoformat(preview["expires_at"]),
            "approval TTL changed",
        )
        require(
            grant.preview_id == UUID(preview["preview_id"]) and grant.idempotency_key == UUID(key),
            "grant request binding mismatch",
        )
        require(len(rows(seed)["mcp_approvals"]) == len(grant_rows) + 1, "approval audit missing")
        return grant.model_dump(mode="json")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        os.close(master)
        if child.stdout is not None:
            child.stdout.close()


@dataclass
class Gate:
    b5: ModuleType
    seed: Seed
    version: str
    successes: int = 0
    rejects: int = 0
    responses: int = 0
    sessions: int = 0
    approvals: int = 0
    secrets: list[str] = field(default_factory=list, repr=False)

    def initialize(self, client: Any, *, controlled: bool) -> None:
        result = client.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "installed-synthetic-b6", "version": "1.0"},
            },
        )
        require(
            result["serverInfo"] == {"name": "knowledge", "version": self.version},
            "server metadata changed",
        )
        require(
            result["capabilities"]["tools"].get("listChanged", False) is False,
            "tools list changed capability",
        )
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = client.request("tools/list", {})["tools"]
        expected = set(self.b5.TOOLS) | (set(CONTROLLED_TOOLS) if controlled else set())
        require(
            len(tools) == len(expected) and {tool["name"] for tool in tools} == expected,
            "explicit tool collection mismatch",
        )
        self.b5.verify_schemas([tool for tool in tools if tool["name"] in self.b5.TOOLS])
        fields = {
            "get_mutation_session": set(),
            "get_mutation_document": {"document_id"},
            "preview_document_update": {"source_id", "document_id", "expected_checksum", "text"},
            "apply_document_update": {
                "preview_id",
                "confirmation_token",
                "idempotency_key",
                "approval_token",
            },
            "get_mutation_command": {"command_id"},
        }
        for tool in tools:
            name = tool["name"]
            if name in fields:
                schema = tool["inputSchema"]
                require(
                    schema.get("additionalProperties") is False
                    and set(schema.get("properties", {})) == fields[name],
                    "controlled schema",
                )
            hints = tool["annotations"]
            readonly = name in self.b5.TOOLS or name.startswith("get_")
            require(
                hints["readOnlyHint"] is readonly
                and hints["destructiveHint"] is (name == "apply_document_update")
                and hints["openWorldHint"] is False,
                "tool annotations changed",
            )
            require(
                hints["idempotentHint"] is (name != "preview_document_update"), "idempotent hint"
            )

    def call(self, client: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from knowledge.mcp.controlled_models import CONTROLLED_TOOL_OUTPUTS
        from knowledge.mcp.server import TOOL_OUTPUTS

        result = self.b5.payload(
            client.call(name, arguments), (CONTROLLED_TOOL_OUTPUTS | TOOL_OUTPUTS)[name]
        )
        self.successes += 1
        return cast(dict[str, Any], result)

    def deny(self, client: Any, name: str, arguments: dict[str, Any], codes: set[str]) -> None:
        before, files = rows(self.seed), self.b5.fingerprint(self.seed.root)
        result = client.call(name, arguments)
        require(result.get("isError") is True, "unsafe write accepted")
        value = json.loads(result["content"][0]["text"])
        require(
            set(value) == {"error"}
            and set(value["error"]) == {"code", "status"}
            and value["error"]["code"] in codes,
            "unsafe refusal code",
        )
        require(
            type(value["error"]["status"]) is int
            and value["error"]["status"] in {400, 403, 404, 409, 410},
            "unsafe error status",
        )
        rendered = json.dumps(result)
        require(
            str(self.seed.root) not in rendered
            and all(token not in rendered for token in self.secrets),
            "refusal secret leak",
        )
        require(
            rows(self.seed) == before and self.b5.fingerprint(self.seed.root) == files,
            "refusal changed knowledge/commands/jobs/grant/files",
        )
        self.rejects += 1

    def closed(self, client: Any) -> None:
        require(client.process.poll() == 0, "stdio orphan after EOF")
        self.sessions += 1
        self.responses += client.next_id
        # confirmation/approval may be legitimate DTO fields; stderr never carries capability。
        require(
            all(token not in "".join(client.stderr_lines) for token in self.secrets),
            "stderr capability leak",
        )


def server_command(
    b5: ModuleType, seed: Seed, *, controlled: bool, actor: str = ACTOR, cli: bool = False
) -> list[str]:
    command = [b5.console("knowledge"), "mcp", "serve"] if cli else [b5.console("knowledge-mcp")]
    command += ["--database", str(seed.database)]
    if controlled:
        command += [
            "--controlled",
            "--mutation-manifest",
            str(seed.manifest),
            "--actor",
            actor,
            "--demo-root",
            str(seed.root),
        ]
    return command


def read_evidence(gate: Gate, client: Any, new_document: str) -> None:
    evidence = gate.call(client, "get_evidence", {"unit_id": gate.seed.unit})
    require(
        evidence["document_id"] == gate.seed.document
        and evidence["text"] == TEXTS[0][evidence["start_char"] : evidence["end_char"]]
        and evidence["document_checksum"] == hashlib.sha256(TEXTS[0].encode()).hexdigest(),
        "historical evidence not exact",
    )
    gate.call(client, "get_lineage", {"lineage_id": gate.seed.lineage})
    gate.call(
        client,
        "compare_documents",
        {"old_document_id": gate.seed.document, "new_document_id": new_document},
    )
    gate.call(client, "search", {"query": MARKERS[0]})
    gate.call(client, "build_context", {"query": MARKERS[0]})


def atomic_denials(gate: Gate, request: dict[str, Any]) -> None:
    """在真实 installed B4 提交点注入故障与时间推进，不能先消费批准再另事务写知识。"""
    from sqlalchemy import event

    from knowledge.mcp.controlled import McpControlledError, open_controlled_runtime
    from knowledge.mcp.controlled_models import ApplyDocumentUpdateInput
    from knowledge.mcp.controlled_tables import McpApprovalRow
    from knowledge.storage import UnitOfWork

    query = ApplyDocumentUpdateInput.model_validate(
        {key: value for key, value in request.items() if key != "_approval_id"}
    )
    before = rows(gate.seed)
    with open_controlled_runtime(
        gate.seed.database, gate.seed.manifest, ACTOR, demo_root=gate.seed.root
    ) as runtime:
        service = runtime.service
        original = service._writer._commit_command

        def expired(uow: UnitOfWork, command_id: UUID, request_fingerprint: str) -> None:
            service._writer._clock = lambda: datetime.now(UTC) + timedelta(seconds=121)
            original(uow, command_id, request_fingerprint)

        service._writer._commit_command = expired  # type: ignore[method-assign]
        try:
            service.apply_document_update(query)
        except McpControlledError as error:
            require(error.code == "mcp_approval_expired", "atomic expiry guard missing")
        else:
            raise AssertionError("expired inside transaction committed")
        finally:
            service._writer._commit_command = original  # type: ignore[method-assign]
            service._writer._clock = lambda: datetime.now(UTC)
        require(rows(gate.seed) == before, "expiry did not rollback all facts")
        gate.rejects += 1

        def fail(session: Any) -> None:
            session.flush()
            grant = session.get(McpApprovalRow, UUID(request["_approval_id"]))
            require(
                grant is not None and grant.consumed_at is not None,
                "approval not consumed in knowledge transaction",
            )
            raise RuntimeError("synthetic private transaction failure")

        factory = service._writer._session_factory
        event.listen(factory, "before_commit", fail)
        try:
            service.apply_document_update(query)
        except McpControlledError as error:
            require(error.code == "mcp_mutation_unavailable", "rollback outcome unsafe")
        else:
            raise AssertionError("fault committed")
        finally:
            event.remove(factory, "before_commit", fail)
        require(rows(gate.seed) == before, "grant/knowledge/outbox not atomic")
        gate.rejects += 1


def verify_history(seed: Seed, commands: list[dict[str, Any]]) -> dict[str, int]:
    from knowledge import KnowledgeLibrary
    from knowledge.storage import create_session_factory, create_sqlite_engine

    before = rows(seed)
    engine = create_sqlite_engine(f"sqlite+pysqlite:///{seed.database.as_posix()}")
    try:
        library = KnowledgeLibrary(create_session_factory(engine))
        config = library.automatic_evaluation.status()
        require(config is not None and config.dataset_hash == seed.dataset_hash, "dataset changed")
        jobs = library.automatic_evaluation.history()
        require(len(jobs) == 3, "extra job or lost outbox")
        by_id = {str(job.id): job for job in jobs}
        for command, expected in zip(commands, ("passed", "failed", "passed"), strict=True):
            require(len(command["job_ids"]) == 1, "one command must have one job")
            job = by_id[command["job_ids"][0]]
            require(
                job.status.value == expected
                and job.dataset_hash == seed.dataset_hash
                and job.dataset_id == seed.dataset_id
                and job.dataset_version == 1,
                "frozen quality job mismatch",
            )
            require(
                job.report is not None and job.report["passed"] is (expected == "passed"),
                "quality report lost",
            )
            assert job.report is not None
            require(job.report["metrics"]["case_count"] == 4, "quality case count changed")
            require(
                set(map(str, job.trigger_revision_ids)) == set(command["revision_ids"]),
                "outbox not bound to committed revisions",
            )
            if expected == "failed":
                require(job.error_code == "QUALITY_GATE_FAILED", "failed quality error changed")
            rendered = json.dumps(job.report)
            require(
                str(seed.root) not in rendered
                and all(marker not in rendered for marker in MARKERS),
                "quality report leaked path/query",
            )
        require(
            library.evaluation.get(seed.dataset_id, 1).content_hash == seed.dataset_hash,
            "fixed dataset rewritten",
        )
    finally:
        engine.dispose()
    require(rows(seed) == before, "history read added job")
    data = rows(seed)
    with sqlite3.connect(seed.database.as_uri() + "?mode=ro", uri=True) as connection:
        consumed = connection.execute(
            "SELECT count(*) FROM mcp_approvals "
            "WHERE consumed_at IS NOT NULL AND command_id IS NOT NULL",
        ).fetchone()[0]
    return {
        "commands": len(data["mutation_commands"]),
        "jobs": len(jobs),
        "passed_jobs": sum(job.status.value == "passed" for job in jobs),
        "failed_jobs": sum(job.status.value == "failed" for job in jobs),
        "consumed_grants": consumed,
    }


def run_extra(b5: ModuleType, temporary: Path, version: str) -> dict[str, int]:
    seed = prepare_seed(temporary)
    gate = Gate(b5, seed, version)
    baseline, files = rows(seed), b5.fingerprint(seed.root)
    require("mcp_approvals" not in baseline, "default schema contains B6")
    # 真实默认 stdio 进程退出后再断言其没有导入受控模块，非静态代码检查。
    code = (
        "import sys; from pathlib import Path; from knowledge.mcp.server import run_server; "
        "run_server(Path(sys.argv[1])); "
        "assert not any(n.startswith(('knowledge.mcp.controlled',"
        "'knowledge.mcp.approval_cli','knowledge.mutations')) for n in sys.modules)"
    )
    with b5.session([sys.executable, "-I", "-c", code, str(seed.database)], temporary) as client:
        gate.initialize(client, controlled=False)
        read_evidence(gate, client, seed.document)
        gate.deny(client, "issue_approval", {}, {"mcp_tool_not_found"})
    gate.closed(client)
    require(rows(seed) == baseline and b5.fingerprint(seed.root) == files, "default MCP wrote")
    # 控制模块安装身份在显式操作之前逐个验证，缺失/源码回退都失败。
    for name in MODULES:
        module = importlib.import_module(
            "knowledge.mcp" if name == "__init__" else "knowledge.mcp." + name
        )
        require(
            module.__file__ is not None and b5.is_installed(Path(module.__file__)),
            "runtime module not installed",
        )
    commands: list[dict[str, Any]] = []
    with b5.session(server_command(b5, seed, controlled=True), temporary) as client:
        gate.initialize(client, controlled=True)
        startup = rows(seed)
        require(
            set(startup) - set(baseline) == {"mcp_approvals"}
            and all(startup[name] == value for name, value in baseline.items()),
            "controlled startup changed more than approval schema",
        )
        for revision, expected in zip(range(1, 4), ("passed", "failed", "passed"), strict=True):
            before, raw = rows(seed), seed.database.read_bytes()
            session_value = gate.call(client, "get_mutation_session", {})
            source = session_value["sources"][0]
            document = gate.call(
                client, "get_mutation_document", {"document_id": source["document_id"]}
            )
            require(document["text"] == TEXTS[revision - 1], "current document mismatch")
            require(rows(seed) == before and seed.database.read_bytes() == raw, "GET changed DB")
            preview = gate.call(
                client,
                "preview_document_update",
                {
                    "source_id": source["source_id"],
                    "document_id": source["document_id"],
                    "expected_checksum": source["checksum"],
                    "text": TEXTS[revision],
                },
            )
            require(
                knowledge_rows(seed)
                == {
                    name: value
                    for name, value in before.items()
                    if name not in {"mutation_previews", "mcp_approvals"}
                },
                "preview changed knowledge or job",
            )
            require(
                0
                < (
                    datetime.fromisoformat(preview["expires_at"]) - datetime.now(UTC)
                ).total_seconds()
                <= 300,
                "preview TTL changed",
            )
            gate.secrets.append(preview["confirmation_token"])
            key = str(uuid4())
            request = {
                "preview_id": preview["preview_id"],
                "confirmation_token": preview["confirmation_token"],
                "idempotency_key": key,
                "approval_token": "synthetic-not-approved",
            }
            gate.deny(client, "apply_document_update", request, {"mcp_approval_required"})
            if revision == 1:
                before_approve = rows(seed)
                denied = subprocess.run(
                    [
                        b5.console("knowledge"),
                        "mcp",
                        "approve",
                        *approval_arguments(seed, preview, key),
                    ],
                    cwd=temporary,
                    env=b5.environment(),
                    input="APPROVE\n",
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                require(
                    denied.returncode == 1
                    and denied.stdout == ""
                    and json.loads(denied.stderr)
                    == {"error_code": "mcp_approval_terminal_required"}
                    and rows(seed) == before_approve,
                    "non TTY approval accepted",
                )
                approve_pty(b5, seed, preview, key, correct=False)
            grant = approve_pty(b5, seed, preview, key)
            assert grant is not None
            gate.approvals += 1
            request["approval_token"] = grant["approval_token"]
            gate.secrets.append(grant["approval_token"])
            if revision == 1:
                for field_name, bad in (
                    ("approval_token", "wrong-token"),
                    ("confirmation_token", "wrong-token"),
                    ("preview_id", str(uuid4())),
                    ("idempotency_key", str(uuid4())),
                ):
                    gate.deny(
                        client,
                        "apply_document_update",
                        {**request, field_name: bad},
                        {"mcp_approval_required", "mcp_approval_conflict", "mcp_preview_not_found"},
                    )
                for field_name in ("confirmed", "actor", "scope_id"):
                    gate.deny(
                        client,
                        "apply_document_update",
                        {**request, field_name: True},
                        {"mcp_invalid_arguments"},
                    )
                with b5.session(
                    server_command(b5, seed, controlled=True, actor="other-actor"), temporary
                ) as other:
                    gate.initialize(other, controlled=True)
                    gate.deny(other, "apply_document_update", request, {"mcp_approval_conflict"})
                gate.closed(other)
                # 测试 owner 只改变 grant scope/expiry 做确定性负例；每次请求不得再改变它。
                with sqlite3.connect(seed.database) as connection:
                    saved = connection.execute(
                        "SELECT scope_id,created_at,expires_at FROM mcp_approvals"
                    ).fetchone()
                    connection.execute("UPDATE mcp_approvals SET scope_id=?", (uuid4().hex,))
                gate.deny(client, "apply_document_update", request, {"mcp_approval_conflict"})
                # 同一个时刻推导两端，避免两次 now 的微秒差让 TTL 超过 120 秒。
                expired_created = datetime.now(UTC) - timedelta(seconds=180)
                with sqlite3.connect(seed.database) as connection:
                    connection.execute(
                        "UPDATE mcp_approvals SET scope_id=?,created_at=?,expires_at=?",
                        (
                            saved[0],
                            expired_created.isoformat(),
                            (expired_created + timedelta(seconds=120)).isoformat(),
                        ),
                    )
                gate.deny(client, "apply_document_update", request, {"mcp_approval_expired"})
                with sqlite3.connect(seed.database) as connection:
                    connection.execute(
                        "UPDATE mcp_approvals SET created_at=?,expires_at=?", saved[1:]
                    )
                atomic_denials(gate, {**request, "_approval_id": grant["approval_id"]})
                gate.deny(
                    client, "issue_approval", {"approval_phrase": "APPROVE"}, {"mcp_tool_not_found"}
                )
            result = gate.call(client, "apply_document_update", request)
            require(
                result["committed"] is True
                and result["evaluation_status"] == expected
                and result["command_id"] == key
                and result["changed"] is True,
                "quality failure not committed or command mismatch",
            )
            commands.append(result)
            after, raw = rows(seed), seed.database.read_bytes()
            require(
                gate.call(client, "apply_document_update", request) == result,
                "same-key replay changed",
            )
            require(
                gate.call(client, "get_mutation_command", {"command_id": key}) == result,
                "command read changed",
            )
            require(rows(seed) == after and seed.database.read_bytes() == raw, "replay created job")
    gate.closed(client)
    before, files = rows(seed), b5.fingerprint(seed.root)
    with b5.session(server_command(b5, seed, controlled=False), temporary) as readonly:
        gate.initialize(readonly, controlled=False)
        read_evidence(gate, readonly, commands[-1]["document_id"])
    gate.closed(readonly)
    with b5.session(server_command(b5, seed, controlled=True, cli=True), temporary) as restarted:
        gate.initialize(restarted, controlled=True)
        for command in commands:
            require(
                gate.call(restarted, "get_mutation_command", {"command_id": command["command_id"]})
                == command,
                "restart lost committed command",
            )
        read_evidence(gate, restarted, commands[-1]["document_id"])
    gate.closed(restarted)
    require(
        rows(seed) == before and b5.fingerprint(seed.root) == files, "restart wrote knowledge/jobs"
    )
    history = verify_history(seed, commands)
    return {
        "runtime_modules": len(MODULES),
        "tools": len(b5.TOOLS) + len(CONTROLLED_TOOLS),
        "quality_cases": len(MARKERS),
        "sessions": gate.sessions,
        "pty_approvals": gate.approvals,
        "successful_calls": gate.successes,
        "rejected_calls": gate.rejects,
        "protocol_responses": gate.responses,
        "seed_files": sum(path.is_file() for path in seed.manifest.parent.rglob("*")),
        **history,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args(argv)
    try:
        # 不把任何 fixture/core 意外打印或原始异常反射到 stdout/stderr。
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            b5 = companion()
            sdk = b5.verify_identity(args.expected_version, "extra")
            require(
                not any(name.startswith("knowledge.mcp.controlled") for name in sys.modules),
                "core eagerly loaded controlled",
            )
            for dependency in ("pytest", "ruff", "mypy", "langchain_openai", "fastapi", "psycopg"):
                require(importlib.util.find_spec(dependency) is None, "dev/API dependency leaked")
            with tempfile.TemporaryDirectory(prefix="knowledge-controlled-installed-") as temporary:
                previous = os.umask(0o077)
                try:
                    counts = run_extra(b5, Path(temporary), args.expected_version)
                finally:
                    os.umask(previous)
        summary = {
            "version": args.expected_version,
            "passed": True,
            "mode": "controlled_extra",
            "sdk_version": sdk,
            "pydantic_version": importlib.metadata.version("pydantic"),
            "checks": list(CHECKS),
            "counts": counts,
        }
    except Exception:
        print("installed controlled MCP smoke failed", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
