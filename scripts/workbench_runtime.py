"""统一入口的隔离编排；不修改原 driver，不传播原始日志或异常。"""

from __future__ import annotations

import ctypes
import http.client
import importlib
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, redirect_stderr, redirect_stdout, suppress
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType, ModuleType
from typing import Any, Literal, TypedDict, cast
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = (
    "seed",
    "management",
    "evaluation",
    "mutations",
    "distribution",
    "prepare_controlled",
    "launcher",
)
ERROR_CODES = frozenset(
    {
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
)
RECEIPT_KEYS = frozenset(
    {
        "session_id",
        "component",
        "invocation_id",
        "status",
        "report_paths",
        "artifacts",
        "error_code",
    }
)


class Receipt(TypedDict):
    session_id: str
    component: str
    invocation_id: str
    status: Literal["completed", "failed", "stopped"]
    report_paths: list[str]
    artifacts: dict[str, str]
    error_code: str | None


class RuntimeErrorCode(Exception):
    """只承载固定枚举；绝不保存底层异常。"""

    def __init__(self, code: str) -> None:
        self.code = code if code in ERROR_CODES else "runtime_failed"
        super().__init__(self.code)


def reports() -> ModuleType:
    # list/参数预检不加载业务依赖，也不需要 reports 已安装。
    return importlib.import_module("scripts.workbench_reports")


def canonical_uuid(value: str) -> str:
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise RuntimeErrorCode("invalid_arguments") from None
    return value


@dataclass(frozen=True)
class Options:
    command: str
    mode: str = "readonly"
    suite: str = "readonly"
    actor: str | None = field(default=None, repr=False)
    prepare_only: bool = False
    web_port: int = 5175
    api_port: int = 8015
    timeout: float = 900
    with_distribution: bool = False

    def validate(self) -> None:
        if (
            self.command not in {"demo", "accept"}
            or self.mode not in {"readonly", "controlled"}
            or self.suite not in {"readonly", "full", "management", "evaluation", "mutations"}
            or type(self.web_port) is not int
            or type(self.api_port) is not int
            or not 1 <= self.web_port <= 65535
            or not 1 <= self.api_port <= 65535
            or self.web_port == self.api_port
            or isinstance(self.timeout, bool)
            or not math.isfinite(self.timeout)
            or not 0 < self.timeout <= 86400
            or (
                self.command == "accept"
                and (self.actor is not None or self.prepare_only or self.mode != "readonly")
            )
            or (self.command == "demo" and (self.suite != "readonly" or self.with_distribution))
            or (self.command == "demo" and self.mode == "controlled" and self.actor is None)
            or (
                self.actor is not None
                and (
                    self.mode != "controlled"
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,79}", self.actor) is None
                )
            )
        ):
            raise RuntimeErrorCode("invalid_arguments")

    def components(self) -> list[str]:
        self.validate()
        if self.command == "demo":
            result = ["prepare_controlled" if self.mode == "controlled" else "seed"]
            if not self.prepare_only:
                result.append("launcher")
            return result
        result = {
            "readonly": ["seed", "management", "evaluation"],
            "full": ["seed", "management", "evaluation", "mutations"],
            "management": ["seed", "management"],
            "evaluation": ["evaluation"],
            "mutations": ["mutations"],
        }[self.suite].copy()
        if self.with_distribution:
            result.append("distribution")
        return result


def private_directory(path: Path) -> None:
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise RuntimeErrorCode("session_invalid")
    info = path.stat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise RuntimeErrorCode("session_invalid")


def create_session() -> Path:
    shared = reports()  # 共享模块缺失时不留下半成品目录。
    base = ROOT / ".konwledge" / "workbench"
    for candidate in (base, *base.parents):
        if candidate.is_symlink():
            raise RuntimeErrorCode("session_invalid")
    base.mkdir(parents=True, mode=0o700, exist_ok=True)
    private_directory(base)
    session = base / str(uuid4())
    session.mkdir(mode=0o700, exist_ok=False)
    private_directory(session)
    return cast(Path, shared.validate_session(session))


