"""B-R2 的受控路径、真实 schema 最小证据和拒绝洗白/泄漏测试。"""

from __future__ import annotations

import copy
import json
import math
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from scripts import workbench_reports as reports

SECRET = "EXTRA_SECRET_QUERY_ACTOR_ENV_RAW_EXCEPTION"
PUBLIC_KEYS = {
    "status",
    "report_paths",
    "checks_passed",
    "checks_failed",
    "job_statuses",
    "mean_recall",
    "frontend_status",
    "children_stopped",
}


@pytest.fixture
def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir(mode=0o755)
    monkeypatch.setattr(reports, "ROOT", root)
    base = root / ".knowledge" / "workbench"
    base.mkdir(parents=True, mode=0o700)
    path = base / str(uuid4())
    path.mkdir(mode=0o700)
    return path


def put(path: Path, value: object, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
    path.chmod(mode)
    return path


def seed_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "passed",
        "checks": dict.fromkeys(reports._SEED_CHECKS, True),
        "steps": [
            {
                "name": name,
                "job": {
                    "id": str(uuid4()),
                    "status": status,
                    "report": {
                        "passed": status == "passed",
                        "metrics": {"case_count": 4, "mean_recall": recall},
                    },
                },
            }
            for name, status, recall in zip(
                ("positive", "fault", "restore"),
                ("passed", "failed", "passed"),
                (1.0, 2 / 3, 1.0),
                strict=True,
            )
        ],
    }


def management_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "passed",
        "checks": dict.fromkeys(reports._B1_CHECKS, True),
        "job_statuses_created_at_desc": ["passed", "failed", "passed"],
        "metrics": {
            "case_count": 4,
            "mean_recall": 2 / 3,
            "report_passed": False,
            "mean_reciprocal_rank": 2 / 3,
            "safe_check_count": 4,
        },
    }


def evaluation_payload(session: Path) -> tuple[Path, dict[str, Any], Path]:
    driver = session / "evaluation" / str(uuid4()) / "driver" / "run"
    seed = seed_payload()
    relative = Path("real-knowledge") / "seed-run" / "report.json"
    seed_path = put(driver / relative, seed)
    ids = [step["job"]["id"] for step in seed["steps"]]
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "passed",
        "checks": dict.fromkeys(reports._B3_CHECKS, True),
        "seed": {
            "report": relative.as_posix(),
            "normal_job_id": ids[0],
            "fault_job_id": ids[1],
            "restore_job_id": ids[2],
        },
        "artifacts": {"seed_report": relative.as_posix()},
        "children_stopped": True,
        "frontend": {
            "status": "passed",
            "tests": {"passed": 1, "skipped": 0},
            "refresh": dict.fromkeys(
                ("new_job_seen", "failure_preserved", "ui_notice_seen", "selection_preserved"), True
            ),
            "comparison": {
                "normal_to_fault": {"comparable": True, "mean_recall_delta": -1 / 3},
                "fault_to_restore": {"comparable": True, "mean_recall_delta": 1 / 3},
            },
        },
    }
    return driver / "report.json", report, seed_path


def mutation_payload() -> dict[str, Any]:
    scope = str(uuid4())
    job_ids = [str(uuid4()) for _ in range(3)]
    command_ids = [str(uuid4()) for _ in range(3)]
    return {
        "status": "passed",
        "scope_id": scope,
        "checks": dict.fromkeys(reports._B4_CHECKS, True),
        "jobs": [
            {
                "id": job_ids[i],
                "status": status,
                "metrics": {"case_count": 4, "mean_recall": recall},
            }
            for i, (status, recall) in enumerate(
                zip(("passed", "failed", "passed"), (1.0, 2 / 3, 1.0), strict=True)
            )
        ],
        "commands": [
            {
                "command_id": command_ids[i],
                "scope_id": scope,
                "committed": True,
                "evaluation_status": status,
                "job_ids": [job_ids[i]],
            }
            for i, status in enumerate(("passed", "failed", "passed"))
        ],
        "children_stopped": True,
        "children": [{"stopped": True}, {"stopped": True}],
        "frontend_update": {
            "status": "passed",
            "command_id": command_ids[0],
            **dict.fromkeys(
                (
                    "preview_core_unchanged",
                    "explicit_confirmation",
                    "response_lost_after_commit",
                    "uncertain_notice_before_get",
                    "identity_scoped_get_recovered",
                    "duplicate_write_prevented",
                    "credential_not_persisted",
                ),
                True,
            ),
        },
        "frontend_recovery": {
            "status": "passed",
            "command_id": command_ids[0],
            **dict.fromkeys(
                (
                    "restart_credential_free_get_only",
                    "old_failure_preserved",
                    "historical_diff_complete",
                    "historical_evidence_available",
                    "comparable",
                ),
                True,
            ),
            "mean_recall_down": -1 / 3,
            "mean_recall_up": 1 / 3,
            "post_count": 0,
        },
    }


def mutation_file(value: dict[str, Any]) -> Path:
    root = reports.ROOT / ".knowledge" / "mutation-demo"
    root.mkdir(mode=0o700, exist_ok=True)
    path = root / value["scope_id"] / "b4-acceptance-report.json"
    return put(path, value)


