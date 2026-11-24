"""固定布局的发行契约；隔离执行实际内联脚本验证正例与拒绝路径。

不解析任意 YAML。门禁逐 step 与当前 CI 比较，manifest 测试只使用临时小文件，
不构建项目、不替换校验代码、不执行 Twine 上传，也不访问真实发行服务。
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Ykontheway/knowledge"
BRANCH = "aime/1793676007-v02-demo-web"
PROJECT_NAME = "knowledge-ykforward"
VERSION = "0.1.0"
TEST_SHA = "e" * 40  # 仅临时 fixture；workflow 不固定源 SHA 或发行摘要。
WHEEL = "knowledge_ykforward-0.1.0-py3-none-any.whl"
SDIST = "knowledge_ykforward-0.1.0.tar.gz"
EXPECTED_FILES = {WHEEL, SDIST}
GENERATOR = "Generate constrained release manifest"
VERIFIER = "Reverify constrained release manifest"


def _contract_text(text: str) -> str:
    return "\n".join(
        line.rstrip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


WORKFLOW = _contract_text((ROOT / ".github/workflows/publish-pypi.yml").read_text(encoding="utf-8"))
CI = _contract_text((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))


def _blocks(text: str, pattern: str) -> dict[str, str]:
    matches = list(re.finditer(pattern, text, re.MULTILINE))
    names = [match.group(1) for match in matches]
    assert len(names) == len(set(names)), "文本契约不允许重名块"
    return {
        match.group(1): text[match.start() : matches[index + 1].start()]
        if index + 1 < len(matches)
        else text[match.start() :]
        for index, match in enumerate(matches)
    }


def _jobs(text: str = WORKFLOW) -> dict[str, str]:
    assert text.count("\njobs:\n") == 1
    return _blocks(text.split("\njobs:\n", 1)[1], r"^  ([a-z]+):$")


def _steps(job: str) -> dict[str, str]:
    assert job.count("\n    steps:\n") == 1
    return _blocks(job.split("\n    steps:\n", 1)[1], r"^      - name: (.+)$")


def _header(job: str) -> str:
    return job.split("\n    steps:\n", 1)[0]


def _run(step: str) -> str:
    assert len(re.findall(r"^        run:", step, re.MULTILINE)) == 1
    if "        run: |\n" in step:
        return dedent(step.split("        run: |\n", 1)[1]).strip()
    return step.split("        run: ", 1)[1].strip()


def _script(job_name: str) -> str:
    step_name = GENERATOR if job_name == "quality" else VERIFIER
    step = _steps(_jobs()[job_name])[step_name]
    assert "        env:\n          RELEASE_SHA: ${{ github.sha }}\n" in step
    prefix, script = _run(step).split("<<'PY'\n", 1)
    directory = (
        '"$RUNNER_TEMP/distribution"' if job_name == "quality" else '"verified-distribution"'
    )
    assert prefix == f"set -euo pipefail\npython3 -I - {directory} "
    assert script.endswith("\nPY")
    return script.removesuffix("\nPY")


def _norm(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _execute(
    job_name: str, distribution: Path, sha: str = TEST_SHA
) -> subprocess.CompletedProcess[str]:
    # 原样执行 workflow 的内联实现；不做 script.replace 或摘要替换。
    return subprocess.run(
        [sys.executable, "-I", "-", str(distribution)],
        input=_script(job_name),
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
        env={"RELEASE_SHA": sha},
    )


def _assert_rejected(result: subprocess.CompletedProcess[str], error: str) -> None:
    assert result.returncode != 0, "内联 verifier 错误接受了反例"
    assert error in result.stderr
    assert result.stdout == ""


def _fixture_distribution(tmp_path: Path, sha: str = TEST_SHA) -> Path:
    distribution = tmp_path / "distribution"
    build = distribution / "build"
    build.mkdir(parents=True)
    for name in EXPECTED_FILES:
        (build / name).write_bytes(f"fixture bytes: {name}".encode())
    result = _execute("quality", distribution, sha)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    return distribution


def _manifest(distribution: Path) -> dict[str, Any]:
    value = json.loads((distribution / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_only_opt_in_dispatch_with_minimal_permissions() -> None:
    top = _blocks(WORKFLOW.split("\njobs:\n", 1)[0], r"^([a-z]+):.*$")
    assert set(top) == {"name", "on", "permissions", "concurrency"}
    assert (
        top["on"].strip()
        == dedent(
            """\
        on:
          workflow_dispatch:
            inputs:
              publish:
                description: '通过所有门禁后上传 knowledge-ykforward 0.1.0 到 PyPI'
                type: boolean
                default: false
        """
        ).strip()
    )
    assert top["permissions"].strip() == "permissions:\n  contents: read"
    assert WORKFLOW.count("permissions:") == 1
    assert top["concurrency"].strip() == (
        f"concurrency:\n  group: release-{PROJECT_NAME}-{VERSION}\n  cancel-in-progress: false"
    )
    assert set(_jobs()) == {"quality", "postgres", "web", "lancedb", "publish"}
    assert not re.search(r"\b(source_sha|upload_url|package_version)\b", WORKFLOW)
    assert not re.search(r"\b[0-9a-f]{40,64}\b", WORKFLOW)  # 不嵌入旧源或静态发行摘要。
    assert "github.event.head_commit" not in WORKFLOW
    assert "contains(" not in WORKFLOW


@pytest.mark.parametrize("job_name", ["quality", "postgres", "web", "lancedb"])
def test_check_jobs_reuse_all_ci_steps_and_configuration(job_name: str) -> None:
    job = _jobs()[job_name]
    source_job = _jobs(CI)[job_name]
    header = re.sub(r"^    (if|timeout-minutes):.*(?:\n|$)", "", _header(job), flags=re.MULTILINE)
    assert header.strip() == _header(source_job).strip()
    assert f"    if: github.repository == '{REPOSITORY}'" in _header(job)
    steps = _steps(job)
    source_steps = _steps(source_job)
    extra_steps = {GENERATOR, "Check release metadata strictly"} if job_name == "quality" else set()
    assert set(steps) == set(source_steps) | extra_steps
    assert [name for name in steps if name not in extra_steps] == list(source_steps)
    for name, source_step in source_steps.items():
        if name == "Check out repository":
            continue  # 当前 workflow SHA 的独立契约见下。
        step = steps[name]
        if name == "Install uv":
            step = re.sub(r'^          version: "0\.12\.15"\n', "", step, flags=re.MULTILINE)
        if name == "Upload verified distributions and smoke summaries":
            # 唯一附加路径为本次生成的 manifest；不放宽已有 artifact/evidence 契约。
            step = step.replace("            ${{ runner.temp }}/distribution/manifest.json\n", "")
        assert step.strip() == source_step.strip(), f"未完整复用 CI step: {name}"


@pytest.mark.parametrize("job_name", ["quality", "postgres", "web", "lancedb"])
def test_every_checkout_is_current_workflow_sha_without_credentials(job_name: str) -> None:
    checkout = _steps(_jobs()[job_name])["Check out repository"]
    expected = dedent(
        """\
          - name: Check out repository
            uses: actions/checkout@v4
            with:
              ref: ${{ github.sha }}
              persist-credentials: false
        """
    )
    assert _norm(checkout) == _norm(expected)
    assert len(re.findall(r"uses: actions/checkout@", _jobs()[job_name])) == 1
    assert WORKFLOW.count("uses: actions/checkout@") == 4
    assert WORKFLOW.count("ref: ${{ github.sha }}") == 4


@pytest.mark.parametrize("job_name", ["quality", "postgres", "lancedb", "publish"])
def test_uv_is_pinned_and_timeouts_are_bounded(job_name: str) -> None:
    setup = _steps(_jobs()[job_name])["Install uv"]
    assert 'uses: astral-sh/setup-uv@v6\n        with:\n          version: "0.12.15"' in setup
    assert WORKFLOW.count("uses: astral-sh/setup-uv@") == 4
    for candidate in _jobs().values():
        timeout = re.findall(r"^    timeout-minutes: (\d+)$", candidate, re.MULTILINE)
        assert len(timeout) == 1 and 25 <= int(timeout[0]) <= 40


def test_quality_keeps_all_python_lanes_and_manifest_follows_smokes() -> None:
    quality = _jobs()["quality"]
    assert 'python-version: ["3.11", "3.12", "3.13"]' in _header(quality)
    assert "    env:\n      NO_COLOR: '1'\n      TERM: dumb" in _header(quality)
    steps = _steps(quality)
    smoke = "Verify wheel and source distribution (core-only, quality, api, postgres, and tokens)"
    names = list(steps)
    index = names.index(smoke)
    assert names[index + 1 : index + 3] == [GENERATOR, "Check release metadata strictly"]
    assert "if:" not in steps[smoke]
    for name in names[index + 1 : index + 3]:
        assert "        if: matrix.python-version == '3.11'" in steps[name]
    artifact = steps["Upload verified distributions and smoke summaries"]
    assert "name: distribution-${{ matrix.python-version }}" in artifact
    for suffix in ("build/*.whl", "build/*.tar.gz", "*-smoke-summary.json", "manifest.json"):
        assert "${{ runner.temp }}/distribution/" + suffix in artifact
    assert names.index("Check release metadata strictly") < names.index(
        "Upload verified distributions and smoke summaries"
    )


def test_publish_gate_is_exact_opt_in_and_needs_every_successful_check() -> None:
    header = _header(_jobs()["publish"])
    assert "    needs: [quality, postgres, web, lancedb]" in header
    gate = header.split("    if: >-\n", 1)[1].split("\n    runs-on:", 1)[0]
    assert " ".join(gate.split()) == (
        f"${{{{ github.repository == '{REPOSITORY}' && "
        f"(github.ref == 'refs/heads/{BRANCH}' || github.ref == 'refs/heads/main') && "
        "github.event_name == 'workflow_dispatch' && inputs.publish == true }}"
    )
    # GitHub 隐式 success() 要求全部 needs 成功；无失败/跳过旁路。
    assert not any(value in header for value in ("always()", "!cancelled()", "failure()"))
    assert "github.event.inputs.publish" not in header  # 不可用字符串代替 boolean。
    assert WORKFLOW.count("uv publish ") == 1
    assert "uv publish" not in WORKFLOW.split("\n  publish:\n", 1)[0]


def test_publish_downloads_same_run_and_never_checks_out_or_builds() -> None:
    publish = _jobs()["publish"]
    steps = _steps(publish)
    assert list(steps) == [
        "Install uv",
        "Download verified distributions",
        VERIFIER,
        "Recheck release metadata strictly",
        "Upload to PyPI",
    ]
    expected = dedent(
        """\
          - name: Download verified distributions
            uses: actions/download-artifact@v4
            with:
              name: distribution-3.11
              path: verified-distribution
        """
    )
    assert _norm(steps["Download verified distributions"]) == _norm(expected)
    assert 'python-version: "3.11"\n          enable-cache: false' in steps["Install uv"]
    for prohibited in (
        "checkout@",
        "repository:",
        "run-id:",
        "github-token:",
        "uv build",
        "uv sync",
        "uv run",
        "scripts/",
        "pip install",
        "tar ",
        "unzip ",
    ):
        assert prohibited not in publish
    assert 'python3 -I - "verified-distribution"' in publish


@pytest.mark.parametrize("job_name", ["quality", "publish"])
def test_manifest_scripts_fix_names_and_only_import_stdlib(job_name: str) -> None:
    tree = ast.parse(_script(job_name))
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "expected" for target in node.targets)
    ]
    assert len(assignments) == 1
    assert ast.literal_eval(assignments[0].value) == EXPECTED_FILES
    imports = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imports == {"hashlib", "json", "os", "re", "sys", "pathlib"}
    assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree))
    assert "${{" not in _script(job_name)  # SHA 经 env 传递，不插值到 Python 源码。


@pytest.mark.parametrize("sha", [TEST_SHA, "a" * 40])
@pytest.mark.parametrize("marker", [None, b"*", b"*\n"])
@pytest.mark.parametrize("with_summaries", [False, True])
def test_generated_manifest_roundtrips_actual_bytes(
    sha: str, marker: bytes | None, with_summaries: bool, tmp_path: Path
) -> None:
    distribution = _fixture_distribution(tmp_path, sha)
    build = distribution / "build"
    manifest = _manifest(distribution)
    assert manifest == {
        "github_sha": sha,
        "project_name": PROJECT_NAME,
        "version": VERSION,
        "files": {
            name: hashlib.sha256((build / name).read_bytes()).hexdigest() for name in EXPECTED_FILES
        },
    }
    if marker is not None:
        (build / ".gitignore").write_bytes(marker)
    if with_summaries:
        for format_name in ("wheel", "sdist"):
            (distribution / f"{format_name}-smoke-summary.json").write_text("{}", encoding="utf-8")
    result = _execute("publish", distribution, sha)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("marker", [None, b"*", b"*\n"])
def test_generator_accepts_only_valid_marker_and_fresh_digest(
    marker: bytes | None, tmp_path: Path
) -> None:
    distribution = _fixture_distribution(tmp_path)
    before = _manifest(distribution)
    (distribution / "manifest.json").unlink()
    if marker is not None:
        (distribution / "build/.gitignore").write_bytes(marker)
    (distribution / "build" / WHEEL).write_bytes(b"new run bytes, not a frozen historical artifact")
    result = _execute("quality", distribution)
    assert result.returncode == 0, result.stderr
    after = _manifest(distribution)
    assert after["files"][WHEEL] != before["files"][WHEEL]
    assert after["files"][SDIST] == before["files"][SDIST]
    assert _execute("publish", distribution).returncode == 0


BUILD_CASES = [
    ("missing_file", "exactly the two fixed files"),
    ("extra_file", "exactly the two fixed files"),
    ("wrong_version", "exactly the two fixed files"),
    ("wrong_name", "exactly the two fixed files"),
    ("nested_directory", "exactly the two fixed files"),
    ("directory_as_wheel", "must be a regular file"),
    ("symlink_as_wheel", "must be a regular file"),
    ("dangling_symlink_as_wheel", "must be a regular file"),
    ("symlink_build", "directory is missing or invalid"),
    ("symlink_distribution", "directory is missing or invalid"),
    ("invalid_marker", "Invalid build-directory marker"),
    ("symlink_marker", "Invalid build-directory marker"),
    ("dangling_symlink_marker", "Invalid build-directory marker"),
    ("directory_marker", "Invalid build-directory marker"),
]


@pytest.mark.parametrize("job_name", ["quality", "publish"])
@pytest.mark.parametrize(("case", "error"), BUILD_CASES)
def test_build_verification_fails_closed(
    job_name: str, case: str, error: str, tmp_path: Path
) -> None:
    distribution = _fixture_distribution(tmp_path)
    build = distribution / "build"
    wheel = build / WHEEL
    if job_name == "quality":
        (distribution / "manifest.json").unlink()
    if case == "missing_file":
        wheel.unlink()
    elif case == "extra_file":
        (build / "unexpected.whl").write_bytes(b"extra")
    elif case == "wrong_version":
        wheel.rename(build / "knowledge_ykforward-0.2.0-py3-none-any.whl")
    elif case == "wrong_name":
        wheel.rename(build / "other_project-0.1.0-py3-none-any.whl")
    elif case == "nested_directory":
        (build / "unexpected").mkdir()
    elif case == "directory_as_wheel":
        wheel.unlink()
        wheel.mkdir()
    elif case in {"symlink_as_wheel", "dangling_symlink_as_wheel"}:
        target = tmp_path / "target.whl"
        wheel.rename(target)
        if case == "dangling_symlink_as_wheel":
            target.unlink()
        wheel.symlink_to(target)
    elif case == "symlink_build":
        target = tmp_path / "real-build"
        build.rename(target)
        build.symlink_to(target, target_is_directory=True)
    elif case == "symlink_distribution":
        target = tmp_path / "real-distribution"
        distribution.rename(target)
        distribution.symlink_to(target, target_is_directory=True)
    elif case == "invalid_marker":
        (build / ".gitignore").write_bytes(b"*\nunsafe")
    elif case in {"symlink_marker", "dangling_symlink_marker"}:
        target = tmp_path / "marker"
        if case == "symlink_marker":
            target.write_bytes(b"*")
        (build / ".gitignore").symlink_to(target)
    elif case == "directory_marker":
        (build / ".gitignore").mkdir()
    else:
        pytest.fail(f"未实现的反例：{case}")
    _assert_rejected(_execute(job_name, distribution), error)


@pytest.mark.parametrize("job_name", ["quality", "publish"])
@pytest.mark.parametrize("case", ["missing_distribution", "missing_build"])
def test_missing_directories_are_rejected(job_name: str, case: str, tmp_path: Path) -> None:
    distribution = tmp_path / "distribution"
    if case == "missing_build":
        distribution.mkdir()
        (distribution / "manifest.json").write_text("{}", encoding="utf-8")
    error = "directory is missing or invalid"
    if case == "missing_build" and job_name == "publish":
        error = "Invalid distribution layout"
    _assert_rejected(_execute(job_name, distribution), error)


@pytest.mark.parametrize("job_name", ["quality", "publish"])
@pytest.mark.parametrize("sha", ["", "A" * 40, "e" * 39, "e" * 41, "g" * 40, "e" * 40 + "\n"])
def test_workflow_sha_must_be_full_lowercase_hex(job_name: str, sha: str, tmp_path: Path) -> None:
    distribution = _fixture_distribution(tmp_path)
    _assert_rejected(_execute(job_name, distribution, sha), "Invalid workflow SHA")


@pytest.mark.parametrize("case", ["existing", "symlink", "dangling_symlink"])
def test_generator_never_overwrites_existing_manifest(case: str, tmp_path: Path) -> None:
    distribution = _fixture_distribution(tmp_path)
    manifest_path = distribution / "manifest.json"
    before = manifest_path.read_bytes()
    target = tmp_path / "target.json"
    if case != "existing":
        manifest_path.rename(target)
        if case == "dangling_symlink":
            target.unlink()
        manifest_path.symlink_to(target)
    _assert_rejected(_execute("quality", distribution), "FileExistsError")
    if case == "existing":
        assert manifest_path.read_bytes() == before
    elif case == "symlink":
        assert target.read_bytes() == before
    else:
        assert not target.exists()


MANIFEST_CASES = [
    ("missing_manifest", "Invalid distribution layout"),
    ("symlink_manifest", "manifest must be a regular file"),
    ("dangling_symlink_manifest", "manifest must be a regular file"),
    ("directory_manifest", "manifest must be a regular file"),
    ("invalid_json", "Invalid manifest JSON"),
    ("invalid_utf8", "Invalid manifest JSON"),
    ("oversized_manifest", "Invalid manifest size"),
    ("array_manifest", "Invalid manifest schema"),
    ("null_manifest", "Invalid manifest schema"),
    ("extra_field", "Invalid manifest schema"),
    ("missing_files_field", "Invalid manifest schema"),
    ("missing_sha_field", "Invalid manifest schema"),
    ("wrong_sha", "workflow SHA mismatch"),
    ("nonstring_sha", "workflow SHA mismatch"),
    ("wrong_version", "version mismatch"),
    ("nonstring_version", "version mismatch"),
    ("wrong_project", "project name mismatch"),
    ("nonstring_project", "project name mismatch"),
    ("array_files", "name exactly the two fixed files"),
    ("null_files", "name exactly the two fixed files"),
    ("missing_filename", "name exactly the two fixed files"),
    ("extra_filename", "name exactly the two fixed files"),
    ("wrong_filename", "name exactly the two fixed files"),
    ("wrong_filename_and_build", "name exactly the two fixed files"),
    ("traversal_filename", "name exactly the two fixed files"),
    ("uppercase_digest", "Invalid manifest SHA256"),
    ("short_digest", "Invalid manifest SHA256"),
    ("long_digest", "Invalid manifest SHA256"),
    ("nonhex_digest", "Invalid manifest SHA256"),
    ("newline_digest", "Invalid manifest SHA256"),
    ("nonstring_digest", "Invalid manifest SHA256"),
    ("tampered_digest", "SHA256 mismatch"),
    ("tampered_bytes", "SHA256 mismatch"),
    ("valid_marker_tampered", "SHA256 mismatch"),
    ("duplicate_filename", "Duplicate manifest key"),
    ("duplicate_top_key", "Duplicate manifest key"),
    ("extra_root_file", "Invalid distribution layout"),
    ("symlink_summary", "Smoke summary must be a regular file"),
    ("directory_summary", "Smoke summary must be a regular file"),
]


@pytest.mark.parametrize(("case", "error"), MANIFEST_CASES)
def test_manifest_verification_fails_closed(case: str, error: str, tmp_path: Path) -> None:
    distribution = _fixture_distribution(tmp_path)
    build = distribution / "build"
    manifest_path = distribution / "manifest.json"
    manifest = _manifest(distribution)
    files = manifest["files"]
    if case == "extra_field":
        manifest["source_url"] = "https://invalid.example/"
    elif case == "missing_files_field":
        del manifest["files"]
    elif case == "missing_sha_field":
        del manifest["github_sha"]
    elif case == "wrong_sha":
        manifest["github_sha"] = "a" * 40
    elif case == "nonstring_sha":
        manifest["github_sha"] = 123
    elif case == "wrong_version":
        manifest["version"] = "0.2.0"
    elif case == "nonstring_version":
        manifest["version"] = 0.1
    elif case == "wrong_project":
        manifest["project_name"] = "other-project"
    elif case == "nonstring_project":
        manifest["project_name"] = [PROJECT_NAME]
    elif case == "array_files":
        manifest["files"] = list(files)
    elif case == "null_files":
        manifest["files"] = None
    elif case == "missing_filename":
        del files[WHEEL]
    elif case == "extra_filename":
        files["extra.whl"] = "f" * 64
    elif case in {"wrong_filename", "wrong_filename_and_build", "traversal_filename"}:
        name = (
            "../outside.whl"
            if case == "traversal_filename"
            else "other_project-0.1.0-py3-none-any.whl"
        )
        files[name] = files.pop(WHEEL)
        if case == "wrong_filename_and_build":
            (build / WHEEL).rename(build / name)
    elif case == "uppercase_digest":
        files[WHEEL] = "A" * 64
    elif case == "short_digest":
        files[WHEEL] = "a" * 63
    elif case == "long_digest":
        files[WHEEL] = "a" * 65
    elif case == "nonhex_digest":
        files[WHEEL] = "g" * 64
    elif case == "newline_digest":
        files[WHEEL] += "\n"
    elif case == "nonstring_digest":
        files[WHEEL] = 123
    elif case == "tampered_digest":
        files[WHEEL] = "f" * 64
    elif case in {"tampered_bytes", "valid_marker_tampered"}:
        (build / WHEEL).write_bytes(b"modified after manifest generation")
        if case == "valid_marker_tampered":
            (build / ".gitignore").write_bytes(b"*")
    elif case == "extra_root_file":
        (distribution / "unexpected.py").write_text("raise RuntimeError", encoding="utf-8")
    elif case == "symlink_summary":
        (distribution / "wheel-smoke-summary.json").symlink_to(manifest_path)
    elif case == "directory_summary":
        (distribution / "wheel-smoke-summary.json").mkdir()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    if case == "missing_manifest":
        manifest_path.unlink()
    elif case in {"symlink_manifest", "dangling_symlink_manifest"}:
        target = tmp_path / "target.json"
        manifest_path.rename(target)
        if case == "dangling_symlink_manifest":
            target.unlink()
        manifest_path.symlink_to(target)
    elif case == "directory_manifest":
        manifest_path.unlink()
        manifest_path.mkdir()
    elif case == "invalid_json":
        manifest_path.write_text("{broken", encoding="utf-8")
    elif case == "invalid_utf8":
        manifest_path.write_bytes(b"\xff")
    elif case == "oversized_manifest":
        manifest_path.write_text(" " * 4097, encoding="utf-8")
    elif case == "array_manifest":
        manifest_path.write_text("[]", encoding="utf-8")
    elif case == "null_manifest":
        manifest_path.write_text("null", encoding="utf-8")
    elif case == "duplicate_filename":
        # 重复的合法名称/摘要也必须拒绝，不能被 json.loads 的后值覆盖语义吞掉。
        raw = json.dumps(manifest)
        member = json.dumps(WHEEL) + ": " + json.dumps(files[WHEEL])
        manifest_path.write_text(raw.replace(member, member + ", " + member), encoding="utf-8")
    elif case == "duplicate_top_key":
        raw = json.dumps(manifest)
        member = '"github_sha": ' + json.dumps(TEST_SHA)
        manifest_path.write_text(raw.replace(member, member + ", " + member), encoding="utf-8")
    _assert_rejected(_execute("publish", distribution), error)


@pytest.mark.parametrize(
    ("job_name", "step_name", "directory"),
    [
        ("quality", "Check release metadata strictly", "$RUNNER_TEMP/distribution/build"),
        ("publish", "Recheck release metadata strictly", "verified-distribution/build"),
    ],
)
def test_twine_strict_checks_only_the_two_explicit_files(
    job_name: str, step_name: str, directory: str
) -> None:
    run = _run(_steps(_jobs()[job_name])[step_name])
    assert run == (
        "uvx --python 3.11 --from twine==7.0.0 twine check --strict \\\n"
        f'  "{directory}/{WHEEL}" \\\n'
        f'  "{directory}/{SDIST}"'
    )


def test_secret_is_scoped_to_upload_and_upload_is_exactly_two_explicit_files() -> None:
    upload = _steps(_jobs()["publish"])["Upload to PyPI"]
    assert "        shell: bash" in upload
    assert "        env:\n          UV_PUBLISH_TOKEN: ${{ secrets.PYPI_API_TOKEN }}" in upload
    assert "          NO_COLOR: '1'\n          TERM: dumb" in upload
    without_upload = WORKFLOW.replace(upload.strip(), "")
    assert "secrets." not in without_upload
    assert "UV_PUBLISH_TOKEN" not in without_upload
    assert WORKFLOW.count("secrets.") == 1
    assert "env:" not in _header(_jobs()["publish"])
    assert (
        _run(upload)
        == dedent(
            """\
        set -euo pipefail
        if [ -z "${UV_PUBLISH_TOKEN:-}" ]; then
          printf '%s\\n' 'PYPI_API_TOKEN 未配置；拒绝上传。' >&2
          exit 1
        fi
        uv publish --trusted-publishing never --check-url https://pypi.org/simple/ --no-progress \\
          "verified-distribution/build/knowledge_ykforward-0.1.0-py3-none-any.whl" \\
          "verified-distribution/build/knowledge_ykforward-0.1.0.tar.gz"
        """
        ).strip()
    )


def test_no_privilege_escalation_or_repository_side_effect_commands() -> None:
    for prohibited in (
        "id-token:",
        "write-all",
        "contents: write",
        "packages: write",
        "pages:",
        "actions/deploy-pages",
        "gh release",
        "gh pr",
        "git tag",
        "git push",
        "git commit",
        "git merge",
        "twine upload",
        "--publish-url",
        "--token",
        "--skip-existing",
        "--dry-run",
        "--verbose",
        "--debug",
        "set -x",
        "set -v",
        "printenv",
        "GITHUB_ENV",
        "GITHUB_OUTPUT",
        "continue-on-error",
    ):
        assert prohibited not in WORKFLOW
    assert not re.search(r"^\s*(environment|env|defaults):", WORKFLOW.split("\njobs:\n", 1)[0])
    assert not re.search(r"^\s*(?:[\w-]+:\s*)?[&*][\w-]+", WORKFLOW, re.MULTILINE)
    assert "<<:" not in WORKFLOW