def allocate_invocation(session: Path, component: str) -> tuple[str, Path]:
    reports().validate_session(session)
    if component not in COMPONENTS:
        raise RuntimeErrorCode("invalid_arguments")
    directory = session / component
    directory.mkdir(mode=0o700, exist_ok=True)
    private_directory(directory)
    invocation_id = str(uuid4())
    invocation = directory / invocation_id
    invocation.mkdir(mode=0o700, exist_ok=False)
    return invocation_id, invocation / "receipt.json"


def safe_environment(parent: Mapping[str, str]) -> dict[str, str]:
    allowed = {
        "PATH",
        "HOME",
        "LANG",
        "VIRTUAL_ENV",
        "UV_CACHE_DIR",
        "TMPDIR",
        "PNPM_HOME",
        "SYSTEMROOT",
        "WINDIR",
        "LC_ALL",
        "LC_CTYPE",
        "LC_NUMERIC",
        "LC_TIME",
        "LC_COLLATE",
        "LC_MONETARY",
        "LC_MESSAGES",
        "LC_PAPER",
        "LC_NAME",
        "LC_ADDRESS",
        "LC_TELEPHONE",
        "LC_MEASUREMENT",
        "LC_IDENTIFICATION",
    }
    result = {key: value for key, value in parent.items() if key in allowed}
    result.update({"NO_COLOR": "1", "TERM": "dumb", "PYTHONDONTWRITEBYTECODE": "1"})
    return result


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    ppid: int
    group: int
    started: int
    state: str


def process_table() -> dict[int, ProcessIdentity]:
    result: dict[int, ProcessIdentity] = {}
    # /proc 是进程内核接口，而非仓库文件搜索。
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            raw = (entry / "stat").read_text()
            fields = raw[raw.rindex(")") + 2 :].split()
            pid = int(entry.name)
            result[pid] = ProcessIdentity(
                pid, int(fields[1]), int(fields[2]), int(fields[19]), fields[0]
            )
        except PermissionError:
            raise RuntimeErrorCode("cleanup_unknown") from None
        except (OSError, ValueError, IndexError):
            continue
    if os.getpid() not in result:
        raise RuntimeErrorCode("cleanup_unknown")
    return result


def descendant_ids(table: Mapping[int, ProcessIdentity], ancestors: set[int]) -> set[int]:
    found = ancestors.copy()
    while True:
        addition = {pid for pid, item in table.items() if item.ppid in found} - found
        if not addition:
            return found
        found.update(addition)


@contextmanager
def subreaper() -> Iterator[None]:
    if (
        not sys.platform.startswith("linux")
        or not hasattr(os, "pidfd_open")
        or not hasattr(signal, "pidfd_send_signal")
    ):
        raise RuntimeErrorCode("cleanup_unknown")
    library = ctypes.CDLL(None, use_errno=True)
    before = ctypes.c_int()
    if library.prctl(37, ctypes.byref(before), 0, 0, 0) != 0:
        raise RuntimeErrorCode("cleanup_unknown")
    if library.prctl(36, 1, 0, 0, 0) != 0:
        raise RuntimeErrorCode("cleanup_unknown")
    try:
        yield
    finally:
        if library.prctl(36, before.value, 0, 0, 0) != 0:
            raise RuntimeErrorCode("cleanup_unknown")