def smoke_payload(fmt: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "distribution_format": fmt,
        "version": "0.1.0",
        "check_names": sorted(reports._SMOKE_CHECKS),
        "counts": {
            "checks": 9,
            "cli_commands": 6,
            "demo_steps": 8,
            "evaluation_cases": 6,
            "gate_checks": 42,
        },
    }
    for key, names in reports._EXTRA_CHECKS.items():
        payload[key] = {"checks": sorted(names), "version": "0.1.0"}
    payload["quality_acceptance"].update(
        passed=True,
        quality_cases=30,
        active_units=1000,
        p95_seconds=0.2,
        external_model_or_sdk_requests=False,
        automatic_evaluation={
            "configured": True,
            "history_count": 2,
            "manual_exit": 3,
            "update_audit_status": "failed",
        },
    )
    payload["tokens_extra"].update(mock_used=False, model_or_sdk_requests=False)
    payload["postgres_extra"]["business_database_connected"] = False
    return payload


# 从 559fcce3-a270-4739-80e8-ebe3598bd044 的两份实物抄录必要聚合；
# 不从待测常量生成检查名，不保留 env/网络描述/原日志；未分发隐藏目录也能回归。
_DIST_SESSION = ".knowledge/workbench/559fcce3-a270-4739-80e8-ebe3598bd044"
_DIST_DRIVER = f"{_DIST_SESSION}/distribution/f8ddc582-eab6-4ec2-98ba-1a554596ea90/driver"


def actual_smoke_payload(fmt: str) -> dict[str, Any]:
    return {
        "distribution_format": fmt,
        "version": "0.1.0",
        "check_names": [
            "installed_identity",
            "cli_entry_points",
            "packaged_resources",
            "demo_timeline",
            "context_and_stale_filtering",
            "database_schema_capture_history_diff",
            "conversation_review_audit",
            "historical_demo_retrieval",
            "evaluation_baseline_gate",
        ],
        "counts": {
            "checks": 9,
            "cli_commands": 6,
            "demo_steps": 8,
            "evaluation_cases": 6,
            "gate_checks": 42,
        },
        "quality_acceptance": {
            "checks": [
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
            ],
            "version": "0.1.0",
            "passed": True,
            "quality_cases": 30,
            "active_units": 1000,
            "p95_seconds": 0.18823063373565674 if fmt == "wheel" else 0.18929024785757065,
            "external_model_or_sdk_requests": False,
            "automatic_evaluation": {
                "configured": True,
                "history_count": 2,
                "manual_exit": 3,
                "update_audit_status": "failed",
            },
        },
        "api_extra": {
            "checks": [
                "installed_api",
                "no_sdks",
                "asgi_routes",
                "conversation_approval_readonly",
                "database_schema_current_only",
                "readonly",
                "management_disabled_hidden",
                "management_jobs_readonly",
                "mutations_default_404_hidden_lazy_no_tables",
                "cli_management_startup_disposal",
            ],
            "version": "0.1.0",
        },
        "tokens_extra": {
            "checks": [
                "installed_site_packages_identity",
                "tiktoken_version_range",
                "real_english_chinese_emoji_encoding",
                "special_token_spelling_as_ordinary_text",
                "exact_context_max_tokens_budget",
                "no_unrelated_extras",
            ],
            "version": "0.1.0",
            "mock_used": False,
            "model_or_sdk_requests": False,
        },
        "postgres_extra": {
            "checks": [
                "installed_postgres_extra",
                "psycopg_binary",
                "database_schema_collector",
                "standard_dsn_normalization",
                "sanitized_synthetic_failure",
                "no_unrelated_extras",
            ],
            "version": "0.1.0",
            "business_database_connected": False,
        },
    }


@pytest.fixture
def actual_distribution() -> dict[str, dict[str, Any]]:
    return {fmt: actual_smoke_payload(fmt) for fmt in ("wheel", "sdist")}


def put_distribution(session: Path, payloads: dict[str, dict[str, Any]]) -> list[Path]:
    driver = session / "distribution" / str(uuid4()) / "driver"
    return [put(driver / f"{fmt}-smoke-summary.json", value) for fmt, value in payloads.items()]


def test_session_canonical_owned_private_no_symlinks(session: Path) -> None:
    assert reports.validate_session(session) == session
    for candidate in (
        session.parent,
        reports.ROOT,
        session / "child",
        session.parent / session.name.upper(),
        session / ".." / session.name,
    ):
        with pytest.raises(reports.WorkbenchReportError):
            reports.validate_session(candidate)
    session.chmod(0o755)
    with pytest.raises(reports.WorkbenchReportError, match="session_invalid"):
        reports.validate_session(session)
    session.chmod(0o700)
    link = session.parent / str(uuid4())
    link.symlink_to(session, target_is_directory=True)
    with pytest.raises(reports.WorkbenchReportError):
        reports.validate_session(link)


@pytest.mark.parametrize("where", ["base", "scope", "ancestor"])
def test_session_ancestor_symlink(session: Path, where: str) -> None:
    target = {"base": session.parent, "scope": session, "ancestor": reports.ROOT}[where]
    moved = target.with_name(target.name + "-moved")
    target.rename(moved)
    target.symlink_to(moved, target_is_directory=True)
    with pytest.raises(reports.WorkbenchReportError):
        reports.validate_session(session)


@pytest.mark.parametrize("mode", [0o666, 0o660, 0o640, 0o777, 0o000, 0o4600])
def test_read_rejects_abnormal_file_modes(session: Path, mode: int) -> None:
    path = put(session / "report.json", {}, mode)
    with pytest.raises(reports.WorkbenchReportError, match="file_invalid"):
        reports.safe_read_json(path, allowed_root=session)


