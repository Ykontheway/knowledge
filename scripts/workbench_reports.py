"""B-R2 受控报告读取与安全投影；不加载 driver，不证明进程退出或 receipt nonce。

ROOT 是唯一仓库边界。allowed_root 不是任意路径授权：只接受 canonical session
及固定 mutation-demo UUID 子树。投影只有八个公开字段；原报告的未知字段不返回。
同 session 内 invocation/nonce、新鲜度、退出码与最终清理由 runtime 独立证明。
"""

from __future__ import annotations

import json
import math
import os
import stat
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NoReturn, cast
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
_COMPONENTS = frozenset(
    {
        "seed",
        "management",
        "evaluation",
        "mutations",
        "distribution",
        "prepare_controlled",
        "launcher",
    }
)
_ERRORS = frozenset(
    {
        "session_invalid",
        "path_invalid",
        "file_invalid",
        "report_missing",
        "report_invalid",
        "json_invalid",
        "json_too_large",
        "write_failed",
        "report_exists",
        "component_invalid",
    }
)
_SEQUENCE = ["passed", "failed", "passed"]
_SEED_CHECKS = frozenset(
    {
        "exactly_three_automatic_jobs",
        "failed_job_preserved_after_restore",
        "positive_past_jobs_not_overwritten",
        "fault_past_jobs_not_overwritten",
        "restore_past_jobs_not_overwritten",
        "mutable_copies_restored",
    }
)
_B1_CHECKS = frozenset(
    {
        "job_statuses_desc_passed_failed_passed",
        "job_detail_status_failed",
        "job_detail_report_readable",
        "sqlite_digest_unchanged",
        "sqlite_row_counts_unchanged",
        "no_job_created",
    }
)
_B3_CHECKS = frozenset(
    {
        "frontend_status_passed",
        "frontend_new_job_seen",
        "frontend_failure_preserved",
        "frontend_ui_notice_seen",
        "frontend_selection_preserved",
    }
)
_B4_CHECKS = frozenset(
    {
        "owned_private_manifest_database",
        "positive_passed",
        "failure_head_committed",
        "fault_no_stale_evidence_fallback",
        "historical_checksum_reuse",
        "restored_gold_evidence_retrievable",
        "fixed_config_dataset",
        "exactly_three_new_jobs_commands",
        "jobs_fixed_pin",
        "recovery_identity_bound",
        "restart_same_manifest_recovers",
        "recovery_gets_no_write",
        "shared_original_docs_unchanged",
    }
)
_SMOKE_CHECKS = frozenset(
    {
        "installed_identity",
        "cli_entry_points",
        "packaged_resources",
        "demo_timeline",
        "context_and_stale_filtering",
        "database_schema_capture_history_diff",
        "conversation_review_audit",
        "historical_demo_retrieval",
        "evaluation_baseline_gate",
    }
)
_EXTRA_CHECKS = {
    "quality_acceptance": frozenset(
        {
            "installed_site_packages_identity",
            "core_optional_dependency_boundary",
            "quality_cli_30_cases",
            "quality_cli_1000_active_units",
            "quality_performance_p95",
            "quality_report_overwrite_guard",
            "automatic_evaluation_sdk_configuration",
            "real_file_import_update_idempotency",
            "failed_audit_privacy_and_commit_safety",
            "automatic_evaluation_cli_exit_3",
        }
    ),
    "api_extra": frozenset(
        {
            "installed_api",
            "no_sdks",
            "asgi_routes",
            "conversation_approval_readonly",
            "database_schema_current_only",
            "readonly",
            "cli_startup_disposal",
        }
    ),
    "tokens_extra": frozenset(
        {
            "installed_site_packages_identity",
            "tiktoken_version_range",
            "real_english_chinese_emoji_encoding",
            "special_token_spelling_as_ordinary_text",
            "exact_context_max_tokens_budget",
            "no_unrelated_extras",
        }
    ),
    "postgres_extra": frozenset(
        {
            "installed_postgres_extra",
            "psycopg_binary",
            "database_schema_collector",
            "standard_dsn_normalization",
            "sanitized_synthetic_failure",
            "no_unrelated_extras",
        }
    ),
}
# API smoke 的两种已发行布局：旧 CLI disposal；新布局同时证明 management/mutations。
# 任一新名字出现都要求完整新布局，不能用旧名字为残缺的新报告兜底。
_API_MANAGEMENT_CHECKS = frozenset(
    {
        "management_disabled_hidden",
        "management_jobs_readonly",
        "mutations_default_404_hidden_lazy_no_tables",
        "cli_management_startup_disposal",
    }
)