class OwnedProcesses:
    """串行调用下只追踪本次后代与 subreaper 收养者；排除调用前所有后代。

    PID + starttime 防 PID 复用。不按名字/端口发送信号；不 waitpid(-1)。
    run_process 必须在专用 CLI 主线程串行使用，不与其它 spawn 并发。
    """

    def __init__(self, baseline: Mapping[int, ProcessIdentity], child: int) -> None:
        excluded_ids = descendant_ids(baseline, {os.getpid()}) - {os.getpid()}
        self.excluded = {pid: baseline[pid].started for pid in excluded_ids}
        self.foreign_baseline = bool(excluded_ids)
        self.root = child
        self.known: dict[int, int] = {}
        self.verified = True
        self.initial_scan = True
        self.refresh()
        self.initial_scan = False

    def refresh(self) -> dict[int, ProcessIdentity]:
        try:
            table = process_table()
            seeds = {
                pid
                for pid, started in self.known.items()
                if pid in table and table[pid].started == started
            }
            if self.initial_scan and self.root in table:
                seeds.add(self.root)
            excluded_seeds = {
                pid
                for pid, started in self.excluded.items()
                if pid in table and table[pid].started == started
            }
            excluded = descendant_ids(table, excluded_seeds)
            for pid in excluded:
                self.excluded[pid] = table[pid].started
            # 快速 setsid 孤儿由内核收养。存在 foreign 基线时，未知收养者不能证明
            # 来源，宁可 unknown 且不发送信号；已观察的 owned 后代仍可安全收尾。
            for pid, item in table.items():
                if item.ppid != os.getpid() or pid in excluded or pid in seeds:
                    continue
                if self.foreign_baseline:
                    self.verified = False
                else:
                    seeds.add(pid)
            found = descendant_ids(table, seeds) - excluded - {os.getpid()}
            for pid in found:
                if pid in table:
                    if pid in self.known and self.known[pid] != table[pid].started:
                        self.verified = False
                        continue
                    self.known.setdefault(pid, table[pid].started)
            return {pid: item for pid, item in table.items() if self.known.get(pid) == item.started}
        except RuntimeErrorCode:
            self.verified = False
            return {}

    def reap(self, process: subprocess.Popen[bytes]) -> None:
        process.poll()
        for pid, item in self.refresh().items():
            if pid != self.root and item.ppid == os.getpid() and item.state == "Z":
                with suppress(ChildProcessError, ProcessLookupError):
                    os.waitpid(pid, os.WNOHANG)

    def send(self, signum: int, *, root_only: bool = False) -> None:
        for pid, item in self.refresh().items():
            if item.state == "Z" or (root_only and pid != self.root):
                continue
            try:
                # pidfd 绑定身份；二次核对 starttime，避免 PID 复用误杀。
                fd = os.pidfd_open(pid)
                try:
                    again = process_table().get(pid)
                    if again is not None and again.started == item.started:
                        signal.pidfd_send_signal(fd, signum)
                finally:
                    os.close(fd)
            except ProcessLookupError:
                pass
            except (OSError, RuntimeErrorCode):
                self.verified = False

    def empty(self, process: subprocess.Popen[bytes]) -> bool:
        self.reap(process)
        return not self.refresh() and self.verified


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int | None
    timed_out: bool
    interrupted: bool
    cleanup_verified: bool
    forced: bool = False


def run_process(
    argv: Sequence[str],
    *,
    timeout: float,
    request: bytes = b"",
    grace: float = 3,
    on_tick: Callable[[OwnedProcesses], None] | None = None,
) -> ProcessResult:
    if (
        isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or not 0 < timeout <= 86400
        or not 0 < grace <= 10
        or len(request) > 4096
    ):
        raise RuntimeErrorCode("invalid_arguments")
    interrupted = False
    timed_out = False
    forced = False
    previous: dict[int, Any] = {}

    def stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal interrupted
        interrupted = True

    with subreaper():
        baseline = process_table()
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, stop)
        process: subprocess.Popen[bytes] | None = None
        owned: OwnedProcesses | None = None
        try:
            process = subprocess.Popen(
                list(argv),
                cwd=ROOT,
                env=safe_environment(os.environ),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                umask=0o077,
            )
            owned = OwnedProcesses(baseline, process.pid)
            if process.stdin is not None:
                with suppress(BrokenPipeError):
                    process.stdin.write(request)
                    process.stdin.close()
            deadline = time.monotonic() + timeout
            while process.poll() is None and not interrupted:
                owned.refresh()
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                if on_tick is not None:
                    on_tick(owned)
                time.sleep(0.03)
        finally:
            if process is not None and owned is not None:
                # 即使正常退出仍检查遗留 setsid 后代。先给原 driver finally 机会。
                if not owned.empty(process):
                    owned.send(signal.SIGINT, root_only=True)
                    end = time.monotonic() + grace
                    while not owned.empty(process) and time.monotonic() < end:
                        time.sleep(0.03)
                for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
                    if owned.empty(process):
                        break
                    if signum != signal.SIGINT:
                        forced = True
                    owned.send(signum)
                    end = time.monotonic() + grace
                    while not owned.empty(process) and time.monotonic() < end:
                        time.sleep(0.03)
                verified = owned.empty(process)
                process.poll()
            else:
                verified = False
            for previous_signum, handler in previous.items():
                signal.signal(previous_signum, handler)
    if process is None:
        raise RuntimeErrorCode("adapter_failed")
    return ProcessResult(process.returncode, timed_out, interrupted, verified, forced)