def test_read_permission_error_is_file_invalid(
    session: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = put(session / "report.json", {"secret": SECRET})
    real_open = os.open
    denied: list[str] = []

    def deny_target(name: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if name == path.name:
            assert kwargs["dir_fd"] >= 0
            assert not flags & os.O_DIRECTORY
            denied.append(name)
            raise PermissionError(SECRET)
        return real_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", deny_target)
    with pytest.raises(reports.WorkbenchReportError) as caught:
        reports.safe_read_json(path, allowed_root=session)
    assert denied == [path.name]
    assert caught.value.code == "file_invalid"
    assert str(caught.value) == "file_invalid"
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    assert SECRET not in str(caught.value)
    assert SECRET not in repr(caught.value)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory", "parent_link"])
def test_read_rejects_links_nonregular_and_ancestry(session: Path, kind: str) -> None:
    path = session / "report.json"
    if kind == "symlink":
        path.symlink_to(put(session / "private.json", {}))
    elif kind == "hardlink":
        os.link(put(session / "private.json", {}), path)
    elif kind == "fifo":
        os.mkfifo(path, 0o600)
    elif kind == "directory":
        path.mkdir()
    else:
        real = session / "real"
        real.mkdir(mode=0o700)
        put(real / "report.json", {})
        (session / "linked").symlink_to(real, target_is_directory=True)
        path = session / "linked" / "report.json"
    with pytest.raises(reports.WorkbenchReportError):
        reports.safe_read_json(path, allowed_root=session)


def test_file_and_directory_owner(session: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = put(session / "report.json", {})
    uid = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: uid + 1)
    with pytest.raises(reports.WorkbenchReportError):
        reports.safe_read_json(path, allowed_root=session)
    with pytest.raises(reports.WorkbenchReportError):
        reports.validate_session(session)


def test_outside_path_rejected_before_open(session: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outside = reports.ROOT / "secret.json"
    other = session.parent / str(uuid4())
    other.mkdir(mode=0o700)
    foreign = put(other / "report.json", {})
    opened: list[object] = []
    real_open = os.open

    def track(path: Any, *args: Any, **kwargs: Any) -> int:
        opened.append(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", track)
    for path, allowed in (
        (outside, reports.ROOT),
        (outside, session),
        (foreign, session),
        (outside, outside.parent),
        (session / ".." / "secret.json", session),
    ):
        with pytest.raises(reports.WorkbenchReportError):
            reports.safe_read_json(path, allowed_root=allowed)
    assert not opened


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":1e9999}',
        b'{"x":1,"x":2}',
        b'{"x":{"s":1,"s":2}}',
        b'{"x":"\xff"}',
        b'{"x":"\\ud800"}',
        b"[]",
        b"null",
        b"{} {}",
        b"\xff\xfe{\x00}\x00",
    ],
)
def test_strict_json_utf8_finite_duplicates(session: Path, raw: bytes) -> None:
    path = session / "report.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    with pytest.raises(reports.WorkbenchReportError) as caught:
        reports.safe_read_json(path, allowed_root=session)
    assert str(caught.value) == caught.value.code
    assert caught.value.__cause__ is None
    assert str(path) not in str(caught.value)


def test_limits(session: Path) -> None:
    raw = b'{"x":"' + b"x" * 100 + b'"}'
    path = session / "report.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    assert reports.safe_read_json(path, allowed_root=session, max_bytes=len(raw))["x"] == "x" * 100
    for limit in (len(raw) - 1, 0, -1, True, 2097153):
        with pytest.raises(reports.WorkbenchReportError):
            reports.safe_read_json(path, allowed_root=session, max_bytes=limit)
    path.write_bytes(b" " * 2097153)
    with pytest.raises(reports.WorkbenchReportError, match="json_too_large"):
        reports.safe_read_json(path, allowed_root=session)


def test_checked_descriptor_rejects_leaf_swap_to_link(
    session: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = put(session / "report.json", {})
    target = put(session / "other.json", {"secret": SECRET})
    real_open = os.open

    def swap(name: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if name == "report.json":
            path.unlink()
            path.symlink_to(target)
        return real_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap)
    with pytest.raises(reports.WorkbenchReportError):
        reports.safe_read_json(path, allowed_root=session)


def test_mutation_reference_is_not_link_and_private_scope_only(session: Path) -> None:
    value = mutation_payload()
    path = mutation_file(value)
    reference = reports.artifact_reference(path, session=session, component="mutations")
    assert reference == path.relative_to(reports.ROOT).as_posix()
    assert not (session / path.name).exists()
    for component in ("seed", "management", "evaluation", "distribution", "launcher"):
        with pytest.raises(reports.WorkbenchReportError):
            reports.artifact_reference(path, session=session, component=component)
    assert (
        reports.artifact_reference(path.parent, session=session, component="prepare_controlled")
        == path.parent.relative_to(reports.ROOT).as_posix()
    )
    path.parent.chmod(0o755)
    with pytest.raises(reports.WorkbenchReportError):
        reports.artifact_reference(path, session=session, component="mutations")


def test_reference_foreign_stale_links(session: Path) -> None:
    foreign = session.parent / str(uuid4())
    foreign.mkdir(mode=0o700)
    path = put(foreign / "report.json", seed_payload())
    with pytest.raises(reports.WorkbenchReportError):
        reports.project_report("seed", [path], session=session)
    stale = put(
        reports.ROOT / ".knowledge" / "real-knowledge-acceptance" / "old" / "report.json",
        seed_payload(),
    )
    with pytest.raises(reports.WorkbenchReportError):
        reports.artifact_reference(stale, session=session, component="seed")
    (session / "report.json").symlink_to(path)
    with pytest.raises(reports.WorkbenchReportError):
        reports.project_report("seed", [session / "report.json"], session=session)


@pytest.mark.parametrize(
    "component,factory", [("seed", seed_payload), ("management", management_payload)]
)
def test_projection_whitelist_real_stage_sequence(
    session: Path, component: str, factory: Callable[[], dict[str, Any]]
) -> None:
    value = factory()
    value.update(
        commands=[SECRET],
        query=SECRET,
        actor=SECRET,
        env={"token": SECRET},
        metadata={"raw": SECRET},
        error_code=SECRET,
        source_report={"all": SECRET},
    )
    value["checks"][SECRET] = True
    path = put(session / component / "report.json", value)
    projected = reports.project_report(component, [path], session=session)
    assert projected["status"] == "passed"
    assert projected["job_statuses"] == ["passed", "failed", "passed"]
    assert projected["children_stopped"] is None
    assert set(projected) == PUBLIC_KEYS
    assert SECRET not in json.dumps(projected)
    assert all(type(r) is float and math.isfinite(r) for r in projected["mean_recall"])


@pytest.mark.parametrize("status", ["failed", "running", "skipped", "unknown", SECRET, None])
def test_driver_status_never_washed_by_good_jobs(session: Path, status: object) -> None:
    value = seed_payload()
    value["status"] = status
    projected = reports.project_report(
        "seed", [put(session / "report.json", value)], session=session
    )
    assert projected["status"] == "failed"
    assert SECRET not in json.dumps(projected)


@pytest.mark.parametrize(
    "checks", [{}, {"anything": True}, {"anything": 1}, {"anything": "true"}, {"anything": [True]}]
)
def test_empty_unknown_or_wrong_type_checks_do_not_pass(session: Path, checks: object) -> None:
    value = seed_payload()
    value["checks"] = checks
    path = put(session / "report.json", value)
    try:
        projection = reports.project_report("seed", [path], session=session)
    except reports.WorkbenchReportError:
        return
    assert projection["status"] != "passed"


def test_false_checks_counts_and_no_secrets(session: Path) -> None:
    value = seed_payload()
    value["checks"]["extra"] = False
    projected = reports.project_report(
        "seed", [put(session / "report.json", value)], session=session
    )
    assert projected["status"] == "failed"
    assert projected["checks_failed"] == 1
    assert type(projected["checks_passed"]) is int


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(schema_version=True),
        lambda p: p["steps"].reverse(),
        lambda p: p["steps"].pop(),
        lambda p: p["steps"][1]["job"].update(status="passed"),
        lambda p: p["steps"][0]["job"].update(id=SECRET),
        lambda p: p["steps"][0]["job"]["report"]["metrics"].update(mean_recall=True),
        lambda p: p["steps"][0]["job"]["report"]["metrics"].update(case_count=True),
        lambda p: p["steps"][0]["job"]["report"]["metrics"].update(mean_recall="1.0"),
        lambda p: p["steps"][1]["job"]["report"]["metrics"].update(mean_recall=1.1),
        lambda p: p["steps"][1]["job"]["report"].update(passed=True),
    ],
)
def test_seed_strict_schema(session: Path, mutation: Callable[[dict[str, Any]], None]) -> None:
    value = seed_payload()
    mutation(value)
    with pytest.raises(reports.WorkbenchReportError):
        reports.project_report("seed", [put(session / "report.json", value)], session=session)


def test_optional_metric_arrays_are_not_fabricated(session: Path) -> None:
    value = seed_payload()
    for step in value["steps"]:
        step["job"]["report"].pop("metrics")
    assert (
        reports.project_report("seed", [put(session / "report.json", value)], session=session)[
            "mean_recall"
        ]
        == []
    )
    value = management_payload()
    value.pop("metrics")
    assert (
        reports.project_report("management", [put(session / "b1.json", value)], session=session)[
            "mean_recall"
        ]
        == []
    )


def test_evaluation_internal_seed_not_latest(session: Path) -> None:
    path, value, _seed = evaluation_payload(session)
    put(path.parent / "real-knowledge" / "zzzz-newer" / "report.json", {"status": "failed"})
    projected = reports.project_report("evaluation", [put(path, value)], session=session)
    assert projected["status"] == "passed"
    assert projected["frontend_status"] == "passed"
    assert projected["children_stopped"] is True
    assert projected["mean_recall"] == [1.0, 2 / 3, 1.0]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(children_stopped=False),
        lambda p: p["frontend"].update(status="skipped"),
        lambda p: p["frontend"]["tests"].update(passed=True),
        lambda p: p["frontend"]["tests"].update(passed=0),
        lambda p: p["frontend"]["tests"].update(skipped=1),
        lambda p: p["frontend"]["refresh"].update(failure_preserved=False),
        lambda p: p["frontend"]["comparison"]["normal_to_fault"].update(mean_recall_delta=0),
        lambda p: p["frontend"]["comparison"]["fault_to_restore"].update(mean_recall_delta="0.3"),
        lambda p: p["frontend"]["comparison"]["fault_to_restore"].update(comparable=False),
        lambda p: p["seed"].update(fault_job_id=str(uuid4())),
    ],
)
def test_evaluation_stage_evidence(
    session: Path, mutation: Callable[[dict[str, Any]], None]
) -> None:
    path, value, _seed = evaluation_payload(session)
    mutation(value)
    with pytest.raises(reports.WorkbenchReportError):
        reports.project_report("evaluation", [put(path, value)], session=session)


