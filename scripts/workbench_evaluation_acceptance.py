"""隔离 B3 workbench 真实验收：复用真实文档 seed run，启动 loopback 管理服务与 Vite，
并执行只在显式环境下启用的 Vitest live integration。

默认不会触碰原始 docs、业务库或用户路径；所有写入都发生在唯一输出目录中。
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from scripts.live_workbench import child_environments, cleanup, spawn, wait_backend, wait_web
from scripts.real_knowledge_acceptance import ROOT, run_acceptance

DEFAULT_OUTPUT_DIR = Path(".knowledge/workbench-evaluation-acceptance")
DEFAULT_VITEST_FILE = Path("src/evaluation/live-acceptance.test.ts")
FOLLOWUP_ANCHOR = "一次通过只证明该任务的固定评测时间与知识指纹，不保证未来变更仍然通过。"
FOLLOWUP_NOTE = "隔离工作台演示备注：允许通过刷新观察新任务，不自动归因到页面上看到的差异。"
_ALLOWED_FRONTEND_STATUS = {"passed", "failed", "skipped"}


class AcceptanceError(RuntimeError):
    """只暴露稳定错误码，不反射底层堆栈、密钥或原文。"""


@dataclass(frozen=True)
class SeedContext:
    report_path: Path
    run_dir: Path
    database: Path
    document_copy: Path
    normal_job_id: str
    fault_job_id: str
    restore_job_id: str
    dataset_hash: str
    case_count: int


@dataclass(frozen=True)
class ServicePorts:
    api_port: int
    web_port: int


@dataclass(frozen=True)
class FrontendArtifacts:
    report_path: Path
    summary: dict[str, Any]
    command: subprocess.CompletedProcess[str]


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AcceptanceError(code)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def expect_dict(value: object, code: str) -> dict[str, Any]:
    require(isinstance(value, dict), code)
    return cast(dict[str, Any], value)


def normalize_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def choose_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def relative_to(root: Path, target: Path) -> str:
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    require(resolved_target.is_relative_to(resolved_root), "ARTIFACT_OUTSIDE_RUN_DIR")
    return resolved_target.relative_to(resolved_root).as_posix()


def build_followup_text(text: str) -> str:
    require(text.count(FOLLOWUP_ANCHOR) == 1, "FOLLOWUP_ANCHOR_NOT_UNIQUE")
    require(FOLLOWUP_NOTE not in text, "FOLLOWUP_NOTE_ALREADY_PRESENT")
    return text.replace(FOLLOWUP_ANCHOR, f"{FOLLOWUP_ANCHOR}\n{FOLLOWUP_NOTE}")


def wait_web_http(port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
        try:
            connection.request("GET", "/")
            response = connection.getresponse()
            body = response.read(4097)
            if response.status == 200 and body:
                return
        except (OSError, http.client.HTTPException):
            pass
        finally:
            connection.close()
        time.sleep(0.1)
    raise AcceptanceError("WEB_NOT_READY")


def load_seed_context(report_path: Path, run_dir: Path) -> SeedContext:
    resolved_report = report_path.resolve()
    require(resolved_report.is_file(), "SEED_REPORT_MISSING")
    require(resolved_report.is_relative_to(run_dir.resolve()), "SEED_REPORT_NOT_ISOLATED")
    payload = json.loads(resolved_report.read_text(encoding="utf-8"))
    require(payload.get("status") == "passed", "SEED_REPORT_NOT_PASSED")
    seed_run_dir = resolved_report.parent
    database = seed_run_dir / "knowledge.db"
    document_copy = seed_run_dir / "documents" / "docs" / "auto-evaluation.md"
    require(database.is_file(), "SEED_DATABASE_MISSING")
    require(document_copy.is_file(), "SEED_DOCUMENT_COPY_MISSING")
    require(document_copy.is_relative_to(seed_run_dir), "SEED_DOCUMENT_COPY_NOT_ISOLATED")

    steps = payload.get("steps")
    require(isinstance(steps, list), "SEED_STEPS_NOT_ARRAY")
    step_map: dict[str, dict[str, Any]] = {}
    for step in steps:
        if isinstance(step, dict) and isinstance(step.get("name"), str):
            step_map[step["name"]] = step
    for name in ("positive", "fault", "restore"):
        require(name in step_map, f"SEED_{name.upper()}_STEP_MISSING")

    def step_job_id(name: str) -> str:
        step = expect_dict(step_map.get(name), f"SEED_{name.upper()}_STEP_MISSING")
        job = expect_dict(step.get("job"), f"SEED_{name.upper()}_JOB_MISSING")
        raw = job.get("id")
        require(isinstance(raw, str), f"SEED_{name.upper()}_JOB_ID_MISSING")
        job_id = cast(str, raw)
        UUID(job_id)
        return job_id

    dataset = expect_dict(payload.get("dataset"), "SEED_DATASET_MISSING")
    dataset_hash = dataset.get("hash")
    case_count = dataset.get("case_count")
    require(
        isinstance(dataset_hash, str) and bool(re.fullmatch(r"[0-9a-f]{64}", dataset_hash)),
        "SEED_DATASET_HASH_INVALID",
    )
    require(
        isinstance(case_count, int) and case_count > 0,
        "SEED_CASE_COUNT_INVALID",
    )

    dataset_hash_value = cast(str, dataset_hash)
    case_count_value = cast(int, case_count)

    return SeedContext(
        report_path=resolved_report,
        run_dir=seed_run_dir,
        database=database,
        document_copy=document_copy,
        normal_job_id=step_job_id("positive"),
        fault_job_id=step_job_id("fault"),
        restore_job_id=step_job_id("restore"),
        dataset_hash=dataset_hash_value,
        case_count=case_count_value,
    )


def validate_frontend_summary(summary: dict[str, Any]) -> None:
    require(summary.get("status") in _ALLOWED_FRONTEND_STATUS, "FRONTEND_SUMMARY_STATUS_INVALID")
    tests = expect_dict(summary.get("tests"), "FRONTEND_SUMMARY_TESTS_INVALID")
    require(
        isinstance(tests.get("passed"), int) and tests["passed"] >= 0,
        "FRONTEND_SUMMARY_PASSED_INVALID",
    )
    require(
        isinstance(tests.get("skipped"), int) and tests["skipped"] >= 0,
        "FRONTEND_SUMMARY_SKIPPED_INVALID",
    )
    if summary.get("status") == "passed":
        refresh = expect_dict(summary.get("refresh"), "FRONTEND_SUMMARY_REFRESH_INVALID")
        for key in ("new_job_seen", "failure_preserved", "ui_notice_seen", "selection_preserved"):
            require(refresh.get(key) is True, f"FRONTEND_{key.upper()}_MISSING")
        comparisons = expect_dict(
            summary.get("comparison"),
            "FRONTEND_SUMMARY_COMPARISON_INVALID",
        )
        normal_fault = expect_dict(
            comparisons.get("normal_to_fault"),
            "FRONTEND_NORMAL_FAULT_INVALID",
        )
        fault_restore = expect_dict(
            comparisons.get("fault_to_restore"),
            "FRONTEND_FAULT_RESTORE_INVALID",
        )
        require(
            normal_fault.get("comparable") is True,
            "FRONTEND_NORMAL_FAULT_NOT_COMPARABLE",
        )
        require(
            fault_restore.get("comparable") is True,
            "FRONTEND_FAULT_RESTORE_NOT_COMPARABLE",
        )
        require(
            normal_fault.get("mean_recall_delta") is not None,
            "FRONTEND_NORMAL_FAULT_DELTA_MISSING",
        )
        require(
            fault_restore.get("mean_recall_delta") is not None,
            "FRONTEND_FAULT_RESTORE_DELTA_MISSING",
        )
        require(
            float(normal_fault["mean_recall_delta"]) < 0,
            "FRONTEND_NORMAL_FAULT_DELTA_NOT_NEGATIVE",
        )
        require(
            float(fault_restore["mean_recall_delta"]) > 0,
            "FRONTEND_FAULT_RESTORE_DELTA_NOT_POSITIVE",
        )


class Runner:
    def __init__(self, output_dir: Path, vitest_file: Path = DEFAULT_VITEST_FILE) -> None:
        root = output_dir.resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.run_dir = root / (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
        )
        self.run_dir.mkdir(mode=0o700, exist_ok=False)
        self.vitest_file = vitest_file
        self.children: list[subprocess.Popen[bytes]] = []
        self.secret: str | None = None
        self.report_path = self.run_dir / "report.json"
        self.report: dict[str, Any] = {
            "schema_version": 1,
            "status": "running",
            "run_id": self.run_dir.name,
            "started_at": datetime.now(UTC).isoformat(),
            "checks": {},
            "commands": [],
            "artifacts": {
                "driver_report": "report.json",
                "seed_report": None,
                "frontend_summary": None,
            },
        }

    def check(self, name: str, condition: bool) -> None:
        self.report["checks"][name] = condition
        require(condition, name.upper())

    def safe(self, value: object) -> None:
        rendered = json.dumps(value, ensure_ascii=False, allow_nan=False)
        require(str(ROOT) not in rendered, "REPORT_ROOT_PATH_LEAK")
        require(str(self.run_dir) not in rendered, "REPORT_RUN_PATH_LEAK")
        if self.secret is not None:
            require(self.secret not in rendered, "REPORT_SECRET_LEAK")

    def _record_command(
        self,
        *,
        label: str,
        command: str,
        exit_code: int | None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.report["commands"].append(
            {
                "label": label,
                "command": command,
                "exit_code": exit_code,
                "stdout_hash": sha256(stdout.encode()),
                "stderr_hash": sha256(stderr.encode()),
            }
        )

    def launch_services(self, seed: SeedContext) -> ServicePorts:
        api_port = choose_loopback_port()
        web_port = choose_loopback_port()
        require(api_port != web_port, "LOOPBACK_PORT_COLLISION")
        self.secret = secrets.token_urlsafe(32)
        backend_env, web_env = child_environments(os.environ, api_port, self.secret)

        backend_command = [
            "uv",
            "run",
            "knowledge",
            "serve",
            "--enable-management",
            "--database",
            str(seed.database),
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
        ]
        backend = spawn(backend_command, ROOT, backend_env)
        self.children.append(backend)
        wait_backend(backend, api_port, stop=threading.Event())
        self._record_command(
            label="backend",
            command=(
                "uv run knowledge serve --enable-management "
                "--database <isolated-db> --host 127.0.0.1 --port <loopback>"
            ),
            exit_code=None,
        )

        web_command = [
            "pnpm",
            "run",
            "dev",
            "--host",
            "127.0.0.1",
            "--port",
            str(web_port),
            "--strictPort",
        ]
        web = spawn(web_command, ROOT / "web", web_env)
        self.children.append(web)
        wait_web(self.children, web_port, stop=threading.Event())
        wait_web_http(web_port)
        self._record_command(
            label="web",
            command="pnpm run dev --host 127.0.0.1 --port <loopback> --strictPort",
            exit_code=None,
        )
        return ServicePorts(api_port=api_port, web_port=web_port)

    def build_vitest_environment(
        self, seed: SeedContext, web_origin: str, frontend_report: Path
    ) -> dict[str, str]:
        secret = self.secret
        require(secret is not None, "SECRET_NOT_INITIALIZED")
        secret_value = cast(str, secret)
        _, web_env = child_environments(os.environ, 1, secret_value)
        env = {
            key: value
            for key, value in web_env.items()
            if key not in {"KNOWLEDGE_API_KEY", "KNOWLEDGE_MANAGEMENT_ORIGIN"}
        }
        env.update(
            {
                "NO_COLOR": "1",
                "TERM": "dumb",
                "KNOWLEDGE_ACCEPTANCE": "1",
                "KNOWLEDGE_ACCEPTANCE_WEB_ORIGIN": web_origin,
                "KNOWLEDGE_ACCEPTANCE_REPO_ROOT": str(ROOT),
                "KNOWLEDGE_ACCEPTANCE_RUN_ROOT": str(self.run_dir),
                "KNOWLEDGE_ACCEPTANCE_SEED_REPORT": str(seed.report_path),
                "KNOWLEDGE_ACCEPTANCE_DATABASE": str(seed.database),
                "KNOWLEDGE_ACCEPTANCE_DOC_COPY": str(seed.document_copy),
                "KNOWLEDGE_ACCEPTANCE_FRONTEND_REPORT": str(frontend_report),
                "KNOWLEDGE_ACCEPTANCE_FOLLOWUP_ANCHOR": FOLLOWUP_ANCHOR,
                "KNOWLEDGE_ACCEPTANCE_FOLLOWUP_NOTE": FOLLOWUP_NOTE,
            }
        )
        return env

    def run_vitest(self, seed: SeedContext, ports: ServicePorts) -> FrontendArtifacts:
        frontend_report = self.run_dir / "frontend-summary.json"
        command = ["pnpm", "exec", "vitest", "run", self.vitest_file.as_posix()]
        try:
            result = subprocess.run(
                command,
                cwd=ROOT / "web",
                env=self.build_vitest_environment(
                    seed, f"http://127.0.0.1:{ports.web_port}", frontend_report
                ),
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            self._record_command(
                label="vitest",
                command=f"pnpm exec vitest run {self.vitest_file.as_posix()}",
                exit_code=None,
                stdout=normalize_text(error.stdout),
                stderr=normalize_text(error.stderr),
            )
            raise AcceptanceError("VITEST_TIMEOUT") from None
        self._record_command(
            label="vitest",
            command=f"pnpm exec vitest run {self.vitest_file.as_posix()}",
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        require(frontend_report.is_file(), "FRONTEND_REPORT_MISSING")
        summary = json.loads(frontend_report.read_text(encoding="utf-8"))
        validate_frontend_summary(summary)
        require(result.returncode == 0, "VITEST_EXIT_NONZERO")
        return FrontendArtifacts(report_path=frontend_report, summary=summary, command=result)

    def execute(self) -> None:
        seed_output_dir = self.run_dir / "real-knowledge"
        seed_report = run_acceptance(seed_output_dir)
        seed = load_seed_context(seed_report, self.run_dir)
        self.report["artifacts"]["seed_report"] = relative_to(self.run_dir, seed.report_path)
        self.report["seed"] = {
            "report": relative_to(self.run_dir, seed.report_path),
            "database_digest": sha256(seed.database.read_bytes()),
            "document_copy": relative_to(self.run_dir, seed.document_copy),
            "normal_job_id": seed.normal_job_id,
            "fault_job_id": seed.fault_job_id,
            "restore_job_id": seed.restore_job_id,
            "dataset_hash": seed.dataset_hash,
            "case_count": seed.case_count,
        }
        ports = self.launch_services(seed)
        self.report["services"] = {
            "api_loopback": f"127.0.0.1:{ports.api_port}",
            "web_loopback": f"127.0.0.1:{ports.web_port}",
        }
        frontend = self.run_vitest(seed, ports)
        self.report["artifacts"]["frontend_summary"] = relative_to(
            self.run_dir, frontend.report_path
        )
        self.report["frontend"] = frontend.summary
        self.check("frontend_status_passed", frontend.summary.get("status") == "passed")
        self.check(
            "frontend_new_job_seen",
            frontend.summary["refresh"]["new_job_seen"] is True,
        )
        self.check(
            "frontend_failure_preserved",
            frontend.summary["refresh"]["failure_preserved"] is True,
        )
        self.check(
            "frontend_ui_notice_seen",
            frontend.summary["refresh"]["ui_notice_seen"] is True,
        )
        self.check(
            "frontend_selection_preserved",
            frontend.summary["refresh"]["selection_preserved"] is True,
        )
        self.report["status"] = "passed"

    def run(self) -> Path:
        try:
            self.execute()
        except Exception as error:
            self.report["status"] = "failed"
            code = (
                str(error) if isinstance(error, AcceptanceError) else type(error).__name__.upper()
            )
            self.report["error_code"] = (
                code if re.fullmatch(r"[A-Z0-9_]+", code) else "RUNNER_ERROR"
            )
        finally:
            try:
                cleanup(self.children)
            finally:
                self.report["children_stopped"] = all(
                    child.poll() is not None for child in self.children
                )
                self.report["finished_at"] = datetime.now(UTC).isoformat()
                self.safe(self.report)
                write_json(self.report_path, self.report)
        return self.report_path


def run_acceptance_flow(output_dir: Path, vitest_file: Path = DEFAULT_VITEST_FILE) -> Path:
    return Runner(output_dir, vitest_file=vitest_file).run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--vitest-file", type=Path, default=DEFAULT_VITEST_FILE)
    args = parser.parse_args(argv)
    report_path = run_acceptance_flow(args.output_dir, vitest_file=args.vitest_file)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "status": payload["status"],
                "report": relative_to(ROOT, report_path),
                "seed_report": payload["artifacts"]["seed_report"],
                "frontend_summary": payload["artifacts"]["frontend_summary"],
                "error_code": payload.get("error_code"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