def loopback_ready(owned: OwnedProcesses, web_port: int, api_port: int) -> bool:
    """仅在两个 loopback listener 的 socket 归本次后代时探测；绝不信任占用端口。"""
    try:
        inodes: set[str] = set()
        for pid in owned.refresh():
            for fd in (Path("/proc") / str(pid) / "fd").iterdir():
                with suppress(OSError):
                    target = os.readlink(fd)
                    if target.startswith("socket:["):
                        inodes.add(target[8:-1])
        listeners: set[int] = set()
        for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
            fields = line.split()
            address, hex_port = fields[1].split(":")
            if address == "0100007F" and fields[3] == "0A" and fields[9] in inodes:
                listeners.add(int(hex_port, 16))
        if not {web_port, api_port}.issubset(listeners):
            return False
        for port, path in ((api_port, "/health"), (web_port, "/")):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                if response.status != 200:
                    return False
                if port == api_port:
                    body = response.read(2049)
                    if len(body) > 2048 or json.loads(body).get("status") != "ok":
                        return False
            finally:
                connection.close()
        return True
    except (OSError, ValueError, AttributeError, http.client.HTTPException):
        return False


def read_receipt(
    session: Path,
    component: str,
    invocation_id: str,
    path: Path,
    *,
    started_ns: int | None = None,
    previous_scopes: frozenset[str] = frozenset(),
) -> Receipt:
    expected = session / component / canonical_uuid(invocation_id) / "receipt.json"
    if path != expected:
        raise RuntimeErrorCode("receipt_invalid")
    if not path.exists():
        raise RuntimeErrorCode("receipt_missing")
    try:
        data = cast(
            dict[str, Any], reports().safe_read_json(path, allowed_root=session, max_bytes=16384)
        )
        if (
            set(data) != RECEIPT_KEYS
            or data["session_id"] != session.name
            or data["component"] != component
            or data["invocation_id"] != invocation_id
            or data["status"] not in {"completed", "failed", "stopped"}
            or data["error_code"] not in ERROR_CODES | {None}
            or not isinstance(data["report_paths"], list)
            or len(data["report_paths"]) > 4
            or not isinstance(data["artifacts"], dict)
            or set(data["artifacts"]) - {"database", "manifest"}
        ):
            raise ValueError
        allowed_artifacts = (
            {"database"}
            if component == "seed"
            else {"database", "manifest"}
            if component == "prepare_controlled"
            else set()
        )
        if set(data["artifacts"]) - allowed_artifacts:
            raise ValueError
        expected_reports = (
            2
            if component == "distribution"
            else 0
            if component in {"launcher", "prepare_controlled"}
            else 1
        )
        if component == "prepare_controlled" and (
            data["report_paths"] or (data["status"] != "completed" and data["artifacts"])
        ):
            raise ValueError
        if data["status"] == "completed":
            if component == "launcher" or len(data["report_paths"]) != expected_reports:
                raise ValueError
            if (
                component in {"seed", "prepare_controlled"}
                and set(data["artifacts"]) != allowed_artifacts
            ):
                raise ValueError
        if data["status"] == "stopped" and (component != "launcher" or data["report_paths"]):
            raise ValueError
        references = [*data["report_paths"], *data["artifacts"].values()]
        for reference in references:
            returned = checked_reference(reference, session=session, component=component)
            if component not in {"mutations", "prepare_controlled"}:
                # session 绑定不够：也不能借用同一 session 的另一次 invocation。
                returned.relative_to(expected.parent / "driver")
        if component == "prepare_controlled" and data["status"] == "completed":
            if started_ns is None:
                raise ValueError
            validate_controlled_artifacts(
                data["artifacts"],
                session=session,
                started_ns=started_ns,
                previous_scopes=previous_scopes,
            )
        return cast(Receipt, data)
    except Exception:
        raise RuntimeErrorCode("receipt_invalid") from None