@pytest.mark.parametrize(
    "kind",
    [
        "foreign",
        "same_session",
        "traversal",
        "symlink",
        "hardlink",
        "seed_failed",
        "seed_false",
        "missing",
    ],
)
def test_evaluation_nested_seed_is_same_output_safe(session: Path, kind: str) -> None:
    path, value, seed = evaluation_payload(session)
    if kind in {"foreign", "same_session", "traversal"}:
        value["seed"]["report"] = {
            "foreign": "/tmp/report.json",
            "same_session": "../../../../seed/report.json",
            "traversal": "real-knowledge/../report.json",
        }[kind]
        value["artifacts"]["seed_report"] = value["seed"]["report"]
    elif kind == "symlink":
        saved = seed.with_name("saved.json")
        seed.rename(saved)
        seed.symlink_to(saved)
    elif kind == "hardlink":
        os.link(seed, seed.with_name("linked.json"))
    elif kind == "missing":
        seed.unlink()
    else:
        nested = json.loads(seed.read_text())
        if kind == "seed_failed":
            nested["status"] = "failed"
        else:
            nested["checks"]["extra"] = False
        put(seed, nested)
    with pytest.raises(reports.WorkbenchReportError):
        reports.project_report("evaluation", [put(path, value)], session=session)


def test_b4_real_contract(session: Path) -> None:
    value = mutation_payload()
    value.update(query=SECRET, commands_extra=SECRET, metadata={"private": SECRET})
    path = mutation_file(value)
    projected = reports.project_report("mutations", [path], session=session)
    assert projected["status"] == "passed"
    assert projected["job_statuses"] == ["passed", "failed", "passed"]
    assert projected["mean_recall"] == [1.0, 2 / 3, 1.0]
    assert projected["frontend_status"] == "passed"
    assert projected["children_stopped"] is True
    assert set(projected) == PUBLIC_KEYS
    assert SECRET not in json.dumps(projected)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(scope_id=str(uuid4())),
        lambda p: p.update(children_stopped=False),
        lambda p: p["children"][0].update(stopped=False),
        lambda p: p.update(children=[]),
        lambda p: p["jobs"].reverse(),
        lambda p: p["jobs"][1]["metrics"].update(mean_recall=0.9),
        lambda p: p["commands"].pop(),
        lambda p: p["commands"][1].update(evaluation_status="passed"),
        lambda p: p["commands"][0].update(committed=1),
        lambda p: p["frontend_update"].update(status="skipped"),
        lambda p: p["frontend_recovery"].update(old_failure_preserved=False),
        lambda p: p["frontend_recovery"].update(post_count=True),
        lambda p: p["frontend_recovery"].update(mean_recall_up=-1 / 3),
    ],
)
def test_b4_cannot_wash_failure_history(
    session: Path, mutation: Callable[[dict[str, Any]], None]
) -> None:
    value = mutation_payload()
    path = mutation_file(value)
    mutation(value)
    put(path, value)
    with pytest.raises(reports.WorkbenchReportError):
        reports.project_report("mutations", [path], session=session)


