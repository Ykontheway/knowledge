"""固定布局的发布工作流文本契约，不依赖 YAML 库，也不宣称解析任意 YAML。

只识别本工作流约定的顶层、job 和具名 step 缩进；变更门禁或布局必须显式更新契约。
内联摘要检查另用隔离 Python 执行反例，不能靠存在某段文字推断校验会失败。
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "3768ceba0719cd21916ea80ae175151a92d4ded1"
REPOSITORY = "Ykontheway/konwledge"
BRANCH = "aime/1793676007-v02-demo-web"
EXPECTED_DIGESTS = {
    "konwledge-0.1.0-py3-none-any.whl": (
        "801e74af65419db1877d16c87cd2a53c5f67fcae4927fbba59c19a58ed950f17"
    ),
    "konwledge-0.1.0.tar.gz": ("2e9dd69ff48582f1117befc33328ef38324a185f3a3008bc263e9ed8e08f46ee"),
}


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


def _digest_script(job_name: str) -> str:
    step_name = (
        "Verify exact release digests"
        if job_name == "quality"
        else "Reverify exact release digests"
    )
    run = _run(_steps(_jobs()[job_name])[step_name])
    prefix, script = run.split("<<'PY'\n", 1)
    assert prefix.startswith("set -euo pipefail\npython3 -I - ")
    assert script.endswith("\nPY")
    return script.removesuffix("\nPY")


def test_only_feature_push_or_opt_in_dispatch_with_minimal_permissions() -> None:
    top = _blocks(WORKFLOW.split("\njobs:\n", 1)[0], r"^([a-z]+):.*$")
    assert set(top) == {"name", "on", "permissions", "concurrency"}
    assert (
        top["on"].strip()
        == dedent(
            f"""\
        on:
          push:
            branches: ['{BRANCH}']
            paths: ['.github/workflows/publish-pypi.yml']
          workflow_dispatch:
            inputs:
              publish:
                description: '通过所有门禁后上传固定的 0.1.0 产物到 PyPI'
                type: boolean
                default: false
        """
        ).strip()
    )
    assert top["permissions"].strip() == "permissions:\n  contents: read"
    assert WORKFLOW.count("permissions:") == 1
    assert top["concurrency"].strip() == (
        "concurrency:\n  group: release-0.1.0\n  cancel-in-progress: false"
    )
    assert set(_jobs()) == {"quality", "postgres", "web", "lancedb", "publish"}
    assert "github.sha" not in WORKFLOW
    assert "refs/heads/main" not in WORKFLOW
    assert not re.search(r"\b(source_sha|upload_url|package_version)\b", WORKFLOW)


@pytest.mark.parametrize("job_name", ["quality", "postgres", "web", "lancedb"])
def test_check_jobs_reuse_all_ci_steps_and_configuration(job_name: str) -> None:
    job = _jobs()[job_name]
    source_job = _jobs(CI)[job_name]
    header = re.sub(r"^    (if|timeout-minutes):.*(?:\n|$)", "", _header(job), flags=re.MULTILINE)
    assert header.strip() == _header(source_job).strip()
    assert f"    if: github.repository == '{REPOSITORY}'" in _header(job)
    steps = _steps(job)
    source_steps = _steps(source_job)
    extra_steps = (
        {"Verify exact release digests", "Check release metadata strictly"}
        if job_name == "quality"
        else set()
    )
    assert set(steps) == set(source_steps) | extra_steps
    assert [name for name in steps if name not in extra_steps] == list(source_steps)
    for name, source_step in source_steps.items():
        if name == "Check out repository":
            continue  # 固定 checkout 的独立契约见下。
        step = steps[name]
        if name == "Install uv":
            step = re.sub(r'^          version: "0\.12\.15"\n', "", step, flags=re.MULTILINE)
        assert step.strip() == source_step.strip(), f"未完整复用 CI step: {name}"


def _norm(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


@pytest.mark.parametrize("job_name", ["quality", "postgres", "web", "lancedb"])
def test_every_checkout_is_the_fixed_repository_and_release_sha(job_name: str) -> None:
    steps = _steps(_jobs()[job_name])
    checkout = steps["Check out repository"]
    expected = dedent(
        f"""\
          - name: Check out repository
            uses: actions/checkout@v4
            with:
              repository: {REPOSITORY}
              ref: {SOURCE_SHA}
              persist-credentials: false
        """
    )
    assert _norm(checkout) == _norm(expected)
    assert len(re.findall(r"uses: actions/checkout@", _jobs()[job_name])) == 1
    assert WORKFLOW.count(SOURCE_SHA) == 4
    assert WORKFLOW.count("uses: actions/checkout@") == 4


@pytest.mark.parametrize("job_name", ["quality", "postgres", "lancedb", "publish"])
def test_uv_is_pinned_and_timeouts_are_bounded(job_name: str) -> None:
    job = _jobs()[job_name]
    setup = _steps(job)["Install uv"]
    assert 'uses: astral-sh/setup-uv@v6\n        with:\n          version: "0.12.15"' in setup
    assert WORKFLOW.count("uses: astral-sh/setup-uv@") == 4
    for candidate in _jobs().values():
        timeout = re.findall(r"^    timeout-minutes: (\d+)$", candidate, re.MULTILINE)
        assert len(timeout) == 1 and 25 <= int(timeout[0]) <= 40


def test_quality_keeps_all_python_lanes_and_strict_checks_follow_smokes() -> None:
    quality = _jobs()["quality"]
    assert 'python-version: ["3.11", "3.12", "3.13"]' in _header(quality)
    assert "    env:\n      NO_COLOR: '1'\n      TERM: dumb" in _header(quality)
    steps = _steps(quality)
    smoke = "Verify wheel and source distribution (core-only, quality, api, postgres, and tokens)"
    names = list(steps)
    index = names.index(smoke)
    assert names[index + 1 : index + 3] == [
        "Verify exact release digests",
        "Check release metadata strictly",
    ]
    assert "if:" not in steps[smoke]
    for name in names[index + 1 : index + 3]:
        assert "        if: matrix.python-version == '3.11'" in steps[name]
    artifact = steps["Upload verified distributions and smoke summaries"]
    assert "name: distribution-${{ matrix.python-version }}" in artifact
    assert "${{ runner.temp }}/distribution/build/*.whl" in artifact
    assert "${{ runner.temp }}/distribution/build/*.tar.gz" in artifact
    assert "${{ runner.temp }}/distribution/*-smoke-summary.json" in artifact


def test_publish_gate_is_exact_opt_in_and_needs_every_successful_check() -> None:
    header = _header(_jobs()["publish"])
    assert "    needs: [quality, postgres, web, lancedb]" in header
    gate = header.split("    if: >-\n", 1)[1].split("\n    runs-on:", 1)[0]
    assert " ".join(gate.split()) == (
        f"${{{{ github.repository == '{REPOSITORY}' && "
        f"github.ref == 'refs/heads/{BRANCH}' && "
        "((github.event_name == 'workflow_dispatch' && inputs.publish == true) || "
        "(github.event_name == 'push' && "
        "contains(github.event.head_commit.message, '[publish-pypi-0.1.0]'))) }}"
    )
    # 没有 always()/失败旁路；GitHub 的隐式 success() 要求所有 needs 成功。
    assert not any(value in header for value in ("always()", "!cancelled()", "failure()"))
    assert "github.event.inputs.publish" not in header  # inputs 的 boolean 不可换成字符串。
    assert WORKFLOW.count("uv publish ") == 1
    assert "uv publish" not in WORKFLOW.split("\n  publish:\n", 1)[0]


def test_publish_downloads_same_run_and_never_checks_out_or_builds() -> None:
    publish = _jobs()["publish"]
    steps = _steps(publish)
    assert list(steps) == [
        "Install uv",
        "Download verified distributions",
        "Reverify exact release digests",
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
    assert 'python3 -I - "verified-distribution/build"' in publish


@pytest.mark.parametrize("job_name", ["quality", "publish"])
def test_digest_script_has_exactly_two_frozen_files_and_only_stdlib_imports(job_name: str) -> None:
    script = _digest_script(job_name)
    tree = ast.parse(script)
    expected_assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "expected" for target in node.targets)
    ]
    assert len(expected_assignments) == 1
    assert ast.literal_eval(expected_assignments[0].value) == EXPECTED_DIGESTS
    imports = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imports == {"hashlib", "sys", "pathlib"}
    assert not any(isinstance(node, (ast.Assert, ast.Try)) for node in ast.walk(tree))
    assert "hashlib.sha256(path.read_bytes()).hexdigest() != digest" in script
    assert _digest_script("quality") == _digest_script("publish")


@pytest.mark.parametrize("job_name", ["quality", "publish"])
@pytest.mark.parametrize(
    ("case", "error"),
    [
        ("missing_build", "directory is missing or invalid"),
        ("missing_file", "exactly the two fixed files"),
        ("extra_file", "exactly the two fixed files"),
        ("wrong_version", "exactly the two fixed files"),
        ("nested_directory", "exactly the two fixed files"),
        ("directory_as_wheel", "must be a regular file"),
        ("symlink_as_wheel", "must be a regular file"),
        ("symlink_build", "directory is missing or invalid"),
        ("invalid_marker", "Invalid build-directory marker"),
        ("symlink_marker", "Invalid build-directory marker"),
        ("directory_marker", "Invalid build-directory marker"),
        ("valid_marker_tampered", "SHA256 mismatch"),
        ("tampered", "SHA256 mismatch"),
    ],
)
def test_digest_verification_fails_closed(
    job_name: str, case: str, error: str, tmp_path: Path
) -> None:
    # 不改摘要、不构建包、不调用上传；使用故意无效的小文件测试实际拒绝路径。
    build = tmp_path / "build"
    if case != "missing_build":
        build.mkdir()
        for name in EXPECTED_DIGESTS:
            (build / name).write_bytes(b"not the verified release")
        wheel = build / "konwledge-0.1.0-py3-none-any.whl"
        if case == "invalid_marker":
            (build / ".gitignore").write_bytes(b"unexpected content")
        elif case == "symlink_marker":
            target = tmp_path / "marker"
            target.write_bytes(b"*")
            (build / ".gitignore").symlink_to(target)
        elif case == "directory_marker":
            (build / ".gitignore").mkdir()
        elif case == "valid_marker_tampered":
            (build / ".gitignore").write_bytes(b"*")
        elif case == "missing_file":
            wheel.unlink()
        elif case == "extra_file":
            (build / "unexpected.whl").write_bytes(b"extra")
        elif case == "wrong_version":
            wheel.rename(build / "konwledge-0.2.0-py3-none-any.whl")
        elif case == "nested_directory":
            (build / "unexpected").mkdir()
        elif case == "directory_as_wheel":
            wheel.unlink()
            wheel.mkdir()
        elif case == "symlink_as_wheel":
            target = tmp_path / "target.whl"
            wheel.rename(target)
            wheel.symlink_to(target)
        elif case == "symlink_build":
            target = tmp_path / "real-build"
            build.rename(target)
            build.symlink_to(target, target_is_directory=True)
    result = subprocess.run(
        [sys.executable, "-I", "-", str(build)],
        input=_digest_script(job_name),
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert error in result.stderr
    assert result.stdout == ""


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
        f'  "{directory}/konwledge-0.1.0-py3-none-any.whl" \\\n'
        f'  "{directory}/konwledge-0.1.0.tar.gz"'
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
          "verified-distribution/build/konwledge-0.1.0-py3-none-any.whl" \\
          "verified-distribution/build/konwledge-0.1.0.tar.gz"
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