def checked_reference(reference: Any, *, session: Path, component: str) -> Path:
    if not isinstance(reference, str) or not reference or Path(reference).is_absolute():
        raise RuntimeErrorCode("receipt_invalid")
    path = ROOT / reference
    if reports().artifact_reference(path, session=session, component=component) != reference:
        raise RuntimeErrorCode("receipt_invalid")
    return path


def controlled_scopes() -> frozenset[str]:
    """调用前固定根快照；即使旧目录被 touch 也不能当作本次 prepare 的产物。"""
    root = ROOT / ".konwledge" / "mutation-demo"
    for candidate in (root, *root.parents):
        if candidate.is_symlink():
            raise RuntimeErrorCode("session_invalid")
    if not root.exists():
        return frozenset()
    private_directory(root)
    return frozenset(entry.name for entry in root.iterdir())


def validate_controlled_artifacts(
    artifacts: Mapping[str, Any],
    *,
    session: Path,
    started_ns: int,
    previous_scopes: frozenset[str],
    scope_id: str | None = None,
    module: ModuleType | None = None,
) -> dict[str, str]:
    """验证原 prepare 的严格 DTO/dbmatch 与本次新鲜度；seed 不成为业务报告。"""
    if set(artifacts) != {"database", "manifest"}:
        raise RuntimeErrorCode("receipt_invalid")
    paths = {
        key: checked_reference(value, session=session, component="prepare_controlled")
        for key, value in artifacts.items()
    }
    manifest, database = paths["manifest"], paths["database"]
    scope = canonical_uuid(manifest.parent.name)
    parent = ROOT / ".konwledge" / "mutation-demo" / scope
    if (
        manifest != parent / "mutation-manifest.json"
        or database.parent.parent != parent
        or database.name != "knowledge.db"
        or scope in previous_scopes
        or (scope_id is not None and scope_id != scope)
    ):
        raise RuntimeErrorCode("receipt_invalid")
    # 原验证器读 seed report、manifest 和库的有限安全字段，不传播 source_ids/全文。
    prepare = module or importlib.import_module("scripts.prepare_mutation_demo")
    if prepare.validate_demo(manifest, database) != manifest:
        raise RuntimeErrorCode("receipt_invalid")
    report = database.parent / "report.json"
    checked_reference(
        report.relative_to(ROOT).as_posix(), session=session, component="prepare_controlled"
    )
    finished_ns = time.time_ns()
    for path in (parent, database.parent, database, manifest, report):
        info = path.stat(follow_symlinks=False)
        if not (
            started_ns <= info.st_mtime_ns <= finished_ns
            and started_ns <= info.st_ctime_ns <= finished_ns
        ):
            raise RuntimeErrorCode("receipt_invalid")
    return {key: path.relative_to(ROOT).as_posix() for key, path in paths.items()}


def empty_component(component: str, *, status: str = "blocked") -> dict[str, Any]:
    return {
        "component": component,
        "status": status,
        "exit_code": None,
        "timed_out": False,
        "cleanup_verified": False,
        "report_paths": [],
        "checks_passed": 0,
        "checks_failed": 0,
        "job_statuses": [],
        "mean_recall": [],
        "frontend_status": None,
        "children_stopped": None,
        "error_code": "dependency_failed" if status == "blocked" else None,
    }


