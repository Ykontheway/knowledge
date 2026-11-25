"""B4 隔离真实 HTTP/UI/core 验收；只写本次 prepare 生成的演示库，输出不含正文或凭据。"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import re
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol, TypedDict, cast
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
FIXED_TEST = "src/mutations/tests/live-acceptance.test.ts"
ACTOR = "demo-editor"
HASH = re.compile(r"^[0-9a-f]{64}$")
STATUS = {"running", "passed", "failed", "skipped", "pending", "not_triggered", "unavailable"}


class AcceptanceError(RuntimeError):
    """只携带固定错误码；绝不转发底层异常。"""


class PreparedDemo(TypedDict):
    status: str
    manifest: str
    database: str
    scope_id: str
    source_ids: list[str]


class SnapshotResult(TypedDict):
    core_hash: str
    counts: dict[str, int]
    config_hash: str | None
    dataset_hash: str | None
    quick_check: bool
    foreign_keys_valid: bool


class PrepareModule(Protocol):
    DemoError: type[Exception]

    def no_symlinks(self, path: Path) -> Path: ...

    def read_json(self, path: Path) -> dict[str, Any]: ...

    def validate_demo(self, manifest_path: Path, database_path: Path) -> Path: ...

    def private_owned(self, path: Path, mode: int, *, directory: bool = False) -> None: ...

    def prepare(self) -> PreparedDemo: ...


def require(value: object, code: str) -> None:
    if not value:
        raise AcceptanceError(code)


def module(name: str) -> Any:
    return importlib.import_module(f"scripts.{name}" if __package__ else name)


def prepare_module() -> PrepareModule:
    return cast(PrepareModule, module("prepare_mutation_demo"))


def json_object(value: object, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AcceptanceError(code)
    return value


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def safe_environment() -> dict[str, str]:
    allowed = {"PATH", "HOME", "LANG", "UV_CACHE_DIR", "TMPDIR", "SYSTEMROOT"}
    result = {k: v for k, v in os.environ.items() if k in allowed or k.startswith("LC_")}
    result.update({"NO_COLOR": "1", "TERM": "dumb", "PYTHONDONTWRITEBYTECODE": "1"})
    return result


def validate_origin(origin: str) -> str:
    require(re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}", origin), "INVALID_ORIGIN")
    port = int(origin.rsplit(":", 1)[1])
    require(port <= 65535 and port not in {5175, 8015}, "INVALID_PORT")
    return origin


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    if port in {5175, 8015}:
        return free_port()
    return port


def owned_database(manifest: Path) -> Path:
    prepare = prepare_module()
    manifest = prepare.no_symlinks(manifest)
    payload = prepare.read_json(manifest)
    database_name = payload.get("database")
    if not isinstance(database_name, str):
        raise prepare.DemoError("INVALID_DEMO_JSON")
    database = prepare.no_symlinks(manifest.parent / database_name)
    prepare.validate_demo(manifest, database)
    return database


def snapshot(database: Path) -> SnapshotResult:
    """一致性只读事务；SQL 仅在已通过所有权校验的库上执行。正文/URI 只参与哈希。"""
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        names = sorted(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        )
        require(
            all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in names),
            "INVALID_TABLE_NAME",
        )
        hashes: dict[str, str] = {}
        counts: dict[str, int] = {}
        for name in names:
            raw_rows = connection.execute(f'SELECT * FROM "{name}"').fetchall()
            # FTS shadow tables 含 BLOB；仅哈希，不将二进制/正文写进报告。
            rows = [
                tuple(
                    hashlib.sha256(item).hexdigest() if isinstance(item, bytes) else item
                    for item in row
                )
                for row in raw_rows
            ]
            rows.sort(key=lambda row: json.dumps(row, ensure_ascii=False))
            counts[name] = len(rows)
            if name != "mutation_previews":
                hashes[name] = digest(rows)
        return {
            "core_hash": digest(hashes),
            "counts": counts,
            "config_hash": hashes.get("auto_evaluation_config"),
            "dataset_hash": hashes.get("evaluation_sets"),
            "quick_check": connection.execute("PRAGMA quick_check").fetchall() == [("ok",)],
            "foreign_keys_valid": not connection.execute("PRAGMA foreign_key_check").fetchall(),
        }
    finally:
        connection.close()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def http(
    origin: str,
    path: str,
    *,
    body: object = None,
    key: str | None = None,
    browser_origin: str | None = None,
    expected: int = 200,
) -> dict[str, Any]:
    validate_origin(origin)
    require(path.startswith(("/v1/", "/health")) and not path.startswith("//"), "INVALID_HTTP_PATH")
    headers = {"Accept": "application/json"}
    if browser_origin is not None:
        headers["Origin"] = browser_origin
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"
    if body is not None:
        headers.update(
            {"Content-Type": "application/json", "X-Knowledge-Intent": "document-update"}
        )
    request = Request(
        origin + path,
        headers=headers,
        data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
    )
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(request, timeout=20)
    except HTTPError as error:
        response = error
    except Exception:
        raise AcceptanceError("HTTP_UNAVAILABLE") from None
    with response:
        require(response.status == expected, f"HTTP_STATUS_{response.status}_EXPECTED_{expected}")
        # 错误体不读取、不反射。
        if expected >= 400:
            return {}
        require(response.headers.get_content_type() == "application/json", "HTTP_NOT_JSON")
        raw = response.read(2 * 1024 * 1024 + 1)
        require(len(raw) <= 2 * 1024 * 1024, "HTTP_TOO_LARGE")
        return json_object(json.loads(raw), "HTTP_NOT_JSON")


class Children:
    def __init__(self) -> None:
        self.items: list[tuple[subprocess.Popen[bytes], Any]] = []

    def start(self, argv: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
        log = tempfile.TemporaryFile()  # noqa: SIM115 -- 生命周期由 Children.close 统一管理
        try:
            child = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=log,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            log.close()
            raise AcceptanceError("CHILD_START_FAILED") from None
        self.items.append((child, log))
        return child

    def stop(self, child: subprocess.Popen[bytes]) -> None:
        # 也终止 pnpm/Vite/Vitest 的后代；所有进程组由本 driver 创建。
        with suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=8)
        with suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGKILL)

    def close(self) -> list[dict[str, object]]:
        results = []
        for child, log in reversed(self.items):
            stopped = True
            try:
                self.stop(child)
            except (OSError, subprocess.SubprocessError):
                stopped = False
            log.seek(0)
            hasher = hashlib.sha256()
            size = 0
            while True:
                chunk = log.read(65536)
                if chunk == b"":
                    break
                size += len(chunk)
                hasher.update(chunk)
            results.append(
                {
                    "output_hash": hasher.hexdigest(),
                    "output_bytes": size,
                    "stopped": stopped and child.poll() is not None,
                }
            )
            log.close()
        self.items.clear()
        return results


def wait_ready(child: subprocess.Popen[bytes], probe: Any, timeout: int = 45) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        require(child.poll() is None, "CHILD_EXITED_BEFORE_READY")
        try:
            probe()
            return
        except Exception:
            time.sleep(0.15)
    raise AcceptanceError("CHILD_READY_TIMEOUT")


def vitest_argv() -> list[str]:
    # 无任意测试文件/命令透传，也不使用 shell。
    return ["pnpm", "exec", "vitest", "run", FIXED_TEST]


def safe_report(value: object) -> None:
    """报告为封闭值域，拒绝正文、路径、token、错误详情，含嵌套字段。"""
    if isinstance(value, float):
        require(math.isfinite(value), "UNSAFE_REPORT_VALUE")
        return
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, str):
        if HASH.fullmatch(value) or value in STATUS:
            return
        try:
            require(str(UUID(value)) == value, "UNSAFE_REPORT_VALUE")
            return
        except (ValueError, AcceptanceError):
            raise AcceptanceError("UNSAFE_REPORT_VALUE") from None
    if isinstance(value, list):
        for item in value:
            safe_report(item)
        return
    if isinstance(value, dict):
        for name, item in value.items():
            require(
                isinstance(name, str)
                and re.fullmatch(r"[a-z][a-z0-9_]*", name)
                and not re.search(r"text|token|secret|key$|path|stack|actor", name),
                "UNSAFE_REPORT_FIELD",
            )
            safe_report(item)
        return
    raise AcceptanceError("UNSAFE_REPORT_VALUE")


def write_report(path: Path, value: object) -> None:
    safe_report(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


class Driver:
    def __init__(self, *, frontend: bool = True) -> None:
        self.frontend = frontend
        self.children = Children()
        self.read_credential = secrets.token_urlsafe(32)
        self.write_credential = secrets.token_urlsafe(32)
        self.report: dict[str, Any] = {"status": "running", "checks": {}, "commands": []}
        self.manifest: Path | None = None
        self.database: Path | None = None

    def check(self, name: str, condition: object) -> None:
        self.report["checks"][name] = bool(condition)
        require(condition, "CHECK_FAILED_" + name.upper())

    def api_start(self, actor: str = ACTOR) -> subprocess.Popen[bytes]:
        assert self.manifest and self.database
        env = safe_environment()
        env.update(
            {
                "KNOWLEDGE_API_KEY": self.read_credential,
                "KNOWLEDGE_MUTATION_KEY": self.write_credential,
                "KNOWLEDGE_MUTATION_ACTOR": actor,
            }
        )
        child = self.children.start(
            [
                sys.executable,
                "-m",
                "knowledge",
                "serve",
                "--database",
                str(self.database),
                "--host",
                "127.0.0.1",
                "--port",
                str(self.api_port),
                "--enable-management",
                "--enable-mutations",
                "--mutation-manifest",
                str(self.manifest),
                "--mutation-origin",
                self.web_origin,
            ],
            ROOT,
            env,
        )
        wait_ready(child, lambda: http(self.api_origin, "/health"))
        return child

    def mutation(self, path: str, body: object = None, expected: int = 200) -> dict[str, Any]:
        return http(
            self.api_origin,
            "/v1/mutations/" + path,
            body=body,
            key=self.write_credential,
            browser_origin=self.web_origin,
            expected=expected,
        )

    def web_test(self, phase: str, **extra: str) -> dict[str, Any]:
        assert self.manifest and self.database
        prepare = prepare_module()
        target = self.manifest.parent / f"frontend-{phase}.json"
        env = safe_environment()
        env.update(
            {
                "KNOWLEDGE_MUTATION_ACCEPTANCE": "1",
                "B4_PHASE": phase,
                "B4_WEB_ORIGIN": self.web_origin,
                "B4_MANIFEST": str(self.manifest),
                "B4_PYTHON": sys.executable,
                "B4_REPORT": str(target),
                "B4_DOCUMENT_ID": self.original["document_id"],
                "B4_SOURCE_ID": self.original["source_id"],
                "B4_SCOPE_ID": self.scope_id,
                **extra,
            }
        )
        child = self.children.start(vitest_argv(), ROOT / "web", env)
        try:
            code = child.wait(timeout=150)
        except subprocess.TimeoutExpired:
            raise AcceptanceError("FRONTEND_TIMEOUT") from None
        require(code == 0, "FRONTEND_FAILED")
        prepare.private_owned(target, 0o600)
        value = prepare.read_json(target)
        safe_report(value)
        require(value.get("status") == "passed", "FRONTEND_REPORT_FAILED")
        return value

    def current(self) -> dict[str, Any]:
        session = self.mutation("session")
        source = next(
            item for item in session["sources"] if item["source_id"] == self.original["source_id"]
        )
        return self.mutation("documents/" + source["document_id"])

    def apply(self, content: str, expected_status: str) -> dict[str, Any]:
        from knowledge.mutations.models import CommandDTO, PreviewDTO

        assert self.database
        current = self.current()
        before = snapshot(self.database)
        payload = {
            "scope_id": self.scope_id,
            "source_id": current["source_id"],
            "document_id": current["document_id"],
            "expected_checksum": current["checksum"],
            "text": content,
        }
        preview = self.mutation("previews", payload)
        PreviewDTO.model_validate(preview)
        self.check(
            "preview_core_unchanged_" + expected_status,
            before["core_hash"] == snapshot(self.database)["core_hash"],
        )
        self.check(
            "preview_complete_" + expected_status,
            len(preview["diff"]) == sum(preview["counts"].values()) and preview["changed"],
        )
        request = {
            "preview_id": preview["preview_id"],
            "confirmation_token": preview["confirmation_token"],
            "idempotency_key": str(uuid4()),
            "confirmed": True,
        }
        self.mutation(
            "commands", {**request, "confirmation_token": secrets.token_urlsafe(32)}, expected=403
        )
        self.mutation("commands", request, expected=200)
        command = self.mutation("commands/" + request["idempotency_key"])
        CommandDTO.model_validate(command)
        self.check(
            "command_" + expected_status,
            command["committed"] is True
            and command["evaluation_status"] == expected_status
            and len(command["job_ids"]) == 1,
        )
        stable = snapshot(self.database)
        replay = self.mutation("commands", request)
        self.check(
            "replay_" + expected_status, replay == command and stable == snapshot(self.database)
        )
        self.mutation("commands", {**request, "preview_id": str(uuid4())}, expected=409)
        self.check(
            "rejected_request_no_write_" + expected_status, stable == snapshot(self.database)
        )
        return command

    def context(self, query: str, *, include_stale: bool = False) -> Any:
        from knowledge.context import ContextPacket

        result = http(
            self.api_origin,
            "/v1/context",
            key=self.read_credential,
            body={
                "query": query,
                "source_ids": [self.original["source_id"]],
                "include_stale": include_stale,
            },
        )
        return ContextPacket.model_validate_json(json.dumps(result))

    def audit(self, commands: list[dict[str, Any]]) -> None:
        from knowledge.storage.auto_evaluation import is_knowledge_revision
        from knowledge.storage.tables import RevisionRow

        assert self.database
        db = sqlite3.connect(f"{self.database.as_uri()}?mode=ro", uri=True)
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            for index, command in enumerate(commands):
                uid = UUID(command["command_id"]).hex
                row = db.execute(
                    "SELECT actor_id, scope_id, idempotency_key, revision_ids FROM "
                    "mutation_commands WHERE id=?",
                    (uid,),
                ).fetchone()
                revisions = db.execute(
                    "SELECT id, author, payload, entity_type FROM revisions WHERE "
                    "json_extract(payload, '$.command_id')=?",
                    (command["command_id"],),
                ).fetchall()
                self.check(
                    f"audit_identity_{index}",
                    bool(row) and row[:3] == (ACTOR, UUID(self.scope_id).hex, uid),
                )
                revision_ids = {str(UUID(item[0])) for item in revisions}
                self.check(
                    f"audit_durable_revision_chain_{index}",
                    revision_ids == set(command["revision_ids"])
                    and all(item[1] == ACTOR for item in revisions)
                    and set(json.loads(row[3])) == set(command["revision_ids"]),
                )
                triggers = {
                    str(UUID(revision[0]))
                    for revision in revisions
                    if is_knowledge_revision(
                        RevisionRow(
                            id=UUID(revision[0]),
                            entity_type=revision[3],
                            entity_id=uuid4(),
                            revision=1,
                            change_type="modified",
                            created_at="",
                            author=revision[1],
                            payload=json_object(
                                json.loads(revision[2]), "INVALID_REVISION_PAYLOAD"
                            ),
                        )
                    )
                }
                for job_id in command["job_ids"]:
                    job = db.execute(
                        "SELECT trigger_revision_ids FROM auto_evaluation_jobs WHERE id=?",
                        (UUID(job_id).hex,),
                    ).fetchone()
                    self.check(
                        f"audit_job_chain_{index}",
                        bool(job) and set(json.loads(job[0])) == triggers and bool(triggers),
                    )
        finally:
            db.close()

    def execute(self) -> None:
        prepared = prepare_module().prepare()
        self.manifest = ROOT / prepared["manifest"]
        self.database = owned_database(self.manifest)
        self.scope_id = prepared["scope_id"]
        self.report["scope_id"] = self.scope_id
        self.api_port = free_port()
        self.web_port = free_port()
        while self.web_port == self.api_port:
            self.web_port = free_port()
        self.api_origin = validate_origin(f"http://127.0.0.1:{self.api_port}")
        self.web_origin = validate_origin(f"http://127.0.0.1:{self.web_port}")
        self.check("owned_private_manifest_database", True)
        before = snapshot(self.database)
        api = self.api_start()
        session = self.mutation("session")
        self.check(
            "session_server_identity",
            session["actor_id"] == ACTOR
            and session["scope_id"] == self.scope_id
            and sorted(s["source_id"] for s in session["sources"]) == prepared["source_ids"],
        )
        real = module("real_knowledge_acceptance")
        shared_docs_hash = digest(
            [hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in real.SOURCE_PATHS]
        )
        documents = [self.mutation("documents/" + s["document_id"]) for s in session["sources"]]
        self.original = next(d for d in documents if f"## {real.AUTO_HEADING}\n" in d["text"])
        self.check("allowed_target", self.original["source_id"] in prepared["source_ids"])
        self.check(
            "startup_reads_core_unchanged",
            before["core_hash"] == snapshot(self.database)["core_hash"],
        )
        sample = {
            "scope_id": self.scope_id,
            "source_id": self.original["source_id"],
            "document_id": self.original["document_id"],
            "expected_checksum": self.original["checksum"],
            "text": self.original["text"],
        }
        http(
            self.api_origin,
            "/v1/mutations/previews",
            body=sample,
            key=self.read_credential,
            browser_origin=self.web_origin,
            expected=403,
        )
        http(
            self.api_origin,
            "/v1/mutations/previews",
            body=sample,
            key=self.write_credential,
            browser_origin="http://127.0.0.1:1",
            expected=403,
        )
        self.mutation("previews", {**sample, "source_id": str(uuid4())}, expected=403)
        self.mutation("previews", {**sample, "scope_id": str(uuid4())}, expected=403)
        self.check("security_rejections_no_write", before == snapshot(self.database))
        if self.frontend:
            env = safe_environment()
            env.update(
                {
                    "KNOWLEDGE_MANAGEMENT_ORIGIN": self.api_origin,
                    "KNOWLEDGE_API_KEY": self.read_credential,
                    "KNOWLEDGE_MUTATION_KEY": self.write_credential,
                    "KNOWLEDGE_MUTATION_ENABLED": "1",
                }
            )
            web = self.children.start(
                [
                    "pnpm",
                    "exec",
                    "vite",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(self.web_port),
                    "--strictPort",
                ],
                ROOT / "web",
                env,
            )
            wait_ready(
                web,
                lambda: http(
                    self.web_origin, "/v1/mutations/session", browser_origin=self.web_origin
                ),
            )
            http(
                self.web_origin,
                "/v1/mutations/previews",
                body=sample,
                browser_origin="http://127.0.0.1:1",
                expected=403,
            )
            ui = self.web_test("update")
            self.report["frontend_update"] = ui
            positive = self.mutation("commands/" + ui["command_id"])
        else:
            positive = self.apply(
                self.original["text"].replace(real.POSITIVE_OLD, real.POSITIVE_NEW)
                + "\n\nB4safeupdate 仅在授权演示副本验证安全可检索说明。",
                "passed",
            )
            self.report["frontend_update"] = {"status": "skipped"}
        self.check(
            "positive_passed", positive["committed"] and positive["evaluation_status"] == "passed"
        )
        self.report["commands"].append(positive)
        packet = self.context("B4safeupdate")
        self.check(
            "safe_update_retrievable",
            any(
                "B4safeupdate" in block.citation.quote
                and str(block.citation.document_id) == positive["document_id"]
                for block in packet.blocks
            ),
        )
        positive_text = self.current()["text"]
        broken = real.replace_section_body(positive_text, real.AUTO_HEADING)
        fault = self.apply(broken, "failed")
        self.report["commands"].append(fault)
        self.check("failure_head_committed", self.current()["document_id"] == fault["document_id"])
        self.check(
            "fault_no_stale_evidence_fallback",
            not self.context(real.CASES[0].query).blocks
            and not self.context(real.CASES[0].query, include_stale=True).blocks,
        )
        restored = self.apply(self.original["text"], "passed")
        self.report["commands"].append(restored)
        self.check(
            "historical_checksum_reuse",
            restored["document_id"] == self.original["document_id"]
            and self.current()["checksum"] == self.original["checksum"],
        )
        self.audit([positive, fault, restored])
        self.check(
            "restored_gold_evidence_retrievable", bool(self.context(real.CASES[0].query).blocks)
        )
        final = snapshot(self.database)
        self.check(
            "fixed_config_dataset",
            before["config_hash"] == final["config_hash"]
            and before["dataset_hash"] == final["dataset_hash"],
        )
        self.check(
            "exactly_three_new_jobs_commands",
            final["counts"]["auto_evaluation_jobs"] - before["counts"]["auto_evaluation_jobs"] == 3
            and final["counts"]["mutation_commands"] - before["counts"]["mutation_commands"] == 3,
        )
        jobs = []
        for command in [positive, fault, restored]:
            job = http(
                self.api_origin,
                "/v1/management/jobs/" + command["job_ids"][0],
                key=self.read_credential,
            )
            require(job["report"] is not None, "JOB_REPORT_MISSING")
            jobs.append(job)
        self.check(
            "jobs_fixed_pin",
            len(
                {
                    (
                        j["dataset_id"],
                        j["dataset_version"],
                        j["dataset_hash"],
                        j["config_fingerprint"],
                    )
                    for j in jobs
                }
            )
            == 1,
        )
        self.report["jobs"] = [
            {
                "id": j["id"],
                "status": j["status"],
                "dataset_hash": j["dataset_hash"],
                "config_fingerprint": j["config_fingerprint"],
                "metrics": j["report"]["metrics"],
            }
            for j in jobs
        ]
        self.children.stop(api)
        foreign = self.api_start("foreign-editor")
        self.mutation("commands/" + positive["command_id"], expected=404)
        self.check("recovery_identity_bound", final == snapshot(self.database))
        self.children.stop(foreign)
        api = self.api_start()
        self.check(
            "restart_same_manifest_recovers",
            all(
                self.mutation("commands/" + c["command_id"]) == c
                for c in [positive, fault, restored]
            ),
        )
        if self.frontend:
            self.report["frontend_recovery"] = self.web_test(
                "recover",
                B4_COMMAND_ID=positive["command_id"],
                B4_FAULT_JOB=fault["job_ids"][0],
                B4_RESTORE_JOB=restored["job_ids"][0],
                B4_POSITIVE_JOB=positive["job_ids"][0],
                B4_FAULT_DOCUMENT=fault["document_id"],
            )
        else:
            self.report["frontend_recovery"] = {"status": "skipped"}
        self.check("recovery_gets_no_write", final == snapshot(self.database))
        self.check(
            "shared_original_docs_unchanged",
            shared_docs_hash
            == digest(
                [
                    hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                    for name in real.SOURCE_PATHS
                ]
            ),
        )
        self.report["readonly_integrity"] = final
        self.report["status"] = "passed"

    def run(self) -> tuple[dict[str, Any], Path | None]:
        previous_umask = os.umask(0o077)
        error_hash = None
        try:
            self.execute()
        except Exception as error:
            self.report["status"] = "failed"
            # 异常类型/固定错误码只存哈希；不输出 path/body/token/raw stack。
            error_hash = digest(
                [
                    type(error).__name__,
                    str(error) if isinstance(error, AcceptanceError) else "redacted",
                ]
            )
        finally:
            try:
                self.report["children"] = self.children.close()
                self.report["children_stopped"] = all(c["stopped"] for c in self.report["children"])
            finally:
                os.umask(previous_umask)
        if not self.report["children_stopped"]:
            self.report["status"] = "failed"
        if error_hash:
            self.report["error_hash"] = error_hash
        # CommandDTO 白名单去 actor，其他字段仅 IDs/hash/count/status，不输出 request。
        self.report["commands"] = [
            {k: v for k, v in c.items() if k != "actor_id"} for c in self.report["commands"]
        ]
        target = self.manifest.parent / "b4-acceptance-report.json" if self.manifest else None
        if target:
            write_report(target, self.report)
        return self.report, target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-frontend", action="store_true", help="仅验收后台，报告明确前端 skipped"
    )
    parser.add_argument(
        "--snapshot-manifest", type=Path, help="只读校验本工具生成目录，输出哈希/计数"
    )
    args = parser.parse_args(argv)
    if args.snapshot_manifest:
        try:
            result = snapshot(owned_database(args.snapshot_manifest))
            safe_report(result)
            print(json.dumps(result))
            return 0
        except Exception:
            print(json.dumps({"status": "failed"}))
            return 1
    driver = Driver(frontend=not args.skip_frontend)
    try:
        report, _ = driver.run()
    except Exception:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "children_stopped": driver.report.get("children_stopped", False),
                }
            )
        )
        return 1
    print(
        json.dumps(
            {k: report[k] for k in ("status", "children_stopped", "scope_id") if k in report},
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