class WorkbenchReportError(Exception):
    """仅携带封闭错误码，无原异常、原文或路径。"""

    def __init__(self, code: str) -> None:
        self.code = code if code in _ERRORS else "report_invalid"
        super().__init__(self.code)


def _require(condition: object, code: str = "report_invalid") -> None:
    if not condition:
        raise WorkbenchReportError(code)


def _absolute(path: Path) -> Path:
    _require(isinstance(path, Path), "path_invalid")
    _require(".." not in path.parts and bool(path.parts), "path_invalid")
    # 不 resolve：绝不把链接规范化成看似合法的路径。
    return path if path.is_absolute() else ROOT / path


def _uuid(value: object) -> str:
    _require(isinstance(value, str))
    try:
        _require(str(UUID(cast(str, value))) == value)
    except (ValueError, TypeError, AttributeError):
        raise WorkbenchReportError("report_invalid") from None
    return cast(str, value)


def _boundary(path: Path) -> tuple[Path, bool]:
    """只授权固定根；返回 session/scope 边界和是否要求整个子树 private。"""
    try:
        parts = path.relative_to(ROOT).parts
        _require(len(parts) >= 3 and parts[0] == ".knowledge", "path_invalid")
        _require(parts[1] in {"workbench", "mutation-demo"}, "path_invalid")
        _uuid(parts[2])
        return ROOT / parts[0] / parts[1] / parts[2], parts[1] == "mutation-demo"
    except (ValueError, WorkbenchReportError):
        raise WorkbenchReportError("path_invalid") from None


def _directory_info(info: os.stat_result, path: Path, boundary: Path, private: bool) -> None:
    _require(stat.S_ISDIR(info.st_mode), "path_invalid")
    if path.is_relative_to(ROOT):
        _require(info.st_uid == os.getuid() and not info.st_mode & 0o7022, "path_invalid")
    if path == boundary or path == boundary.parent or (private and path.is_relative_to(boundary)):
        _require(stat.S_IMODE(info.st_mode) == 0o700, "path_invalid")


@contextmanager
def _directory_fd(path: Path, boundary: Path, private: bool) -> Iterator[int]:
    """逐段 openat + NOFOLLOW；持有父 fd 避免检查后再按完整路径打开的竞态。"""
    fd = -1
    try:
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            fd = os.open(path.anchor, flags)
            current = Path(path.anchor)
            for part in path.parts[1:]:
                child = os.open(part, flags, dir_fd=fd)
                try:
                    current = current / part
                    _directory_info(os.fstat(child), current, boundary, private)
                except BaseException:
                    os.close(child)
                    raise
                os.close(fd)
                fd = child
        except OSError:
            raise WorkbenchReportError("path_invalid") from None
        yield fd
    finally:
        if fd >= 0:
            os.close(fd)


def validate_session(session: Path) -> Path:
    """只接受 ROOT/.knowledge/workbench/<canonical UUID>，owned 0700 且无链接。"""
    try:
        path = _absolute(session)
        boundary, private = _boundary(path)
        _require(path == boundary and not private, "session_invalid")
        with _directory_fd(path, boundary, False):
            pass
        return path
    except WorkbenchReportError:
        raise WorkbenchReportError("session_invalid") from None