def merge_result(
    component: str, result: ProcessResult, receipt: Mapping[str, Any], *, session: Path
) -> dict[str, Any]:
    item = empty_component(component, status="failed")
    item.update(
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        cleanup_verified=result.cleanup_verified,
        error_code=None,
    )
    try:
        paths = [
            checked_reference(ref, session=session, component=component)
            for ref in receipt["report_paths"]
        ]
        if component == "launcher":
            projection: dict[str, Any] = {}
        else:
            if not paths and component != "prepare_controlled":
                raise RuntimeErrorCode("report_missing")
            projection = reports().project_report(component, paths, session=session)
        # 投影只能更新安全报告字段，不能覆盖执行证据。
        for key in (
            "report_paths",
            "checks_passed",
            "checks_failed",
            "job_statuses",
            "mean_recall",
            "frontend_status",
            "children_stopped",
        ):
            if key in projection:
                item[key] = projection[key]
        if not result.cleanup_verified:
            item["status"], item["error_code"] = "unknown", "cleanup_unknown"
        elif result.forced:
            item["error_code"] = "cleanup_forced"
        elif result.timed_out:
            item["error_code"] = "timeout"
        elif result.interrupted:
            if (
                component == "launcher"
                and result.exit_code == 130
                and receipt["status"] == "stopped"
            ):
                item["status"] = "stopped"
            else:
                item["error_code"] = "interrupted"
        elif result.exit_code != 0:
            item["error_code"] = "driver_failed"
        elif receipt["status"] != "completed":
            item["error_code"] = receipt["error_code"] or "adapter_failed"
        elif component != "launcher" and (
            projection.get("status") not in {"passed", "ready"}
            or item["checks_failed"] != 0
            or item["children_stopped"] is False
        ):
            item["error_code"] = "checks_failed"
        else:
            item["status"] = "ready" if component == "prepare_controlled" else "passed"
    except Exception:
        item["error_code"] = "report_invalid"
        if not result.cleanup_verified:
            item["status"], item["error_code"] = "unknown", "cleanup_unknown"
    return item


def run_component(
    session: Path, component: str, options: Options, artifacts: Mapping[str, str]
) -> tuple[dict[str, Any], dict[str, str]]:
    invocation_id, receipt_path = allocate_invocation(session, component)
    argv = [
        sys.executable,
        str(ROOT / "scripts" / "workbench.py"),
        "_adapter",
        "--session-id",
        session.name,
        "--component",
        component,
        "--invocation-id",
        invocation_id,
    ]
    request = json.dumps(
        {
            "artifacts": dict(artifacts),
            "actor": options.actor,
            "web_port": options.web_port,
            "api_port": options.api_port,
        }
    ).encode()
    announced = False

    def tick(owned: OwnedProcesses) -> None:
        nonlocal announced
        if not announced and loopback_ready(owned, options.web_port, options.api_port):
            print(f"ready http://127.0.0.1:{options.web_port}/", flush=True)
            announced = True

    previous_scopes = controlled_scopes() if component == "prepare_controlled" else frozenset()
    # 使用本次独占目录的文件系统时间下界，避免内核时间粒度与 wall clock 偏差。
    started_ns = receipt_path.parent.stat().st_mtime_ns
    result = run_process(
        argv,
        timeout=options.timeout,
        request=request,
        on_tick=tick if component == "launcher" else None,
    )
    try:
        receipt = read_receipt(
            session,
            component,
            invocation_id,
            receipt_path,
            started_ns=started_ns,
            previous_scopes=previous_scopes,
        )
    except RuntimeErrorCode as error:
        item = empty_component(component, status="failed")
        item.update(
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            cleanup_verified=result.cleanup_verified,
            error_code=(
                "cleanup_forced"
                if result.forced
                else "timeout"
                if result.timed_out
                else "interrupted"
                if result.interrupted
                else error.code
            ),
        )
        if not result.cleanup_verified:
            item.update(status="unknown", error_code="cleanup_unknown")
        return item, {}
    item = merge_result(component, result, receipt, session=session)
    # 仅成功的准备结果可以传入下一组件；验收不要输出数据库路径。
    artifacts_out = receipt["artifacts"] if item["status"] in {"passed", "ready"} else {}
    return item, dict(artifacts_out)


