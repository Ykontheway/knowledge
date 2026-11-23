from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
import scripts.workbench_evaluation_acceptance as acceptance
from scripts.real_knowledge_acceptance import ROOT as REAL_KNOWLEDGE_ROOT


def make_seed_run(run_dir: Path) -> tuple[Path, Path, Path]:
    seed_dir = run_dir / "real-knowledge" / "20261116T120000000000Z-seed1234"
    (seed_dir / "documents" / "docs").mkdir(parents=True)
    database = seed_dir / "knowledge.db"
    database.write_bytes(b"SQLite format 3\x00seed")
    document_copy = seed_dir / "documents" / "docs" / "auto-evaluation.md"
    document_copy.write_text(
        f"# 标题\n\n{acceptance.FOLLOWUP_ANCHOR}\n",
        encoding="utf-8",
    )
    report_path = seed_dir / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "dataset": {"hash": "a" * 64, "case_count": 4},
                "steps": [
                    {"name": "positive", "job": {"id": "11111111-1111-1111-1111-111111111111"}},
                    {"name": "fault", "job": {"id": "22222222-2222-2222-2222-222222222222"}},
                    {"name": "restore", "job": {"id": "33333333-3333-3333-3333-333333333333"}},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return report_path, database, document_copy


def frontend_summary() -> dict[str, object]:
    return {
        "status": "passed",
        "tests": {"passed": 1, "skipped": 0},
        "comparison": {
            "normal_to_fault": {
                "comparable": True,
                "mean_recall_delta": -0.25,
            },
            "fault_to_restore": {
                "comparable": True,
                "mean_recall_delta": 0.25,
            },
        },
        "refresh": {
            "new_job_seen": True,
            "failure_preserved": True,
            "ui_notice_seen": True,
            "selection_preserved": True,
        },
    }


def test_build_followup_text_inserts_note_once() -> None:
    original = f"前文\n{acceptance.FOLLOWUP_ANCHOR}\n后文\n"
    updated = acceptance.build_followup_text(original)
    assert updated != original
    assert updated.count(acceptance.FOLLOWUP_ANCHOR) == 1
    assert acceptance.FOLLOWUP_NOTE in updated
    with pytest.raises(acceptance.AcceptanceError):
        acceptance.build_followup_text(updated)


def test_load_seed_context_reads_isolated_copy_and_ids(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    report_path, database, document_copy = make_seed_run(run_dir)

    seed = acceptance.load_seed_context(report_path, run_dir)

    assert seed.report_path == report_path.resolve()
    assert seed.database == database
    assert seed.document_copy == document_copy
    assert seed.normal_job_id == "11111111-1111-1111-1111-111111111111"
    assert seed.fault_job_id == "22222222-2222-2222-2222-222222222222"
    assert seed.restore_job_id == "33333333-3333-3333-3333-333333333333"
    assert seed.dataset_hash == "a" * 64
    assert seed.case_count == 4


def test_build_vitest_environment_excludes_runtime_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    report_path, _, _ = make_seed_run(run_dir)
    seed = acceptance.load_seed_context(report_path, run_dir)
    runner = acceptance.Runner(tmp_path)
    runner.secret = "runtime-secret"
    monkeypatch.setenv("KNOWLEDGE_API_KEY", "old-secret")
    monkeypatch.setenv("KNOWLEDGE_MANAGEMENT_ORIGIN", "http://evil:9999")
    monkeypatch.setenv("VITE_LEAK", "bad")

    environment = runner.build_vitest_environment(
        seed,
        "http://127.0.0.1:4173",
        runner.run_dir / "frontend-summary.json",
    )

    assert "KNOWLEDGE_API_KEY" not in environment
    assert "KNOWLEDGE_MANAGEMENT_ORIGIN" not in environment
    assert not any(key.startswith("VITE_") for key in environment)
    assert environment["KNOWLEDGE_ACCEPTANCE"] == "1"
    assert environment["KNOWLEDGE_ACCEPTANCE_WEB_ORIGIN"] == "http://127.0.0.1:4173"
    assert environment["KNOWLEDGE_ACCEPTANCE_FOLLOWUP_NOTE"] == acceptance.FOLLOWUP_NOTE


def test_runner_orchestrates_mocked_success_and_cleans_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = acceptance.Runner(tmp_path)
    report_path, _, _ = make_seed_run(runner.run_dir)
    backend = MagicMock(pid=123001)
    web = MagicMock(pid=123002)
    backend.poll.return_value = None
    web.poll.return_value = None

    monkeypatch.setattr(acceptance, "run_acceptance", lambda _output_dir: report_path)
    monkeypatch.setattr(acceptance, "spawn", MagicMock(side_effect=[backend, web]))
    monkeypatch.setattr(acceptance, "wait_backend", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(acceptance, "wait_web", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(acceptance, "wait_web_http", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "scripts.workbench_evaluation_acceptance.secrets.token_urlsafe",
        lambda _size: "runtime-secret",
    )

    def fake_cleanup(children: list[MagicMock]) -> None:
        for child in children:
            child.poll.return_value = 0

    monkeypatch.setattr(acceptance, "cleanup", fake_cleanup)

    def fake_subprocess_run(*arguments: object, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        env = cast(dict[str, str], kwargs["env"])
        frontend_report = Path(env["KNOWLEDGE_ACCEPTANCE_FRONTEND_REPORT"])
        frontend_report.write_text(
            json.dumps(frontend_summary(), ensure_ascii=False),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            args=list(cast(list[str], arguments[0])) if arguments else [],
            returncode=0,
            stdout="vitest ok",
            stderr="",
        )

    monkeypatch.setattr(
        "scripts.workbench_evaluation_acceptance.subprocess.run",
        fake_subprocess_run,
    )

    result = runner.run()
    payload = json.loads(result.read_text(encoding="utf-8"))
    rendered = result.read_text(encoding="utf-8")

    assert payload["status"] == "passed"
    assert payload["children_stopped"] is True
    assert payload["frontend"]["status"] == "passed"
    assert payload["checks"]["frontend_new_job_seen"] is True
    assert len(payload["commands"]) == 3
    assert "runtime-secret" not in rendered
    assert str(runner.run_dir) not in rendered


def test_runner_failure_writes_safe_report_without_secret_or_root_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = acceptance.Runner(tmp_path)
    child = MagicMock(pid=123003)
    child.poll.return_value = None

    def fail(self: acceptance.Runner) -> None:
        self.secret = "runtime-secret"
        self.children.append(child)
        raise RuntimeError(f"private {self.secret} {REAL_KNOWLEDGE_ROOT}")

    def fake_cleanup(children: list[MagicMock]) -> None:
        for current in children:
            current.poll.return_value = 0

    monkeypatch.setattr(acceptance.Runner, "execute", fail)
    monkeypatch.setattr(acceptance, "cleanup", fake_cleanup)

    result = runner.run()
    payload = json.loads(result.read_text(encoding="utf-8"))
    rendered = result.read_text(encoding="utf-8")

    assert payload["status"] == "failed"
    assert payload["error_code"] == "RUNTIMEERROR"
    assert payload["children_stopped"] is True
    assert "runtime-secret" not in rendered
    assert str(REAL_KNOWLEDGE_ROOT) not in rendered
