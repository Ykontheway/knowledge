"""MCP 发行边界、拒绝门禁和安全父汇总；不改旧发行投影。"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from scripts import installed_mcp_smoke as smoke
from scripts import verify_distribution as distribution

from test_distribution import (
    ENTRY_POINTS,
    NAME,
    RESOURCE,
    SDIST_ROOT,
    VERSION,
    WHEEL_METADATA,
    write_sdist,
    write_wheel,
)

MCP_REQUIREMENT = 'Requires-Dist: mcp<2,>=1.30.0; extra == "mcp"\n'


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("", "exactly one"),
        ("Requires-Dist: mcp>=1.30.0,<2\n", "conditional only"),
        ('Requires-Dist: mcp>=1.30.0,<2; extra == "api"\n', "conditional only"),
        ('Requires-Dist: mcp>=1.30.0,<2; extra != "mcp"\n', "conditional only"),
        (
            'Requires-Dist: mcp>=1.30.0,<2; extra == "mcp" or python_version >= "3"\n',
            "conditional only",
        ),
        (
            'Requires-Dist: mcp>=1.30.0,<2; extra == "mcp" and python_version < "3"\n',
            "conditional only",
        ),
        ('Requires-Dist: mcp>=1.2.0,<2; extra == "mcp"\n', "must pin"),
        ('Requires-Dist: mcp>=1.20.0,<2; extra == "mcp"\n', "must pin"),
        ('Requires-Dist: mcp>=1.29.0,<2; extra == "mcp"\n', "must pin"),
        ('Requires-Dist: mcp>=1.30.0,<3; extra == "mcp"\n', "must pin"),
        ('Requires-Dist: mcp>=1.30.0; extra == "mcp"\n', "must pin"),
        ('Requires-Dist: mcp==1.30.0; extra == "mcp"\n', "must pin"),
        ('Requires-Dist: mcp>=1.30.0,<2,!=1.31; extra == "mcp"\n', "must pin"),
        ('Requires-Dist: mcp[sse]>=1.30.0,<2; extra == "mcp"\n', "must pin"),
        ('Requires-Dist: mcp @ https://example.invalid/mcp.whl; extra == "mcp"\n', "must pin"),
        (MCP_REQUIREMENT * 2, "exactly one"),
    ],
)
def test_artifacts_reject_ineffective_core_or_wrong_mcp_range(
    tmp_path: Path,
    kind: str,
    replacement: str,
    message: str,
) -> None:
    metadata = WHEEL_METADATA.replace(MCP_REQUIREMENT, replacement)
    if kind == "wheel":
        artifact = tmp_path / "bad.whl"
        write_wheel(artifact, overrides={"knowledge_ykforward-0.1.0.dist-info/METADATA": metadata})
        with pytest.raises(ValueError, match=message):
            distribution.inspect_wheel(artifact, NAME, VERSION, (RESOURCE,))
    else:
        artifact = tmp_path / "bad.tar.gz"
        write_sdist(artifact, overrides={f"{SDIST_ROOT}/PKG-INFO": metadata})
        with pytest.raises(ValueError, match=message):
            distribution.inspect_sdist(artifact, NAME, VERSION)


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_artifacts_reject_missing_mcp_extra(tmp_path: Path, kind: str) -> None:
    metadata = WHEEL_METADATA.replace("Provides-Extra: mcp\n", "")
    if kind == "wheel":
        artifact = tmp_path / "bad.whl"
        write_wheel(artifact, overrides={"knowledge_ykforward-0.1.0.dist-info/METADATA": metadata})
        with pytest.raises(ValueError, match="missing the mcp extra"):
            distribution.inspect_wheel(artifact, NAME, VERSION, (RESOURCE,))
    else:
        artifact = tmp_path / "bad.tar.gz"
        write_sdist(artifact, overrides={f"{SDIST_ROOT}/PKG-INFO": metadata})
        with pytest.raises(ValueError, match="missing the mcp extra"):
            distribution.inspect_sdist(artifact, NAME, VERSION)


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
@pytest.mark.parametrize("module", distribution.MCP_MODULES)
def test_artifacts_require_all_mcp_modules(tmp_path: Path, kind: str, module: str) -> None:
    if kind == "wheel":
        artifact = tmp_path / "missing.whl"
        write_wheel(artifact, omit=(module,))
        with pytest.raises(ValueError, match="missing packaged file"):
            distribution.inspect_wheel(artifact, NAME, VERSION, (RESOURCE,))
    else:
        artifact = tmp_path / "missing.tar.gz"
        write_sdist(artifact, omit=(f"{SDIST_ROOT}/src/{module}",))
        with pytest.raises(ValueError, match="missing source file"):
            distribution.inspect_sdist(artifact, NAME, VERSION)


@pytest.mark.parametrize("filename", distribution.MCP_SDIST_FILES)
def test_sdist_requires_service_protocol_and_installed_smoke(tmp_path: Path, filename: str) -> None:
    artifact = tmp_path / "missing.tar.gz"
    write_sdist(artifact, omit=(f"{SDIST_ROOT}/{filename}",))
    with pytest.raises(ValueError, match="missing source file"):
        distribution.inspect_sdist(artifact, NAME, VERSION)


def test_mcp_module_collection_matches_actual_package() -> None:
    root = distribution.PROJECT_ROOT / "src"
    assert {
        path.relative_to(root).as_posix() for path in (root / "knowledge/mcp").glob("*.py")
    } == set(distribution.MCP_MODULES)


@pytest.mark.parametrize(
    "entries",
    [
        ENTRY_POINTS.replace("knowledge-mcp = knowledge.mcp.server:main\n", ""),
        ENTRY_POINTS.replace("knowledge.mcp.server:main", "knowledge.cli:main"),
        ENTRY_POINTS + "unexpected = knowledge.cli:main\n",
    ],
)
def test_wheel_requires_exact_two_consoles(tmp_path: Path, entries: str) -> None:
    artifact = tmp_path / "bad.whl"
    write_wheel(
        artifact, overrides={"knowledge_ykforward-0.1.0.dist-info/entry_points.txt": entries}
    )
    with pytest.raises(ValueError, match="entry points mismatch"):
        distribution.inspect_wheel(artifact, NAME, VERSION, (RESOURCE,))


def safe_summary(mode: str, sdk: str = "1.30.0") -> dict[str, Any]:
    return {
        "version": VERSION,
        "passed": True,
        "mode": mode,
        "sdk_version": None if mode == "base" else sdk,
        "pydantic_version": "2.14.1",
        "checks": list(smoke.BASE_CHECKS if mode == "base" else smoke.EXTRA_CHECKS),
        "counts": {"help_commands": 5, "missing_extra_commands": 2}
        if mode == "base"
        else {
            "tools": 5,
            "sessions": 3,
            "successful_calls": 18,
            "rejected_calls": 39,
            "protocol_responses": 63,
            "unchanged_files": 2,
        },
    }


@pytest.mark.parametrize("mode", ["base", "extra"])
def test_parent_accepts_exact_safe_schema_and_all_checks(mode: str) -> None:
    summary = safe_summary(mode)
    assert distribution.load_mcp_summary(json.dumps(summary), VERSION, mode) == summary
    assert "/" not in json.dumps(summary) and smoke.SECRET not in json.dumps(summary)


@pytest.mark.parametrize(
    "updates",
    [
        {"passed": False},
        {"version": "9.9.9"},
        {"mode": "base"},
        {"checks": []},
        {"checks": ["/absolute/private/secret"]},
        {"raw_sql": "private SQL"},
        {"sdk_version": "2.0.0"},
        {"sdk_version": "1.1.0"},
        {"sdk_version": "1.2.0"},
        {"sdk_version": "1.20.0"},
        {"sdk_version": "1.29.9"},
        {"sdk_version": None},
        {"sdk_version": "/private"},
        {"counts": {}},
        {"counts": {"tools": True}},
    ],
)
def test_parent_rejects_failed_incomplete_or_private_summary(updates: dict[str, Any]) -> None:
    summary = {**safe_summary("extra"), **updates}
    with pytest.raises(RuntimeError, match="safe schema/check/count") as error:
        distribution.load_mcp_summary(json.dumps(summary), VERSION, "extra")
    assert "/absolute" not in str(error.value) and "private SQL" not in str(error.value)


@pytest.mark.parametrize(
    "key",
    [
        "tools",
        "sessions",
        "successful_calls",
        "rejected_calls",
        "protocol_responses",
        "unchanged_files",
    ],
)
@pytest.mark.parametrize("bad_value", [True, -1, "1", 0])
def test_parent_rejects_bad_counts(key: str, bad_value: Any) -> None:
    summary = safe_summary("extra")
    summary["counts"][key] = bad_value
    with pytest.raises(RuntimeError, match="safe schema/check/count"):
        distribution.load_mcp_summary(json.dumps(summary), VERSION, "extra")


def test_parent_rejects_non_json_without_echoing_it() -> None:
    with pytest.raises(RuntimeError) as error:
        distribution.load_mcp_summary(smoke.SECRET, VERSION, "extra")
    assert smoke.SECRET not in str(error.value)


def test_fingerprint_detects_db_changes_and_new_sidecars(tmp_path: Path) -> None:
    database = tmp_path / "sandbox.db"
    database.write_bytes(b"fixture")
    before = smoke.fingerprint(tmp_path)
    database.write_bytes(b"modified")
    assert smoke.fingerprint(tmp_path) != before
    database.write_bytes(b"fixture")
    assert smoke.fingerprint(tmp_path) == before
    (tmp_path / "sandbox.db-wal").touch()
    assert smoke.fingerprint(tmp_path) != before


@pytest.mark.parametrize("key", sorted(smoke.FORBIDDEN_KEYS))
def test_nested_metadata_allowlist_rejects_private_keys(key: str) -> None:
    with pytest.raises(AssertionError, match="private metadata"):
        smoke.assert_metadata_safe({"blocks": [{key: "value"}]})


def test_smoke_failure_stdout_empty_and_stderr_fixed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(_version: str, _mode: str) -> str:
        raise RuntimeError(smoke.SECRET + "/absolute/path raw SQL")

    monkeypatch.setattr(smoke, "verify_identity", fail)
    assert smoke.main(["--expected-version", VERSION, "--mode", "extra"]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "installed MCP smoke failed\n"


@pytest.mark.parametrize("distribution_format", ["wheel", "sdist"])
def test_orchestrator_keeps_old_layout_and_sdk_only_in_new_extra_venvs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    distribution_format: str,
) -> None:
    events: list[tuple[str, Any]] = []
    old_summary = {"passed": True, "checks": ["existing_check"]}
    replay_summary = {"passed": True, "mode": "replay_core", "jobs": 3, "diffs": 16}

    def run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        events.append(("run", command))
        if (
            len(command) == 3
            and command[1] == "-I"
            and Path(command[2]).name == "installed_replay_smoke.py"
        ):
            assert command[0] == str(tmp_path / f"{distribution_format}-venv/bin/python")
            assert Path(command[2]).is_file()
            events.append(("replay", command[0]))
            return subprocess.CompletedProcess(command, 0, json.dumps(replay_summary), "")
        return subprocess.CompletedProcess(command, 0, json.dumps(old_summary), "")

    def python_path(venv: Path) -> Path:
        return venv / "bin/python"

    def mcp_run(python: Path, script: Path, version: str, mode: str) -> dict[str, Any]:
        assert script.parent == tmp_path / f"{distribution_format}-run" and script.is_file()
        assert version == VERSION
        events.append(("mcp", (python, mode)))
        return safe_summary(mode)

    monkeypatch.setattr(distribution, "_run", run)
    monkeypatch.setattr(distribution, "_venv_python", python_path)
    monkeypatch.setattr(distribution, "_run_mcp_smoke", mcp_run)

    def controlled_run(python: Path, script: Path, version: str) -> dict[str, Any]:
        assert python == tmp_path / f"{distribution_format}-mcp-venv/bin/python"
        assert script.parent == tmp_path / f"{distribution_format}-run" and script.is_file()
        assert script.with_name("installed_mcp_smoke.py").is_file()
        assert version == VERSION
        events.append(("controlled", python))
        return {"passed": True, "mode": "controlled_extra"}

    monkeypatch.setattr(distribution, "_run_mcp_controlled_smoke", controlled_run)
    artifact = tmp_path / ("artifact.whl" if distribution_format == "wheel" else "artifact.tar.gz")
    summary = distribution._smoke_install(
        uv="uv",
        target_python="python",
        artifact=artifact,
        distribution_format=distribution_format,
        version=VERSION,
        scratch=tmp_path,
        fixtures=tmp_path,
        tiktoken_cache=tmp_path / "token-cache",
    )
    assert set(summary) == {
        "passed",
        "checks",
        "quality_acceptance",
        "api_extra",
        "tokens_extra",
        "postgres_extra",
        "mcp_extra",
        "mcp_controlled_extra",
        "replay_core",
    }
    assert summary["replay_core"] == replay_summary
    assert sum(kind == "replay" for kind, _ in events) == 1
    assert summary["mcp_controlled_extra"] == {"passed": True, "mode": "controlled_extra"}
    assert sum(kind == "controlled" for kind, _ in events) == 1
    for key in ("quality_acceptance", "api_extra", "tokens_extra", "postgres_extra"):
        assert summary[key] == old_summary
    assert summary["checks"] == old_summary["checks"]
    assert summary["mcp_extra"]["core_base"] == safe_summary("base")
    assert summary["mcp_extra"]["sdk_version"] == "1.30.0"
    assert summary["mcp_extra"]["test_label"] == "default1.30"
    minimum = summary["mcp_extra"]["minimum_sdk"]
    assert minimum == {**safe_summary("extra"), "test_label": "min1.30"}
    assert "test_dependency_constraints" not in minimum
    base_index = next(
        i for i, (kind, value) in enumerate(events) if kind == "mcp" and value[1] == "base"
    )
    installs = [
        (i, command)
        for i, (kind, command) in enumerate(events)
        if kind == "run" and command[1:3] == ["pip", "install"]
    ]
    assert installs[0][0] < base_index < installs[1][0]
    assert len(installs) == 6
    for _, command in installs:
        if any("[mcp]" in part or "mcp==" in part for part in command):
            assert "-mcp-" in command[4]
        else:
            assert "-mcp-" not in command[4]
    mcp_installs = [command for _, command in installs if f"{artifact}[mcp]" in command]
    assert mcp_installs == [
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(tmp_path / f"{distribution_format}-mcp-venv/bin/python"),
            f"{artifact}[mcp]",
        ],
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(tmp_path / f"{distribution_format}-mcp-minimum-venv/bin/python"),
            f"{artifact}[mcp]",
            "mcp==1.30.0",
        ],
    ]
    assert not any(
        "pydantic" in part or "backport" in part for _, command in installs for part in command
    )


@pytest.mark.parametrize("sdk", ["1.30.0", "1.31.0", "1.99.9"])
def test_parent_accepts_public_sdk_range_without_pydantic_compatibility_pin(sdk: str) -> None:
    summary = safe_summary("extra", sdk)
    assert distribution.load_mcp_summary(json.dumps(summary), VERSION, "extra") == summary


@pytest.fixture
def installed_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """保留 verify_identity 的 SDK 导入控制流，只替换安装位置/依赖检测。"""
    import sys

    monkeypatch.delitem(sys.modules, "mcp", raising=False)
    monkeypatch.delitem(sys.modules, "knowledge.mcp.server", raising=False)
    monkeypatch.setattr(smoke, "is_installed", lambda _path: True)
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)


@pytest.mark.usefixtures("installed_identity")
@pytest.mark.parametrize("sdk", ["1.2.0", "1.20.0", "1.29.9", "2.0.0", "1.30.0"])
def test_installed_identity_enforces_public_sdk_floor(
    monkeypatch: pytest.MonkeyPatch,
    sdk: str,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        importlib, "import_module", lambda _name: SimpleNamespace(__file__=__file__)
    )
    monkeypatch.setattr(
        importlib.metadata, "version", lambda name: sdk if name == "mcp" else VERSION
    )
    if sdk == "1.30.0":
        assert smoke.verify_identity(VERSION, "extra") == sdk
    else:
        with pytest.raises(AssertionError, match="SDK outside public range"):
            smoke.verify_identity(VERSION, "extra")


@pytest.mark.usefixtures("installed_identity")
def test_installed_but_broken_sdk_fails_not_skips(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        importlib.metadata, "version", lambda name: "1.30.0" if name == "mcp" else VERSION
    )
    imported: list[str] = []

    def broken_import(name: str) -> Any:
        imported.append(name)
        raise ImportError("cannot import eval_type_backport " + smoke.SECRET)

    monkeypatch.setattr(importlib, "import_module", broken_import)
    assert smoke.main(["--expected-version", VERSION, "--mode", "extra"]) == 1
    captured = capsys.readouterr()
    assert imported == ["mcp"]
    assert captured.out == "" and captured.err == "installed MCP smoke failed\n"


def test_parent_fails_nonzero_smoke_even_with_passing_stdout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 1, json.dumps(safe_summary("extra")), smoke.SECRET
        ),
    )
    with pytest.raises(RuntimeError, match="isolated installed MCP extra smoke failed") as error:
        distribution._run_mcp_smoke(tmp_path / "python", tmp_path / "smoke.py", VERSION, "extra")
    assert smoke.SECRET not in str(error.value)