@contextmanager
def session_signals() -> Iterator[Callable[[], bool]]:
    interrupted = False
    previous: dict[int, Any] = {}

    def stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal interrupted
        interrupted = True

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, stop)
        yield lambda: interrupted
    finally:
        for previous_signum, handler in previous.items():
            signal.signal(previous_signum, handler)


def execute(options: Options) -> tuple[Path, dict[str, Any], int]:
    options.validate()
    with session_signals() as interrupted:
        return execute_session(options, interrupted)


def execute_session(
    options: Options, interrupted: Callable[[], bool]
) -> tuple[
    Path,
    dict[str, Any],
    int,
]:
    requested = options.components()  # 所有非法参数必须在创建目录之前拒绝。
    session = create_session()
    summary: dict[str, Any] = {
        "schema_version": 1,
        "session_id": session.name,
        "command": options.command,
        "mode": (
            options.mode
            if options.command == "demo"
            else "controlled"
            if options.suite in {"full", "mutations"}
            else "readonly"
        ),
        "requested_components": requested,
        "status": "failed",
        "components": [],
        "artifacts": {},
    }
    if options.command == "accept":
        summary["suite"] = options.suite
    artifacts: dict[str, str] = {}
    blocked = False
    for component in requested:
        if interrupted():
            blocked = True
        if blocked:
            item = empty_component(component)
            if interrupted():
                item["error_code"] = "interrupted"
            summary["components"].append(item)
            continue
        try:
            item, produced = run_component(session, component, options, artifacts)
        except BaseException as error:
            if not isinstance(error, (Exception, KeyboardInterrupt)):
                raise
            item = empty_component(component, status="unknown")
            item["error_code"] = (
                "interrupted"
                if isinstance(error, KeyboardInterrupt)
                else error.code
                if isinstance(error, RuntimeErrorCode)
                else "runtime_failed"
            )
            produced = {}
        summary["components"].append(item)
        if component in {"seed", "prepare_controlled"}:
            artifacts.update(produced)
        blocked = item["status"] not in {"passed", "ready"}
    statuses = [item["status"] for item in summary["components"]]
    if "unknown" in statuses:
        summary["status"] = "unknown"
    elif interrupted() or "failed" in statuses or "blocked" in statuses:
        summary["status"] = "failed"
    elif "stopped" in statuses:
        summary["status"] = "stopped"
    else:
        summary["status"] = "prepared" if options.prepare_only else "passed"
    if options.command == "demo":
        summary["artifacts"] = artifacts
    path = session / "summary.json"
    reports().write_json_exclusive(path, summary, session=session)
    return path, summary, 0 if summary["status"] in {"passed", "prepared"} else 1