def test_b4_mandatory_no_rewrite_check(session: Path) -> None:
    value = mutation_payload()
    value["checks"].pop("restart_same_manifest_recovers")
    assert (
        reports.project_report("mutations", [mutation_file(value)], session=session)["status"]
        == "failed"
    )


def test_distribution_actual_schema_two_fixed_summaries(session: Path) -> None:
    paths = [
        put(session / "distribution" / f"{fmt}-smoke-summary.json", smoke_payload(fmt))
        for fmt in ("wheel", "sdist")
    ]
    projected = reports.project_report("distribution", paths, session=session)
    assert projected["status"] == "passed"
    assert projected["checks_passed"] == 76
    assert projected["checks_failed"] == 0
    assert projected["job_statuses"] == projected["mean_recall"] == []
    assert set(projected) == PUBLIC_KEYS
    with pytest.raises(reports.WorkbenchReportError):
        reports.project_report("distribution", paths[:1], session=session)
    with pytest.raises(reports.WorkbenchReportError):
        reports.project_report("distribution", [paths[0], paths[0]], session=session)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(status="failed"),
        lambda p: p["quality_acceptance"].update(passed=False),
        lambda p: p["quality_acceptance"].update(passed="true"),
        lambda p: p["counts"].update(checks=True),
        lambda p: p["counts"].update(checks=42),
        lambda p: p["check_names"].pop(),
        lambda p: p["api_extra"].update(checks=[]),
        lambda p: p["tokens_extra"].update(mock_used=True),
        lambda p: p["postgres_extra"].update(business_database_connected=True),
        lambda p: p.update(distribution_format="wheel"),
    ],
)
def test_distribution_no_stdout_or_partial_pass(
    session: Path, mutation: Callable[[dict[str, Any]], None]
) -> None:
    wheel, sdist = smoke_payload("wheel"), smoke_payload("sdist")
    mutation(sdist)
    paths = [
        put(session / "wheel-smoke-summary.json", wheel),
        put(session / "sdist-smoke-summary.json", sdist),
    ]
    try:
        projected = reports.project_report("distribution", paths, session=session)
    except reports.WorkbenchReportError:
        return
    assert projected["status"] == "failed"


def test_distribution_session_aggregate_regression(
    session: Path, actual_distribution: dict[str, dict[str, Any]]
) -> None:
    for value in actual_distribution.values():
        value.update(env={"token": SECRET}, raw_log=SECRET, actor=SECRET)
        value["api_extra"]["checks"].append("unproven_future_check")
    paths = put_distribution(session, actual_distribution)
    projected = reports.project_report("distribution", paths[::-1], session=session)
    assert projected["status"] == "passed"
    assert projected["checks_passed"] == 82  # 每种格式 9 + 10 + 10 + 6 + 6。
    assert projected["checks_failed"] == 0
    assert projected["children_stopped"] is None  # 不宣称 runtime 的 cleanup。
    assert projected["report_paths"] == [
        p.relative_to(reports.ROOT).as_posix() for p in paths[::-1]
    ]
    assert set(projected) == PUBLIC_KEYS
    assert SECRET not in json.dumps(projected)
    assert "unproven_future_check" not in json.dumps(projected)