def _file_info(info: os.stat_result, *, private: bool, max_bytes: int | None = None) -> None:
    # session 内 0644 可读取：0700 会话边界已提供隐私；拒绝写共享、执行和特殊权限。
    modes = {0o600} if private else {0o600, 0o400, 0o644, 0o444}
    _require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and info.st_nlink == 1
        and stat.S_IMODE(info.st_mode) in modes,
        "file_invalid",
    )
    if max_bytes is not None:
        _require(0 <= info.st_size <= max_bytes, "json_too_large")


def _json_value(value: object) -> None:
    """拒绝非 JSON 类型、非 str 键、非 finite 数值和孤立 surrogate。"""
    if value is None or type(value) in {bool, int}:
        return
    if type(value) is float:
        _require(math.isfinite(value), "json_invalid")
        return
    if type(value) is str:
        value.encode("utf-8", "strict")
        return
    if type(value) is list:
        for item in cast(list[object], value):
            _json_value(item)
        return
    if type(value) is dict:
        for key, item in cast(dict[object, object], value).items():
            _require(type(key) is str, "json_invalid")
            _json_value(key)
            _json_value(item)
        return
    raise WorkbenchReportError("json_invalid")


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in items:
        _require(key not in result, "json_invalid")
        result[key] = item
    return result


def _constant(_value: str) -> NoReturn:
    raise WorkbenchReportError("json_invalid")


