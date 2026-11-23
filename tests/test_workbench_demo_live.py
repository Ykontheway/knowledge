"""独立真实 demo 验收；默认 skip，不改源/文档/配置，不执行预览或命令。

显式运行：
KNOWLEDGE_WORKBENCH_DEMO_LIVE=1 python -m pytest -q -s --tb=no \
    tests/test_workbench_demo_live.py
只启动统一 CLI。未知 stdout/stderr、响应正文和异常仅计算 hash，不回显。
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import selectors
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import time
import traceback
from contextlib import ExitStack, closing, suppress
from pathlib import Path
from typing import IO, Any, TypeVar, cast
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[1]
UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
USED_PORTS = {5175, 8015}
RUNTIME_ERRORS = {
    "invalid_arguments",
    "session_invalid",
    "adapter_failed",
    "receipt_missing",
    "receipt_invalid",
    "report_invalid",
    "checks_failed",
    "driver_failed",
    "timeout",
    "interrupted",
    "cleanup_unknown",
    "cleanup_forced",
    "dependency_failed",
    "runtime_failed",
    "report_missing",
}
STATUSES = {"passed", "prepared", "ready", "stopped", "failed", "blocked", "unknown"}
pytestmark = pytest.mark.skipif(
    os.environ.get("KNOWLEDGE_WORKBENCH_DEMO_LIVE") != "1",
    reason="真实联调须显式设置 KNOWLEDGE_WORKBENCH_DEMO_LIVE=1",
)


class LiveFailure(Exception):
    """仅由本文件的固定检查名称构造。"""


def require(condition: object, code: str) -> None:
    if not condition:
        raise LiveFailure(code)


T = TypeVar("T")


def present(value: T | None, code: str) -> T:
    if value is None:
        raise LiveFailure(code)
    return value


def uuid_text(value: Any) -> str:
    require(isinstance(value, str), "INVALID_UUID")
    require(str(UUID(value)) == value, "INVALID_UUID")
    return str(value)


def process_table() -> dict[int, tuple[int, int, int, str]]:
    # 内核接口；只读取身份，不读取全机 cmdline/environ。
    table = {}
    for entry in Path("/proc").iterdir():
        if entry.name.isdecimal():
            try:
                raw = (entry / "stat").read_text()
                fields = raw[raw.rindex(")") + 2 :].split()
                table[int(entry.name)] = (
                    int(fields[1]),
                    int(fields[2]),
                    int(fields[19]),
                    fields[0],
                )
            except (FileNotFoundError, ProcessLookupError, ValueError, IndexError):
                continue
    return table


def private_tree(scope: Path) -> None:
    for path in (scope, scope.parent, *scope.rglob("*")):
        info = path.lstat()
        directory = stat.S_ISDIR(info.st_mode)
        require(
            not path.is_symlink()
            and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600)
            and (directory or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1)),
            "CONTROLLED_SCOPE_NOT_PRIVATE_OWNED",
        )


def snapshot(database: Path) -> dict[str, Any]:
    # 不实例化 library；mode=ro + query_only，所有正文仅在内存中散列。
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        require(db.execute("PRAGMA quick_check").fetchall() == [("ok",)], "DB_INVALID")
        tables = [
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ]
        counts, hashes = {}, {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            rows = [
                hashlib.sha256(repr(row).encode("utf-8")).hexdigest()
                for row in db.execute(f"SELECT * FROM {quoted}")
            ]
            counts[table] = len(rows)
            hashes[table] = hashlib.sha256("".join(sorted(rows)).encode()).hexdigest()
        jobs = sorted(
            str(UUID(row[0])) for row in db.execute("SELECT id FROM auto_evaluation_jobs")
        )
    return {"counts": counts, "hashes": hashes, "jobs": jobs}


class Demo:
    def __init__(self, mode: str, ports: tuple[int, int]) -> None:
        self.mode, (self.web_port, self.api_port) = mode, ports
        self.origin = f"http://127.0.0.1:{self.web_port}"
        self.session: Path | None = None
        self.summary_path: Path | None = None
        self.database: Path | None = None
        self.manifest: Path | None = None
        self.before: dict[str, Any] | None = None
        self.known: dict[int, int] = {}
        self.ready = False
        self.output_hash = hashlib.sha256()
        self.output_bytes = 0
        self.buffer = b""
        self.output_oversize = False
        self.evidence: dict[str, Any] = {"mode": mode, "ports": list(ports)}
        self.checks: dict[str, bool] = {}
        self.failures: list[str] = []
        self.requests: list[tuple[str, str, int]] = []
        self.proc: subprocess.Popen[bytes] | None = None
        self.selector = selectors.DefaultSelector()
        scopes = ROOT / ".konwledge" / "mutation-demo"
        self.old_scopes = {p.name for p in scopes.iterdir()} if scopes.exists() else set()

    def start(self) -> None:
        args = [sys.executable, "scripts/workbench.py", "demo"]
        if self.mode == "controlled":
            args += ["--mode", "controlled", "--actor", "demo-editor"]
        args += [
            "--web-port",
            str(self.web_port),
            "--api-port",
            str(self.api_port),
            "--timeout",
            "240",
        ]
        names = {
            "PATH",
            "HOME",
            "LANG",
            "VIRTUAL_ENV",
            "UV_CACHE_DIR",
            "TMPDIR",
            "PNPM_HOME",
            "SYSTEMROOT",
            "WINDIR",
        }
        env = {k: v for k, v in os.environ.items() if k in names or k.startswith("LC_")}
        env.update(NO_COLOR="1", TERM="dumb", PYTHONDONTWRITEBYTECODE="1")
        self.proc = subprocess.Popen(
            args,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            umask=0o077,
        )
        for stream in (self.proc.stdout, self.proc.stderr):
            stream = present(stream, "OUTPUT_PIPE_MISSING")
            os.set_blocking(stream.fileno(), False)
            self.selector.register(stream, selectors.EVENT_READ, stream is self.proc.stdout)
        self.refresh()

    def refresh(self) -> dict[int, tuple[int, int, int, str]]:
        table = process_table()
        self.proc = present(self.proc, "PROCESS_MISSING")
        found = {p for p, started in self.known.items() if p in table and table[p][2] == started}
        if self.proc.poll() is None and self.proc.pid in table:
            found.add(self.proc.pid)
        while True:
            addition = {p for p, info in table.items() if info[0] in found} - found
            if not addition:
                break
            found.update(addition)
        for pid in found:
            self.known.setdefault(pid, table[pid][2])
            require(self.known[pid] == table[pid][2], "PROCESS_IDENTITY_CHANGED")
        owned = {p: table[p] for p in found}
        if self.session is None:
            for pid in owned:
                try:
                    argv = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
                except (FileNotFoundError, ProcessLookupError):
                    continue
                if b"_adapter" in argv and b"--session-id" in argv:
                    session_id = uuid_text(argv[argv.index(b"--session-id") + 1].decode("ascii"))
                    self.session = ROOT / ".konwledge" / "workbench" / session_id
                    require(self.session.is_dir(), "SESSION_MISSING")
        return owned

    def pump(self, timeout: float = 0.03) -> None:
        self.refresh()
        for key, _mask in self.selector.select(timeout):
            chunk = os.read(key.fd, 8192)
            if not chunk:
                self.selector.unregister(key.fileobj)
                cast(IO[bytes], key.fileobj).close()
                continue
            self.output_hash.update(chunk)
            self.output_bytes += len(chunk)
            if not key.data:
                continue  # stderr 永远不解析/回显。
            self.buffer += chunk
            if len(self.buffer) > 65536:
                self.output_oversize = True
                self.buffer = b""
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                if line == f"ready {self.origin}/".encode():
                    self.ready = True
                match = re.fullmatch(
                    rb"summary (\.konwledge/workbench/"
                    + UUID_PATTERN.encode()
                    + rb"/summary\.json)",
                    line,
                )
                if match:
                    path = ROOT / match[1].decode("ascii")
                    require(self.session == path.parent, "SUMMARY_SESSION_MISMATCH")
                    self.summary_path = path

    def wait_ready(self) -> None:
        self.proc = present(self.proc, "PROCESS_MISSING")
        deadline = time.monotonic() + 180
        while not self.ready and self.proc.poll() is None and time.monotonic() < deadline:
            self.pump()
        require(self.ready, "DEMO_NOT_READY")
        self.checks["ready_url"] = True
        self.evidence["ready_url"] = self.origin + "/"
        self.listeners_owned()

    def listeners_owned(self) -> None:
        inodes = set()
        for pid in self.refresh():
            try:
                for fd in (Path("/proc") / str(pid) / "fd").iterdir():
                    with suppress(FileNotFoundError, ProcessLookupError):
                        target = os.readlink(fd)
                        if target.startswith("socket:["):
                            inodes.add(target[8:-1])
            except (FileNotFoundError, ProcessLookupError):
                continue
        listeners = set()
        for name in ("tcp", "tcp6"):
            for line in (Path("/proc/net") / name).read_text().splitlines()[1:]:
                fields = line.split()
                address, port = fields[1].split(":")
                if fields[3] == "0A" and int(port, 16) in {self.web_port, self.api_port}:
                    require(
                        address == "0100007F" and fields[9] in inodes, "LISTENER_NOT_OWNED_LOOPBACK"
                    )
                    listeners.add(int(port, 16))
        require(listeners == {self.web_port, self.api_port}, "LISTENERS_MISSING")
        self.checks["owned_loopback_listeners"] = True

    def get(
        self,
        port: int,
        path: str,
        expected: int = 200,
        *,
        html: bool = False,
        reject_origin: bool = False,
    ) -> Any:
        # 唯一 HTTP 方法 GET；没有凭据头、没有 body、不允许自动重定向。
        headers = {
            "Accept": "text/html" if html else "application/json",
            "Origin": self.origin,
            "Sec-Fetch-Site": "same-origin",
        }
        if reject_origin:
            headers.update(Origin="http://127.0.0.1:1", **{"Sec-Fetch-Site": "cross-site"})
        self.pump(0)
        with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=10)) as conn:
            conn.request("GET", path, headers=headers)
            res = conn.getresponse()
            self.requests.append(("GET", path.split("?")[0], res.status))
            require(res.status == expected, f"HTTP_STATUS_{res.status}_EXPECTED_{expected}")
            if expected >= 400:
                return None  # 错误正文不读取、不传播。
            raw = res.read(8 * 1024 * 1024 + 1)
            require(len(raw) <= 8 * 1024 * 1024, "HTTP_RESPONSE_TOO_LARGE")
            if html:
                require("text/html" in (res.getheader("Content-Type") or ""), "UI_NOT_HTML")
                require(
                    b'<div id="root"></div>' in raw and b"/src/main.tsx" in raw, "UI_INDEX_MISSING"
                )
                return None
            require("application/json" in (res.getheader("Content-Type") or ""), "HTTP_NOT_JSON")
            value = json.loads(raw)
            require(isinstance(value, dict), "HTTP_NOT_OBJECT")
            return value

    def artifacts(self) -> dict[str, Any]:
        self.session = present(self.session, "SESSION_NOT_OBSERVED")
        from scripts import workbench_reports as reports

        reports.validate_session(self.session)
        component = "prepare_controlled" if self.mode == "controlled" else "seed"
        receipts = list((self.session / component).glob("*/receipt.json"))
        require(len(receipts) == 1, "PREPARE_RECEIPT_MISSING")
        receipt = reports.safe_read_json(receipts[0], allowed_root=self.session)
        require(
            receipt["session_id"] == self.session.name
            and receipt["component"] == component
            and receipt["invocation_id"] == receipts[0].parent.name
            and receipt["status"] == "completed",
            "PREPARE_RECEIPT_INVALID",
        )
        for name, reference in receipt["artifacts"].items():
            path = ROOT / reference
            require(
                reports.artifact_reference(path, session=self.session, component=component)
                == reference,
                "ARTIFACT_REFERENCE_INVALID",
            )
            if name == "database":
                self.database = path
            elif name == "manifest":
                self.manifest = path
            else:
                raise LiveFailure("ARTIFACT_NAME_INVALID")
        self.database = present(self.database, "DATABASE_MISSING")
        if self.mode == "controlled":
            self.manifest = present(self.manifest, "MANIFEST_MISSING")
            scope = self.manifest.parent
            require(
                scope.parent == ROOT / ".konwledge" / "mutation-demo"
                and uuid_text(scope.name) not in self.old_scopes,
                "CONTROLLED_SCOPE_NOT_FRESH",
            )
            private_tree(scope)
            manifest = reports.safe_read_json(self.manifest, allowed_root=scope)
            require(
                manifest["scope_id"] == scope.name
                and scope / manifest["database"] == self.database,
                "SCOPE_DB_MISMATCH",
            )
            self.checks["fresh_private_owned_scope"] = True
        allowed = self.manifest.parent if self.manifest is not None else self.session
        seed = reports.safe_read_json(self.database.parent / "report.json", allowed_root=allowed)
        require(seed["status"] == "passed", "SEED_NOT_PASSED")
        seed_jobs = sorted(uuid_text(step["job"]["id"]) for step in seed["steps"])
        before = snapshot(self.database)
        require(len(seed_jobs) == 3 and before["jobs"] == seed_jobs, "NON_SEED_JOBS_PRESENT")
        require(
            before["counts"].get("mutation_commands", 0) == 0
            and before["counts"].get("mutation_previews", 0) == 0,
            "MUTATIONS_PRESENT_BEFORE_GET",
        )
        self.checks["only_three_seed_jobs"] = True
        return before

    def inspect(self) -> None:
        before = self.artifacts()
        self.before = before
        self.database = present(self.database, "DATABASE_MISSING")
        for path in ("/", "/index", "/index.html"):
            self.get(self.web_port, path, html=True)
        self.checks["ui_http_index"] = True
        self.get(self.api_port, "/v1/management/jobs", expected=401)
        self.get(self.web_port, "/v1/management/jobs", expected=403, reject_origin=True)
        jobs = self.get(self.web_port, "/v1/management/jobs?limit=100")
        items = jobs["items"]
        require(
            jobs["total"] == 3
            and len(items) == 3
            and [item["status"] for item in items] == ["passed", "failed", "passed"]
            and sorted(uuid_text(item["id"]) for item in items) == before["jobs"],
            "MANAGEMENT_JOBS_INVALID",
        )
        detail = self.get(self.web_port, "/v1/management/jobs/" + uuid_text(items[1]["id"]))
        require(
            detail["status"] == "failed" and bool(detail["report"]),
            "MANAGEMENT_FAILED_JOB_NOT_READABLE",
        )
        self.checks["management_get"] = True
        self.checks["backend_auth_and_proxy_origin_guards"] = True
        if self.mode == "readonly":
            self.get(self.api_port, "/v1/mutations/session", expected=404)
            self.get(self.web_port, "/v1/mutations/session", expected=503)
            self.checks["readonly_b4_backend_404"] = True
            self.checks["readonly_b4_proxy_disabled_503"] = True
        else:
            self.get(self.api_port, "/v1/mutations/session", expected=401)
            self.get(self.web_port, "/v1/mutations/session", expected=403, reject_origin=True)
            session = self.get(self.web_port, "/v1/mutations/session")
            require(
                session["role"] == "demo_editor"
                and session["actor_id"] == "demo-editor"
                and session["capabilities"] == ["document.update"],
                "CONTROLLED_ROLE_ACTOR_INVALID",
            )
            self.manifest = present(self.manifest, "MANIFEST_MISSING")
            require(
                uuid_text(session["scope_id"]) == self.manifest.parent.name,
                "SESSION_SCOPE_MISMATCH",
            )
            require(bool(session["sources"]), "CONTROLLED_SOURCES_MISSING")
            from scripts import workbench_reports as reports

            manifest = reports.safe_read_json(self.manifest, allowed_root=self.manifest.parent)
            require(
                sorted(uuid_text(s["source_id"]) for s in session["sources"])
                == sorted(manifest["allowed_source_ids"]),
                "SOURCE_ALLOWLIST_MISMATCH",
            )
            for source in session["sources"]:
                document = self.get(
                    self.web_port, "/v1/mutations/documents/" + uuid_text(source["document_id"])
                )
                require(
                    all(
                        document[k] == source[k]
                        for k in ("source_id", "document_id", "checksum", "content_type")
                    )
                    and document["scope_id"] == session["scope_id"]
                    and isinstance(document["text"], str)
                    and bool(document["text"]),
                    "CONTROLLED_DOCUMENT_SOURCE_MISMATCH",
                )
            self.checks["controlled_session_ready_editor_server_actor"] = True
            self.checks["controlled_get_documents_sources"] = True
        require(snapshot(self.database) == before, "GET_CHANGED_DATABASE")
        self.checks["get_no_commands_previews_new_jobs"] = True

    def send_owned(self, signum: int, *, parent_only: bool = False) -> None:
        self.proc = present(self.proc, "PROCESS_MISSING")
        for pid, info in self.refresh().items():
            if info[3] == "Z" or (parent_only and pid != self.proc.pid):
                continue
            with suppress(ProcessLookupError):
                fd = os.pidfd_open(pid)
                try:
                    again = process_table().get(pid)
                    if again is not None and again[2] == info[2]:
                        signal.pidfd_send_signal(fd, signum)
                finally:
                    os.close(fd)

    def stop(self) -> None:
        if self.proc is None:
            self.selector.close()
            return
        if self.proc.poll() is None:
            self.send_owned(signal.SIGINT, parent_only=True)
            self.checks["sigint_parent"] = True
        end = time.monotonic() + 40
        while self.proc.poll() is None and time.monotonic() < end:
            self.pump()
        # 应急只向已证明 PID+starttime 归属本次 demo 的进程发信号，绝不按名称/端口 kill。
        if self.proc.poll() is None or self.refresh():
            self.failures.append("EMERGENCY_CLEANUP_REQUIRED")
            for signum in (signal.SIGTERM, signal.SIGKILL):
                self.send_owned(signum)
                end = time.monotonic() + 5
                while self.refresh() and time.monotonic() < end:
                    self.pump()
        self.proc.poll()
        for _ in range(20):
            if not self.selector.get_map():
                break
            self.pump()
        for key in list(self.selector.get_map().values()):
            self.selector.unregister(key.fileobj)
            cast(IO[bytes], key.fileobj).close()
        self.selector.close()
        self.evidence.update(
            exit_code=self.proc.returncode,
            output_sha256=self.output_hash.hexdigest(),
            output_bytes=self.output_bytes,
        )
        self.checks["no_owned_orphans"] = not self.refresh()
        self.checks["ports_closed"] = all(
            self.port_closed(p) for p in (self.web_port, self.api_port)
        )
        self.checks["safe_exit_code"] = self.proc.returncode == 1
        if self.summary_path is None and self.session is not None:
            candidate = self.session / "summary.json"
            if candidate.is_file():
                self.summary_path = candidate
        self.summary_path = present(self.summary_path, "SUMMARY_MISSING")
        self.session = present(self.session, "SESSION_NOT_OBSERVED")
        from scripts import workbench_reports as reports

        summary = reports.safe_read_json(self.summary_path, allowed_root=self.session)
        self.evidence["summary"] = self.summary_path.relative_to(ROOT).as_posix()
        require(
            summary["session_id"] == self.session.name
            and summary["command"] == "demo"
            and summary["mode"] == self.mode,
            "SUMMARY_IDENTITY_INVALID",
        )
        self.evidence["summary_status"] = (
            summary["status"] if summary["status"] in STATUSES else "unknown"
        )
        self.checks["summary_stopped_not_passed"] = summary["status"] == "stopped"
        components = summary["components"]
        expected = ["prepare_controlled" if self.mode == "controlled" else "seed", "launcher"]
        require(
            [item["component"] for item in components] == expected, "SUMMARY_COMPONENTS_INVALID"
        )
        self.evidence["components"] = [
            {
                "component": item["component"],
                "status": item["status"] if item["status"] in STATUSES else "unknown",
                "exit_code": item["exit_code"] if type(item["exit_code"]) is int else None,
                "cleanup_verified": item["cleanup_verified"] is True,
                "error_code": item["error_code"]
                if item["error_code"] in RUNTIME_ERRORS | {None}
                else "runtime_failed",
            }
            for item in components
        ]
        self.checks["all_cleanup_verified"] = all(
            item["cleanup_verified"] is True for item in components
        )
        self.checks["launcher_stopped_130"] = (
            components[-1]["status"] == "stopped" and components[-1]["exit_code"] == 130
        )
        self.checks["no_output_oversize"] = not self.output_oversize
        if self.before is not None:
            self.database = present(self.database, "DATABASE_MISSING")
            after = snapshot(self.database)
            self.checks["stopped_no_commands_previews_new_jobs"] = after == self.before
            self.evidence.update(
                seed_jobs=3,
                new_jobs=len(set(after["jobs"]) - set(self.before["jobs"])),
                mutation_commands=after["counts"].get("mutation_commands", 0),
                mutation_previews=after["counts"].get("mutation_previews", 0),
            )
            if self.manifest is not None:
                private_tree(self.manifest.parent)

    @staticmethod
    def port_closed(port: int) -> bool:
        with closing(socket.socket()) as sock:
            sock.settimeout(0.3)
            return sock.connect_ex(("127.0.0.1", port)) != 0

    def run(self) -> None:
        try:
            self.start()
            self.wait_ready()
            self.inspect()
        except Exception as error:
            self.failure(error)
        finally:
            try:
                self.stop()
            except Exception as error:
                self.failure(error)
        self.evidence["checks"] = self.checks
        self.failures.extend(name.upper() for name, okay in self.checks.items() if not okay)
        self.evidence["failures"] = self.failures
        self.evidence["http_methods"] = sorted({method for method, _path, _code in self.requests})
        # 不回显 document/source/job ID、原始 HTTP/CLI 字节或异常堆栈。
        print("demo_live " + json.dumps(self.evidence, ensure_ascii=False, sort_keys=True))
        if self.failures:
            pytest.fail("DEMO_LIVE_FAILED:" + ",".join(self.failures), pytrace=False)

    def failure(self, error: Exception) -> None:
        self.failures.append(
            str(error) if isinstance(error, LiveFailure) else "LIVE_UNEXPECTED_ERROR"
        )
        trace = "".join(traceback.format_exception(error)).encode("utf-8", "replace")
        self.evidence.setdefault("trace_sha256", []).append(hashlib.sha256(trace).hexdigest())


@pytest.mark.parametrize("mode", ["readonly", "controlled"])
def test_workbench_demo_live(mode: str) -> None:
    require(
        sys.platform.startswith("linux")
        and hasattr(os, "pidfd_open")
        and hasattr(signal, "pidfd_send_signal"),
        "LINUX_PIDFD_REQUIRED",
    )
    # 同时 bind 两个空闲 loopback 端口，排除默认端口与本文件前一次 demo 的端口。
    with ExitStack() as stack:
        ports: list[int] = []
        while len(ports) < 2:
            sock = stack.enter_context(socket.socket())
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            if port not in USED_PORTS:
                ports.append(port)
                USED_PORTS.add(port)
    Demo(mode, (ports[0], ports[1])).run()