def adapter(session_id: str, component: str, invocation_id: str, request: Mapping[str, Any]) -> int:
    """隐藏子进程只调用固定 PUBLIC Python API；原始 payload 不进入 receipt。"""
    canonical_uuid(session_id)
    canonical_uuid(invocation_id)
    if component not in COMPONENTS:
        raise RuntimeErrorCode("invalid_arguments")
    session = ROOT / ".konwledge" / "workbench" / session_id
    reports().validate_session(session)
    invocation = session / component / invocation_id
    private_directory(invocation)
    receipt_path = invocation / "receipt.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        raise RuntimeErrorCode("receipt_invalid")
    receipt: Receipt = {
        "session_id": session_id,
        "component": component,
        "invocation_id": invocation_id,
        "status": "failed",
        "report_paths": [],
        "artifacts": {},
        "error_code": None,
    }
    exit_code = 1
    try:
        if set(request) != {"artifacts", "actor", "web_port", "api_port"}:
            raise RuntimeErrorCode("invalid_arguments")
        supplied = request["artifacts"]
        if not isinstance(supplied, dict) or set(supplied) - {"database", "manifest"}:
            raise RuntimeErrorCode("invalid_arguments")
        options = Options(
            "demo",
            mode="controlled" if request["actor"] is not None else "readonly",
            actor=request["actor"],
            web_port=request["web_port"],
            api_port=request["api_port"],
        )
        options.validate()
        if component == "prepare_controlled" and options.actor is None:
            raise RuntimeErrorCode("invalid_arguments")
        artifact_component = "prepare_controlled" if "manifest" in supplied else "seed"
        inputs = {
            key: checked_reference(value, session=session, component=artifact_component)
            for key, value in supplied.items()
        }
        paths: list[Path] = []
        output = invocation / "driver"
        module_names = {
            "seed": "real_knowledge_acceptance",
            "management": "management_api_acceptance",
            "evaluation": "workbench_evaluation_acceptance",
            "mutations": "mutation_workbench_acceptance",
            "prepare_controlled": "prepare_mutation_demo",
            "distribution": "verify_distribution",
            "launcher": "live_workbench",
        }
        with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
            module = importlib.import_module("scripts." + module_names[component])
            if component == "seed":
                path = Path(module.run_acceptance(output))
                paths = [path]
                receipt["artifacts"]["database"] = reports().artifact_reference(
                    path.parent / "knowledge.db", session=session, component=component
                )
                exit_code = 0
            elif component == "management":
                path = output / "report.json"
                exit_code = module.Runner(inputs["database"], path).run()
                paths = [path]
            elif component == "evaluation":
                paths = [Path(module.run_acceptance_flow(output))]
                exit_code = 0
            elif component == "mutations":
                _ignored_payload, returned = module.Driver(frontend=True).run()
                if returned is None:
                    raise RuntimeErrorCode("report_missing")
                paths = [Path(returned)]
                exit_code = 0
            elif component == "prepare_controlled":
                previous_scopes = controlled_scopes()
                started_ns = invocation.stat().st_mtime_ns
                prepared = module.prepare()
                if not isinstance(prepared, dict) or prepared.get("status") != "ready":
                    raise RuntimeErrorCode("adapter_failed")
                scope = canonical_uuid(prepared["scope_id"])
                receipt["artifacts"] = validate_controlled_artifacts(
                    {key: prepared[key] for key in ("database", "manifest")},
                    session=session,
                    started_ns=started_ns,
                    previous_scopes=previous_scopes,
                    scope_id=scope,
                    module=module,
                )
                # PUBLIC prepare 的 seed 旁报告只作严格准备证据，不进入 report 投影。
                exit_code = 0
            elif component == "distribution":
                _wheel, _sdist, returned_paths = module.verify(output, sys.executable)
                paths = list(returned_paths)
                exit_code = 0
            else:
                if "database" not in inputs:
                    raise RuntimeErrorCode("invalid_arguments")
                exit_code = module.run(
                    inputs["database"],
                    options.web_port,
                    options.api_port,
                    mutation_manifest=inputs.get("manifest"),
                    mutation_actor=options.actor,
                )
            if type(exit_code) is not int:
                raise RuntimeErrorCode("adapter_failed")
        receipt["report_paths"] = [
            reports().artifact_reference(path, session=session, component=component)
            for path in paths
        ]
        receipt["status"] = (
            "stopped"
            if component == "launcher" and exit_code == 130
            else "completed"
            if exit_code == 0
            else "failed"
        )
        if receipt["status"] == "failed":
            receipt["error_code"] = "driver_failed"
    except KeyboardInterrupt:
        receipt["error_code"] = "interrupted"
        exit_code = 130
    except Exception as error:
        receipt["error_code"] = (
            error.code if isinstance(error, RuntimeErrorCode) else "adapter_failed"
        )
        exit_code = 1
    if component == "prepare_controlled" and receipt["status"] != "completed":
        receipt["artifacts"] = {}
    reports().write_json_exclusive(receipt_path, receipt, session=session)
    return exit_code
