from __future__ import annotations

from pathlib import Path

import pytest
from scripts.verify_distribution import (
    REPLAY_MODULES,
    REPLAY_SDIST_FILES,
    inspect_sdist,
    inspect_wheel,
)

from test_distribution import NAME, SDIST_ROOT, VERSION, write_sdist, write_wheel


@pytest.mark.parametrize("module", REPLAY_MODULES)
def test_wheel_requires_replay_module(tmp_path: Path, module: str) -> None:
    artifact = tmp_path / "test.whl"
    write_wheel(artifact, omit=(module,))
    with pytest.raises(ValueError, match="wheel is missing packaged file"):
        inspect_wheel(artifact, NAME, VERSION, ())


@pytest.mark.parametrize("filename", REPLAY_SDIST_FILES)
def test_sdist_requires_replay_python_tools_and_tests(tmp_path: Path, filename: str) -> None:
    artifact = tmp_path / "test.tar.gz"
    write_sdist(artifact, omit=(f"{SDIST_ROOT}/{filename}",))
    with pytest.raises(ValueError, match="sdist is missing source file"):
        inspect_sdist(artifact, NAME, VERSION)


@pytest.mark.parametrize("module", REPLAY_MODULES)
def test_sdist_requires_replay_module(tmp_path: Path, module: str) -> None:
    artifact = tmp_path / "test.tar.gz"
    write_sdist(artifact, omit=(f"{SDIST_ROOT}/src/{module}",))
    with pytest.raises(ValueError, match="sdist is missing source file"):
        inspect_sdist(artifact, NAME, VERSION)