_DIST_CHECK_LOCATIONS = [("core", "check_names")] + [
    (key, "checks") for key in ("quality_acceptance", "api_extra", "tokens_extra", "postgres_extra")
]
_DIST_CHECKS = [
    (scope, field, name)
    for scope, field in _DIST_CHECK_LOCATIONS
    for name in (
        actual_smoke_payload("wheel") if scope == "core" else actual_smoke_payload("wheel")[scope]
    )[field]
]


@pytest.mark.parametrize("fmt", ["wheel", "sdist"])
@pytest.mark.parametrize("scope,field,name", _DIST_CHECKS)
def test_actual_distribution_each_smoke_result_required(
    session: Path,
    actual_distribution: dict[str, dict[str, Any]],
    fmt: str,
    scope: str,
    field: str,
    name: str,
) -> None:
    value = actual_distribution[fmt]
    target = value if scope == "core" else value[scope]
    target[field].remove(name)
    if scope == "core":
        value["counts"]["checks"] -= 1  # 连自洽的计数也不能为缺结果兜底。
    if scope == "api_extra":
        target[field].append("cli_startup_disposal")  # 禁止残缺新布局退回旧 alias。
    with pytest.raises(reports.WorkbenchReportError, match="report_invalid"):
        reports.project_report(
            "distribution", put_distribution(session, actual_distribution), session=session
        )


@pytest.mark.parametrize("fmt", ["wheel", "sdist"])
def test_actual_distribution_removed_cli_alias_check_cannot_replace_entry_points(
    session: Path, actual_distribution: dict[str, dict[str, Any]], fmt: str
) -> None:
    value = actual_distribution[fmt]
    value["check_names"][value["check_names"].index("cli_entry_points")] = "cli_aliases"
    assert value["counts"]["checks"] == len(value["check_names"])
    with pytest.raises(reports.WorkbenchReportError, match="report_invalid"):
        reports.project_report(
            "distribution", put_distribution(session, actual_distribution), session=session
        )


