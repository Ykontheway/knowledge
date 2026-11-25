"""项目命名契约；无需构建产物、可选 SDK 或系统服务。"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_NAMESPACE = "kon" + "wledge"


@pytest.fixture
def project_config() -> dict[str, Any]:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
        return tomllib.load(stream)


def test_distribution_name_and_version(project_config: dict[str, Any]) -> None:
    project = project_config["project"]
    assert project["name"] == "knowledge-ykforward"
    assert project["version"] == "0.1.0"


def test_import_namespace_and_version_need_no_site_dependencies(tmp_path: Path) -> None:
    source = PROJECT_ROOT / "src"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    script = f"""
import importlib.util
from pathlib import Path
import sys
import knowledge

assert knowledge.__name__ == 'knowledge'
assert knowledge.__version__ == '0.1.0'
assert Path(knowledge.__file__).resolve() == Path({str(source / "knowledge/__init__.py")!r})
assert importlib.util.find_spec({LEGACY_NAMESPACE!r}) is None
assert not any(name.split('.')[0] == {LEGACY_NAMESPACE!r} for name in sys.modules)
assert 'knowledge.application' not in sys.modules
assert not any(name.split('.')[0] in {{'mcp', 'fastapi', 'lancedb', 'psycopg', 'tiktoken'}}
               for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-S", "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert list(tmp_path.iterdir()) == []


def test_console_entries_are_exactly_two(project_config: dict[str, Any]) -> None:
    assert project_config["project"]["scripts"] == {
        "knowledge": "knowledge.cli:main",
        "knowledge-mcp": "knowledge.mcp.server:main",
    }


def test_package_urls_point_to_renamed_repository(project_config: dict[str, Any]) -> None:
    assert project_config["project"]["urls"] == {
        "Repository": "https://github.com/Ykontheway/knowledge",
        "Issues": "https://github.com/Ykontheway/knowledge/issues",
    }


def test_wheel_selects_only_new_namespace(project_config: dict[str, Any]) -> None:
    assert project_config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/knowledge"
    ]
    source = PROJECT_ROOT / "src"
    assert (source / "knowledge" / "__init__.py").is_file()
    assert (source / "knowledge" / "py.typed").is_file()
    assert not (source / LEGACY_NAMESPACE).exists()