def safe_read_json(path: Path, *, allowed_root: Path, max_bytes: int = 2097152) -> dict[str, Any]:
    """受控 ancestry、no-follow owned regular nlink=1、限额、fatal UTF-8/finite JSON。"""
    fd = -1
    try:
        _require(type(max_bytes) is int and 0 < max_bytes <= 2097152, "json_too_large")
        root, target = _absolute(allowed_root), _absolute(path)
        boundary, private = _boundary(root)
        _require(target != root and target.is_relative_to(root), "path_invalid")
        with _directory_fd(target.parent, boundary, private) as parent:
            fd = os.open(
                target.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=parent,
            )
        before = os.fstat(fd)
        _file_info(before, private=private, max_bytes=max_bytes)
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            raw = stream.read(max_bytes + 1)
            after = os.fstat(stream.fileno())
        _file_info(after, private=private, max_bytes=max_bytes)
        _require(len(raw) <= max_bytes, "json_too_large")
        _require(
            (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            and len(raw) == after.st_size,
            "file_invalid",
        )
        value = json.loads(
            raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_constant
        )
        _json_value(value)
        _require(type(value) is dict, "json_invalid")
        return cast(dict[str, Any], value)
    except FileNotFoundError:
        raise WorkbenchReportError("report_missing") from None
    except PermissionError:
        raise WorkbenchReportError("file_invalid") from None
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
        raise WorkbenchReportError("json_invalid") from None
    finally:
        if fd >= 0:
            os.close(fd)


def _artifact_root(path: Path, session: Path, component: str) -> tuple[Path, bool]:
    _require(component in _COMPONENTS, "component_invalid")
    if path != session and path.is_relative_to(session):
        return session, False
    _require(component in {"mutations", "prepare_controlled"}, "path_invalid")
    boundary, private = _boundary(path)
    _require(private, "path_invalid")
    return boundary, True


def artifact_reference(path: Path, *, session: Path, component: str) -> str:
    """返回 repo-relative 引用，不创建链接；B4 只例外允许固定 private UUID 子树。"""
    session = validate_session(session)
    path = _absolute(path)
    boundary, private = _artifact_root(path, session, component)
    with _directory_fd(path.parent, boundary, private) as parent:
        try:
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                _directory_info(info, path, boundary, private)
            else:
                _file_info(info, private=private)
        except OSError:
            raise WorkbenchReportError("path_invalid") from None
    return path.relative_to(ROOT).as_posix()


def write_json_exclusive(path: Path, payload: Mapping[str, Any], *, session: Path) -> None:
    """只为可信父进程生成的 mapping 提供 safe IO；不是 summary/receipt schema 验证器。"""
    fd = -1
    try:
        session = validate_session(session)
        target = _absolute(path)
        _require(target != session and target.is_relative_to(session), "path_invalid")
        _require(isinstance(payload, Mapping), "json_invalid")
        value = dict(payload)
        _json_value(value)
        raw = (
            json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8", "strict")
        _require(len(raw) <= 2097152, "json_too_large")
        with _directory_fd(target.parent, session, False) as parent:
            fd = os.open(
                target.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=parent,
            )
        os.fchmod(fd, 0o600)
        _file_info(os.fstat(fd), private=True)
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise WorkbenchReportError("report_exists") from None
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
        raise WorkbenchReportError("write_failed") from None
    finally:
        if fd >= 0:
            os.close(fd)


def _object(value: object) -> dict[str, Any]:
    _require(type(value) is dict)
    return cast(dict[str, Any], value)


def _array(value: object) -> list[Any]:
    _require(type(value) is list)
    return cast(list[Any], value)


def _integer(value: object, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise WorkbenchReportError("report_invalid")
    return value


def _number(value: object, *, recall: bool = False) -> float:
    _require(type(value) in {int, float})
    try:
        result = float(cast(float, value))
        _require(math.isfinite(result) and (not recall or 0 <= result <= 1))
        return result
    except (ValueError, OverflowError):
        raise WorkbenchReportError("report_invalid") from None


def _checks(report: dict[str, Any], required: frozenset[str]) -> tuple[int, int, bool]:
    checks = _object(report.get("checks"))
    _require(bool(checks) and all(type(v) is bool for v in checks.values()))
    passed = sum(v is True for v in checks.values())
    failed = sum(v is False for v in checks.values())
    return passed, failed, not failed and required.issubset(checks)


def _metrics(value: object) -> list[float]:
    if value is None:
        return []
    metrics = _object(value)
    for key in ("case_count", "answerable_count", "no_answer_count", "safe_check_count"):
        if key in metrics:
            _integer(metrics[key], 1 if key == "case_count" else 0)
    for key in (
        "mean_recall",
        "mean_precision",
        "mean_reciprocal_rank",
        "mean_ndcg",
        "hit_rate",
        "no_answer_accuracy",
    ):
        if key in metrics and metrics[key] is not None:
            _number(metrics[key], recall=True)
    if "report_passed" in metrics:
        _require(type(metrics["report_passed"]) is bool)
    return (
        [] if metrics.get("mean_recall") is None else [_number(metrics["mean_recall"], recall=True)]
    )


def _seed(report: dict[str, Any]) -> tuple[list[str], list[float], list[str]]:
    _require(type(report.get("schema_version")) is int and report["schema_version"] == 1)
    steps = [_object(s) for s in _array(report.get("steps"))]
    _require([s.get("name") for s in steps] == ["positive", "fault", "restore"])
    jobs = [_object(step.get("job")) for step in steps]
    statuses = [job.get("status") for job in jobs]
    _require(statuses == _SEQUENCE)
    ids = [_uuid(job.get("id")) for job in jobs]
    _require(len(set(ids)) == 3)
    recalls: list[float] = []
    for job in jobs:
        quality = _object(job.get("report"))
        if "passed" in quality:
            _require(
                type(quality["passed"]) is bool and quality["passed"] is (job["status"] == "passed")
            )
        recalls.extend(_metrics(quality.get("metrics")))
    if len(recalls) == 3:
        _require(recalls[1] < recalls[0] and recalls[1] < recalls[2])
    return _SEQUENCE.copy(), recalls, ids


def _frontend(report: dict[str, Any]) -> None:
    _require(report.get("status") == "passed")
    tests = _object(report.get("tests"))
    _integer(tests.get("passed"), 1)
    _require(_integer(tests.get("skipped")) == 0)
    for key in ("failed", "errors"):
        if key in tests:
            _require(_integer(tests[key]) == 0)
    refresh = _object(report.get("refresh"))
    _require(
        all(
            refresh.get(k) is True
            for k in ("new_job_seen", "failure_preserved", "ui_notice_seen", "selection_preserved")
        )
    )
    comparison = _object(report.get("comparison"))
    for key, negative in (("normal_to_fault", True), ("fault_to_restore", False)):
        item = _object(comparison.get(key))
        _require(item.get("comparable") is True)
        delta = _number(item.get("mean_recall_delta"))
        _require(delta < 0 if negative else delta > 0)


def _evaluation(report: dict[str, Any], path: Path, session: Path) -> tuple[list[str], list[float]]:
    _require(type(report.get("schema_version")) is int and report["schema_version"] == 1)
    seed, artifacts = _object(report.get("seed")), _object(report.get("artifacts"))
    relative = seed.get("report")
    _require(type(relative) is str and relative == artifacts.get("seed_report"))
    link = Path(cast(str, relative))
    _require(not link.is_absolute() and ".." not in link.parts and bool(link.parts))
    target = path.parent / link
    _require(target.name == "report.json" and target.is_relative_to(path.parent / "real-knowledge"))
    artifact_reference(target, session=session, component="evaluation")
    nested = safe_read_json(target, allowed_root=path.parent)
    _require(nested.get("status") == "passed")
    _passed, _failed, okay = _checks(nested, _SEED_CHECKS)
    _require(okay)
    statuses, recalls, ids = _seed(nested)
    _require([seed.get(k) for k in ("normal_job_id", "fault_job_id", "restore_job_id")] == ids)
    frontend = _object(report.get("frontend"))
    _frontend(frontend)
    if "jobs" in frontend:
        jobs = _object(frontend["jobs"])
        _require([_object(jobs.get(k)).get("id") for k in ("normal", "fault", "restore")] == ids)
        _require(
            [_object(jobs.get(k)).get("status") for k in ("normal", "fault", "restore")]
            == _SEQUENCE
        )
    _require(report.get("children_stopped") is True)
    return statuses, recalls


def _mutations(report: dict[str, Any], path: Path) -> tuple[list[str], list[float]]:
    scope = _uuid(report.get("scope_id"))
    _require(path == ROOT / ".knowledge" / "mutation-demo" / scope / "b4-acceptance-report.json")
    jobs = [_object(job) for job in _array(report.get("jobs"))]
    commands = [_object(command) for command in _array(report.get("commands"))]
    _require(len(jobs) == len(commands) == 3 and [j.get("status") for j in jobs] == _SEQUENCE)
    ids = [_uuid(job.get("id")) for job in jobs]
    _require(len(set(ids)) == 3)
    recalls = [r for job in jobs for r in _metrics(job.get("metrics"))]
    _require(
        len(recalls) == 3
        and all(
            math.isclose(a, b, rel_tol=0, abs_tol=1e-12)
            for a, b in zip(recalls, (1.0, 2 / 3, 1.0), strict=True)
        )
    )
    command_ids = [_uuid(c.get("command_id")) for c in commands]
    _require(len(set(command_ids)) == 3)
    for index, command in enumerate(commands):
        _require(
            command.get("scope_id") == scope
            and command.get("committed") is True
            and command.get("evaluation_status") == _SEQUENCE[index]
            and command.get("job_ids") == [ids[index]]
        )
    _require(report.get("children_stopped") is True)
    children = _array(report.get("children"))
    _require(bool(children) and all(_object(c).get("stopped") is True for c in children))
    update, recovery = (
        _object(report.get("frontend_update")),
        _object(report.get("frontend_recovery")),
    )
    _require(update.get("status") == recovery.get("status") == "passed")
    _require(update.get("command_id") == recovery.get("command_id") == command_ids[0])
    _require(
        all(
            update.get(k) is True
            for k in (
                "preview_core_unchanged",
                "explicit_confirmation",
                "response_lost_after_commit",
                "uncertain_notice_before_get",
                "identity_scoped_get_recovered",
                "duplicate_write_prevented",
                "credential_not_persisted",
            )
        )
    )
    _require(
        all(
            recovery.get(k) is True
            for k in (
                "restart_credential_free_get_only",
                "old_failure_preserved",
                "historical_diff_complete",
                "historical_evidence_available",
                "comparable",
            )
        )
    )
    _require(
        _number(recovery.get("mean_recall_down")) < 0
        and _number(recovery.get("mean_recall_up")) > 0
        and _integer(recovery.get("post_count")) == 0
    )
    return _SEQUENCE.copy(), recalls


def _named_checks(value: object, required: frozenset[str]) -> int:
    items = _array(value)
    _require(
        all(type(item) is str for item in items)
        and len(set(items)) == len(items)
        and required.issubset(items)
    )
    return len(required)  # 未知名字不是新增的可证明 checks。


def _distribution_passing(report: dict[str, Any]) -> bool:
    """只适配 distribution；旧 summary 无 status，但显式失败证据绝不能被忽略。"""
    okay = True
    if "status" in report:
        _require(type(report["status"]) is str)
        okay = report["status"] == "passed"
    if "passed" in report:
        _require(type(report["passed"]) is bool)
        okay = okay and report["passed"] is True
    if "checks_failed" in report:
        okay = (_integer(report["checks_failed"]) == 0) and okay
    if "failed_checks" in report:
        failed = _array(report["failed_checks"])
        _require(all(type(name) is str and bool(name) for name in failed))
        okay = not failed and okay
    return okay


def _distribution(report: dict[str, Any], path: Path) -> tuple[int, bool]:
    fmt = report.get("distribution_format")
    _require(fmt in {"wheel", "sdist"} and path.name == f"{fmt}-smoke-summary.json")
    okay = _distribution_passing(report)
    count = _named_checks(report.get("check_names"), _SMOKE_CHECKS)
    counts = _object(report.get("counts"))
    _require(_integer(counts.get("checks")) == len(report["check_names"]))
    _require(_integer(counts.get("cli_commands")) == 6)
    for key in ("demo_steps", "evaluation_cases", "gate_checks"):
        _integer(counts.get(key), 1)
    version = report.get("version")
    _require(type(version) is str and bool(version))
    for key, required in _EXTRA_CHECKS.items():
        extra = _object(report.get(key))
        if key == "api_extra":
            names = _array(extra.get("checks"))
            # 先校验旧的公共六项；新名字不是任意 alias，也不是减少最小证据。
            _named_checks(names, required - {"cli_startup_disposal"})
            if _API_MANAGEMENT_CHECKS.intersection(names):
                required = (required - {"cli_startup_disposal"}) | _API_MANAGEMENT_CHECKS
        count += _named_checks(extra.get("checks"), required)
        _require(extra.get("version") == version)
        passing = _distribution_passing(extra)
        okay = okay and passing
    quality = _object(report["quality_acceptance"])
    _require(type(quality.get("passed")) is bool)
    okay = okay and quality["passed"] is True
    _integer(quality.get("quality_cases"), 30)
    _integer(quality.get("active_units"), 1000)
    _require(
        _number(quality.get("p95_seconds")) >= 0
        and quality.get("external_model_or_sdk_requests") is False
    )
    automatic = _object(quality.get("automatic_evaluation"))
    _require(
        automatic.get("configured") is True
        and automatic.get("update_audit_status") == "failed"
        and _integer(automatic.get("manual_exit")) == 3
    )
    _integer(automatic.get("history_count"), 2)
    tokens = _object(report["tokens_extra"])
    _require(tokens.get("mock_used") is False and tokens.get("model_or_sdk_requests") is False)
    _require(_object(report["postgres_extra"]).get("business_database_connected") is False)
    return count, okay


def _project_report(
    component: str, report_paths: Sequence[Path], *, session: Path
) -> dict[str, Any]:
    """投影严格八字段；业务不通过返回 failed，损坏 schema/不安全 IO 抛固定错误码。

    prepare_controlled 仅 empty paths 返回 ready，业务验证仍由原 strict prepare/runtime 做。
    seed 不宣称清理，children_stopped=None。distribution 只接收两份固定名称 JSON。
    """
    session = validate_session(session)
    _require(component in _COMPONENTS - {"launcher"}, "component_invalid")
    _require(not isinstance(report_paths, (str, bytes, Path)), "report_invalid")
    paths = [_absolute(path) for path in report_paths]
    result: dict[str, Any] = {
        "status": "failed",
        "report_paths": [],
        "checks_passed": 0,
        "checks_failed": 0,
        "job_statuses": [],
        "mean_recall": [],
        "frontend_status": None,
        "children_stopped": None,
    }
    if component == "prepare_controlled":
        _require(not paths)
        result["status"] = "ready"
        return result
    _require(len(paths) == (2 if component == "distribution" else 1), "report_missing")
    _require(len(set(paths)) == len(paths))
    result["report_paths"] = [
        artifact_reference(p, session=session, component=component) for p in paths
    ]
    if component == "distribution":
        _require(
            paths[0].parent == paths[1].parent
            and {p.name for p in paths} == {"wheel-smoke-summary.json", "sdist-smoke-summary.json"}
        )
        okay = True
        versions: list[object] = []
        for path in paths:
            report = safe_read_json(path, allowed_root=session)
            count, passing = _distribution(report, path)
            result["checks_passed"] += count if passing else 0
            result["checks_failed"] += 0 if passing else 1
            okay = okay and passing
            versions.append(report.get("version"))
        _require(versions[0] == versions[1])
        result["status"] = "passed" if okay else "failed"
        return result
    path = paths[0]
    allowed, _private = _artifact_root(path, session, component)
    report = safe_read_json(path, allowed_root=allowed)
    required = {
        "seed": _SEED_CHECKS,
        "management": _B1_CHECKS,
        "evaluation": _B3_CHECKS,
        "mutations": _B4_CHECKS,
    }[component]
    passed, failed, okay = _checks(report, required)
    result.update(checks_passed=passed, checks_failed=failed)
    # 原 driver failed、未知/running/skipped 均不能靠局部指标提升成 passed。
    if report.get("status") != "passed" or not okay:
        return result
    if component == "seed":
        statuses, recalls, _ids = _seed(report)
        result.update(job_statuses=statuses, mean_recall=recalls)
    elif component == "management":
        _require(type(report.get("schema_version")) is int and report["schema_version"] == 1)
        _require(report.get("job_statuses_created_at_desc") == _SEQUENCE)
        result.update(job_statuses=_SEQUENCE.copy(), mean_recall=_metrics(report.get("metrics")))
    elif component == "evaluation":
        statuses, recalls = _evaluation(report, path, session)
        result.update(
            job_statuses=statuses,
            mean_recall=recalls,
            frontend_status="passed",
            children_stopped=True,
        )
    else:
        statuses, recalls = _mutations(report, path)
        result.update(
            job_statuses=statuses,
            mean_recall=recalls,
            frontend_status="passed",
            children_stopped=True,
        )
    result["status"] = "passed"
    return result


def project_report(
    component: str, report_paths: Sequence[Path], *, session: Path
) -> dict[str, Any]:
    """返回严格八字段；非法类型/损坏 schema 只暴露 report_invalid。

    prepare_controlled 仅空路径返回 ready；seed 清理字段 None 留给 runtime。
    退出码、nonce/invocation 绑定与最终 cleanup 不在此模块宣称。
    """
    try:
        return _project_report(component, report_paths, session=session)
    except (
        OSError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        RecursionError,
        OverflowError,
    ):
        raise WorkbenchReportError("report_invalid") from None