@pytest.mark.parametrize(
    "scope", ["core", "quality_acceptance", "api_extra", "tokens_extra", "postgres_extra"]
)
@pytest.mark.parametrize(
    "marker",
    [
        {"status": "failed"},
        {"status": "skipped"},
        {"status": "running"},
        {"status": "unknown"},
        {"passed": False},
        {"checks_failed": 1},
        {"failed_checks": ["smoke_failed"]},
    ],
)
def test_actual_distribution_explicit_failure_not_washed(
    session: Path,
    actual_distribution: dict[str, dict[str, Any]],
    scope: str,
    marker: dict[str, Any],
) -> None:
    value = actual_distribution["sdist"]
    target = value if scope == "core" else value[scope]
    target.update(marker)
    projected = reports.project_report(
        "distribution", put_distribution(session, actual_distribution), session=session
    )
    assert projected["status"] == "failed"
    assert projected["checks_failed"] == 1
    assert projected["checks_passed"] == 41


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(distribution_format="wheel"),
        lambda p: p.update(distribution_format={"raw": SECRET}),
        lambda p: p.update(version="different"),
        lambda p: p.update(status=True),
        lambda p: p.update(passed="true"),
        lambda p: p.update(checks_failed=True),
        lambda p: p.update(failed_checks="failed"),
        lambda p: p["counts"].update(checks=True),
        lambda p: p["counts"].update(checks=8),
        lambda p: p["counts"].pop("cli_commands"),
        lambda p: p["counts"].update(cli_commands=True),
        lambda p: p["counts"].update(cli_commands="6"),
        lambda p: p["counts"].update(cli_commands=6.0),
        lambda p: p["counts"].update(cli_commands=0),
        lambda p: p["counts"].update(cli_commands=5),
        lambda p: p["counts"].update(cli_commands=7),
        lambda p: p["counts"].update(cli_commands=8),
        lambda p: p["counts"].update(demo_steps=0),
        lambda p: p["check_names"].append(p["check_names"][0]),
        lambda p: p["api_extra"].update(checks={"installed_api": False}),
        lambda p: p["api_extra"]["checks"].append(p["api_extra"]["checks"][0]),
        lambda p: p["api_extra"].update(version="different"),
        lambda p: p["quality_acceptance"].update(passed=1),
        lambda p: p["quality_acceptance"].update(active_units=999),
        lambda p: p["quality_acceptance"]["automatic_evaluation"].update(manual_exit=0),
        lambda p: p["tokens_extra"].update(model_or_sdk_requests=True),
        lambda p: p["postgres_extra"].update(business_database_connected=True),
    ],
)
def test_actual_distribution_bad_schema(
    session: Path,
    actual_distribution: dict[str, dict[str, Any]],
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    mutation(actual_distribution["sdist"])
    with pytest.raises(reports.WorkbenchReportError, match="report_invalid") as caught:
        reports.project_report(
            "distribution", put_distribution(session, actual_distribution), session=session
        )
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize(
    "scope", ["quality_acceptance", "api_extra", "tokens_extra", "postgres_extra"]
)
def test_actual_distribution_missing_whole_smoke(
    session: Path, actual_distribution: dict[str, dict[str, Any]], scope: str
) -> None:
    actual_distribution["wheel"].pop(scope)
    with pytest.raises(reports.WorkbenchReportError):
        reports.project_report(
            "distribution", put_distribution(session, actual_distribution), session=session
        )


@pytest.mark.parametrize(
    "kind", ["manifest", "different_parent", "foreign_session", "symlink", "hardlink"]
)
def test_actual_distribution_wrong_manifest_or_ownership(
    session: Path, actual_distribution: dict[str, dict[str, Any]], kind: str
) -> None:
    paths = put_distribution(session, actual_distribution)
    path = paths[1]
    if kind == "manifest":
        paths[1] = path.with_name("mutation-manifest.json")
        path.rename(paths[1])
    elif kind in {"different_parent", "foreign_session"}:
        parent = (
            session / "unrelated" if kind == "different_parent" else session.parent / str(uuid4())
        )
        paths[1] = put(parent / path.name, actual_distribution["sdist"])
    elif kind == "symlink":
        saved = path.with_name("saved.json")
        path.rename(saved)
        path.symlink_to(saved)
    else:
        os.link(path, path.with_name("linked.json"))
    with pytest.raises(reports.WorkbenchReportError):
        reports.project_report("distribution", paths, session=session)


def test_prepare_empty_ready_only(session: Path) -> None:
    result = reports.project_report("prepare_controlled", [], session=session)
    assert result == {
        "status": "ready",
        "report_paths": [],
        "checks_passed": 0,
        "checks_failed": 0,
        "job_statuses": [],
        "mean_recall": [],
        "frontend_status": None,
        "children_stopped": None,
    }
    for component in ("seed", "management", "evaluation", "mutations", "distribution"):
        with pytest.raises(reports.WorkbenchReportError):
            reports.project_report(component, [], session=session)
    with pytest.raises(reports.WorkbenchReportError):
        reports.project_report(
            "prepare_controlled", [put(session / "report.json", seed_payload())], session=session
        )


def test_typed_summary_and_nonce_bound_receipt_write_roundtrip(session: Path) -> None:
    invocation = str(uuid4())
    driver = session / "seed" / invocation / "driver"
    path = put(driver / "report.json", seed_payload())
    projected = reports.project_report("seed", [path], session=session)
    summary = {
        "schema_version": 1,
        "session_id": session.name,
        "command": "accept",
        "status": "passed",
        "components": [
            {
                "component": "seed",
                **projected,
                "exit_code": 0,
                "timed_out": False,
                "cleanup_verified": True,
            }
        ],
        "artifacts": {},
    }
    receipt = {
        "session_id": session.name,
        "component": "seed",
        "invocation_id": invocation,
        "status": "completed",
        "report_paths": projected["report_paths"],
        "artifacts": {},
        "error_code": None,
    }
    for target, payload in (
        (session / "summary.json", summary),
        (driver.parent / "receipt.json", receipt),
    ):
        reports.write_json_exclusive(target, payload, session=session)
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert reports.safe_read_json(target, allowed_root=session) == payload
        original = target.read_bytes()
        with pytest.raises(reports.WorkbenchReportError, match="report_exists"):
            reports.write_json_exclusive(target, {"changed": True}, session=session)
        assert target.read_bytes() == original
    assert SECRET not in json.dumps(summary)
    # nonce 与 summary 的业务 schema 在 runtime 校验，低层 IO 不把它们擅自放宽或重写。


@pytest.mark.parametrize(
    "bad",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        {1: "wrong-key"},
        (1, 2),
        {1, 2},
        Path("secret"),
        object(),
        "\ud800",
    ],
)
def test_write_strict_finite_json_structure(session: Path, bad: object) -> None:
    target = session / "summary.json"
    with pytest.raises(reports.WorkbenchReportError):
        reports.write_json_exclusive(
            target, {"components": [{"mean_recall": [bad]}]}, session=session
        )
    assert not target.exists()


def test_exclusive_write_symlink_ancestor_and_foreign(session: Path) -> None:
    secret = put(session / "secret.json", {"secret": SECRET})
    target = session / "summary.json"
    target.symlink_to(secret)
    before = secret.read_bytes()
    with pytest.raises(reports.WorkbenchReportError):
        reports.write_json_exclusive(target, {"status": "passed"}, session=session)
    assert secret.read_bytes() == before
    real = session / "real"
    real.mkdir(mode=0o700)
    (session / "alias").symlink_to(real, target_is_directory=True)
    for candidate in (
        session / "alias" / "receipt.json",
        reports.ROOT / "summary.json",
        session / ".." / "foreign.json",
    ):
        with pytest.raises(reports.WorkbenchReportError):
            reports.write_json_exclusive(candidate, {}, session=session)
    assert not (real / "receipt.json").exists()


def test_error_code_does_not_reflect_raw_secret() -> None:
    error = reports.WorkbenchReportError(SECRET)
    assert error.code == "report_invalid"
    assert error.args == ("report_invalid",)
    assert SECRET not in repr(error)


def test_fixture_factories_do_not_share_mutable_checks() -> None:
    first = seed_payload()
    second = copy.deepcopy(first)
    second["checks"]["extra"] = False
    assert "extra" not in first["checks"]


