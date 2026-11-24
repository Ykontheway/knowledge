from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from importlib import resources
from pathlib import Path
from typing import Any

from knowledge import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
LOCK_PATH = PROJECT_ROOT / "uv.lock"


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _run_python(script: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_release_metadata_is_coherent() -> None:
    pyproject = _load_toml(PYPROJECT_PATH)
    project = pyproject["project"]
    assert isinstance(project, dict)

    assert project["name"] == "knowledge-ykforward"
    assert project["version"] == __version__ == "0.1.0"
    assert project["requires-python"] == ">=3.11"
    assert "Development Status :: 3 - Alpha" in project["classifiers"]
    assert project["scripts"] == {
        "knowledge": "knowledge.cli:main",
        "knowledge-mcp": "knowledge.mcp.server:main",
    }


def test_lock_contains_matching_editable_project_record() -> None:
    pyproject = _load_toml(PYPROJECT_PATH)
    lock = _load_toml(LOCK_PATH)
    project = pyproject["project"]
    assert isinstance(project, dict)

    editable_projects = [
        package
        for package in lock["package"]
        if package["name"] == project["name"] and package.get("source") == {"editable": "."}
    ]
    assert len(editable_projects) == 1
    assert editable_projects[0]["version"] == project["version"]
    assert lock["requires-python"] == project["requires-python"]


def test_packaged_demo_corpus_is_available_via_importlib_resources() -> None:
    corpus = resources.files("knowledge.demo").joinpath("corpus")
    expected = {
        "deployment-guide.v1.md",
        "deployment-guide.v2.md",
        "deployment-guide.v3.md",
        "oncall-faq.v1.md",
    }

    assert {item.name for item in corpus.iterdir() if item.is_file()} == expected
    assert all(corpus.joinpath(name).read_text(encoding="utf-8").strip() for name in expected)


def test_root_public_api_is_lazy_and_matches_application_facade(tmp_path: Path) -> None:
    script = """
import sys
import knowledge

assert knowledge.__all__ == ["KnowledgeLibrary", "__version__"]
assert {"KnowledgeLibrary", "__version__"} <= set(dir(knowledge))
assert "knowledge.application" not in sys.modules
implementation = knowledge.KnowledgeLibrary
from knowledge.application import KnowledgeLibrary
assert implementation is KnowledgeLibrary
assert knowledge.KnowledgeLibrary is KnowledgeLibrary
try:
    knowledge.not_a_public_attribute
except AttributeError:
    pass
else:
    raise AssertionError("unknown root attributes must raise AttributeError")
"""

    result = _run_python(script, tmp_path)

    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_version_command_needs_no_optional_lancedb_or_database(tmp_path: Path) -> None:
    script = """
import sys
sys.modules["lancedb"] = None
from knowledge.cli import main
raise SystemExit(main(["--version"]))
"""

    result = _run_python(script, tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "knowledge 0.1.0"
    assert list(tmp_path.iterdir()) == []


def test_packaged_type_marker_is_present() -> None:
    assert resources.files("knowledge").joinpath("py.typed").is_file()


def test_api_extra_and_sdk_dependencies_remain_separate() -> None:
    pyproject = _load_toml(PYPROJECT_PATH)
    project = pyproject["project"]
    assert project["optional-dependencies"]["api"] == [
        "fastapi>=0.115,<1",
        "uvicorn>=0.30,<1",
    ]
    runtime = " ".join(project["dependencies"])
    assert all(
        name not in runtime for name in ("fastapi", "uvicorn", "httpx", "openai", "langchain")
    )
    dev = " ".join(pyproject["dependency-groups"]["dev"])
    assert all(
        name in dev for name in ("fastapi", "uvicorn", "httpx", "openai", "langchain-openai")
    )


def test_core_only_root_api_and_cli_imports_are_lazy(tmp_path: Path) -> None:
    script = """
import sys
for name in ("fastapi", "uvicorn", "openai", "langchain_openai", "httpx", "mcp"):
    sys.modules[name] = None
import knowledge
import knowledge.api
from knowledge.cli import main
assert "knowledge.api.server" not in sys.modules
assert main(["--version"]) == 0
assert main(["--help"]) == 0
assert main(["serve", "--help"]) == 0
assert main(["mcp", "--help"]) == 0
assert main(["mcp", "serve", "--help"]) == 0
assert "knowledge.mcp.server" not in sys.modules
assert "knowledge.api.server" not in sys.modules
"""
    result = _run_python(script, tmp_path)
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_core_only_serve_reports_missing_optional_dependency(tmp_path: Path) -> None:
    database = tmp_path / "existing.db"
    database.touch()
    script = """
import sys
sys.modules["fastapi"] = None
sys.modules["uvicorn"] = None
from knowledge.cli import main
raise SystemExit(main(["serve", "--database", "existing.db"]))
"""
    result = _run_python(script, tmp_path)

    assert result.returncode == 1
    assert "knowledge-ykforward[api]" in result.stderr
    assert "Traceback" not in result.stderr
    assert list(tmp_path.iterdir()) == [database]
    assert database.stat().st_size == 0


def test_mcp_optional_metadata_and_lock_keep_core_dependency_boundary() -> None:
    pyproject = _load_toml(PYPROJECT_PATH)
    project = pyproject["project"]
    assert project["optional-dependencies"]["mcp"] == ["mcp>=1.30.0,<2"]
    assert project["dependencies"] == [
        "click>=8.1,<9",
        "pydantic>=2.7,<3",
        "sqlalchemy>=2.0,<3",
        "typer>=0.12,<1",
    ]
    dev_mcp = [item for item in pyproject["dependency-groups"]["dev"] if item.startswith("mcp")]
    assert dev_mcp == project["optional-dependencies"]["mcp"] == ["mcp>=1.30.0,<2"]
    package = next(
        package
        for package in _load_toml(LOCK_PATH)["package"]
        if package["name"] == "knowledge-ykforward" and package.get("source") == {"editable": "."}
    )
    assert {item["name"] for item in package["dependencies"]} == {
        "click",
        "pydantic",
        "sqlalchemy",
        "typer",
    }
    assert package["optional-dependencies"]["mcp"] == [{"name": "mcp"}]
    requirements = [item for item in package["metadata"]["requires-dist"] if item["name"] == "mcp"]
    assert requirements == [{"name": "mcp", "marker": "extra == 'mcp'", "specifier": ">=1.30.0,<2"}]
    assert "mcp" in package["metadata"]["provides-extras"]
    assert {item["name"] for item in package["dev-dependencies"]["dev"]} >= {"mcp"}
    dev_requirements = [
        item for item in package["metadata"]["requires-dev"]["dev"] if item["name"] == "mcp"
    ]
    assert dev_requirements == [{"name": "mcp", "specifier": ">=1.30.0,<2"}]


def test_core_mcp_console_dependency_failure_is_safe_and_does_not_create_db(tmp_path: Path) -> None:
    script = """
import sys
sys.modules['mcp'] = None
from knowledge.mcp.server import main
raise SystemExit(main(['--database', 'missing.db']))
"""
    result = _run_python(script, tmp_path)
    assert result.returncode == 1 and result.stdout == ""
    assert "pip install 'knowledge-ykforward[mcp]'" in result.stderr
    assert "Traceback" not in result.stderr and str(tmp_path) not in result.stderr
    assert list(tmp_path.iterdir()) == []