# 这些历史实物仅用于可选的 schema 回归，不授予生产读取任意路径的权限。
# 缺失时可移植测试仍完整执行；固定路径不用 glob、不选“最新一次”。
_FIXED = {
    "seed": ".knowledge/real-knowledge-acceptance/20261113T062525019181Z-11d25751/report.json",
    "management": ".knowledge/b1-management-acceptance-final.json",
    "evaluation": (
        ".knowledge/workbench-evaluation-acceptance/20261116T042018921245Z-951ad2f7/report.json"
    ),
    "evaluation_seed": (
        ".knowledge/workbench-evaluation-acceptance/20261116T042018921245Z-951ad2f7/"
        "real-knowledge/20261116T042018921469Z-ae0094fc/report.json"
    ),
    "mutations": (
        ".knowledge/mutation-demo/c2c9b890-e706-4362-a7fe-e4675edef052/b4-acceptance-report.json"
    ),
    "wheel": f"{_DIST_DRIVER}/wheel-smoke-summary.json",
    "sdist": f"{_DIST_DRIVER}/sdist-smoke-summary.json",
}


def fixed_fixture(key: str) -> dict[str, Any]:
    source = Path(__file__).resolve().parents[1] / _FIXED[key]
    if key in {"wheel", "sdist"}:
        # 实物只经生产 strict reader 引用；只拷贝 fixture 所需的非秘密聚合。
        root = Path(__file__).resolve().parents[1]
        try:
            with pytest.MonkeyPatch.context() as original:
                original.setattr(reports, "ROOT", root)
                original_report = reports.safe_read_json(source, allowed_root=root / _DIST_SESSION)
        except reports.WorkbenchReportError as error:
            if error.code in {"report_missing", "path_invalid"} and not source.exists():
                pytest.skip("固定会话的发行样本未随仓库分发")
            raise
        template = actual_smoke_payload(key)
        aggregate = {
            name: (
                {field: original_report[name][field] for field in fields}
                if type(fields) is dict
                else original_report[name]
            )
            for name, fields in template.items()
        }
        automatic = template["quality_acceptance"]["automatic_evaluation"]
        aggregate["quality_acceptance"]["automatic_evaluation"] = {
            field: original_report["quality_acceptance"]["automatic_evaluation"][field]
            for field in automatic
        }
        return aggregate
    fd = -1
    try:
        fd = os.open(source.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in source.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        leaf = os.open(source.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(leaf, "rb") as stream:
            info = os.fstat(stream.fileno())
            assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
            assert info.st_size <= 2097152
            value: dict[str, Any] = json.loads(stream.read(2097153).decode("utf-8", "strict"))
            return value
    except FileNotFoundError:
        pytest.skip("固定历史验收样本未随仓库分发")
    finally:
        if fd >= 0:
            os.close(fd)


@pytest.mark.parametrize("fmt", ["wheel", "sdist"])
def test_session_distribution_embedded_fixture_matches_original(fmt: str) -> None:
    assert fixed_fixture(fmt) == actual_smoke_payload(fmt)


@pytest.mark.parametrize(
    "component", ["seed", "management", "evaluation", "mutations", "distribution"]
)
def test_fixed_original_driver_reports_project_without_driver_changes(
    session: Path, component: str
) -> None:
    if component == "distribution":
        paths = [
            put(session / "distribution" / f"{fmt}-smoke-summary.json", fixed_fixture(fmt))
            for fmt in ("wheel", "sdist")
        ]
    else:
        value = fixed_fixture(component)
        if component == "mutations":
            paths = [mutation_file(value)]
        else:
            path = session / component / "driver" / "original-run" / "report.json"
            if component == "evaluation":
                nested = fixed_fixture("evaluation_seed")
                assert value["seed"]["report"] == (
                    "real-knowledge/20261116T042018921469Z-ae0094fc/report.json"
                )
                put(path.parent / value["seed"]["report"], nested)
            paths = [put(path, value)]
    projection = reports.project_report(component, paths, session=session)
    assert projection["status"] == "passed"
    assert set(projection) == PUBLIC_KEYS
    assert projection["checks_passed"] > 0
    assert projection["checks_failed"] == 0


@pytest.mark.parametrize("kind", ["format", "counts", "seed_steps", "frontend"])
def test_schema_errors_never_reflect_raw_exceptions(session: Path, kind: str) -> None:
    if kind == "format":
        value = smoke_payload("wheel")
        value["distribution_format"] = {"secret": SECRET}
        paths = [
            put(session / "wheel-smoke-summary.json", value),
            put(session / "sdist-smoke-summary.json", smoke_payload("sdist")),
        ]
        component = "distribution"
    elif kind == "counts":
        value = smoke_payload("wheel")
        value["counts"] = [SECRET]
        paths = [
            put(session / "wheel-smoke-summary.json", value),
            put(session / "sdist-smoke-summary.json", smoke_payload("sdist")),
        ]
        component = "distribution"
    elif kind == "seed_steps":
        value = seed_payload()
        value["steps"] = [SECRET]
        paths, component = [put(session / "report.json", value)], "seed"
    else:
        path, value, _seed = evaluation_payload(session)
        value["frontend"] = {"tests": SECRET}
        paths, component = [put(path, value)], "evaluation"
    with pytest.raises(reports.WorkbenchReportError) as caught:
        reports.project_report(component, paths, session=session)
    assert caught.value.code == "report_invalid"
    assert caught.value.__cause__ is None
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize("target", ["summary", "receipt"])
def test_writer_does_not_grant_mutation_demo_production_writes(session: Path, target: str) -> None:
    value = mutation_payload()
    reference = mutation_file(value)
    with pytest.raises(reports.WorkbenchReportError):
        reports.write_json_exclusive(reference.parent / f"{target}.json", {}, session=session)
    assert not (reference.parent / f"{target}.json").exists()
