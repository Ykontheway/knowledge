from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.export_mutation_schema import (
    DEFAULT_OUTPUT,
    MODEL_SOURCES,
    build_mutation_schema,
    dump_mutation_schema,
)


def test_mutation_schema_matches_actual_models() -> None:
    definitions = build_mutation_schema()["$defs"]
    for model, mode in MODEL_SOURCES:
        actual = model.model_json_schema(mode=mode)
        nested = actual.pop("$defs", {})
        assert definitions[model.__name__] == actual
        for name, fragment in nested.items():
            assert definitions[name] == fragment


def test_mutation_schema_matches_file() -> None:
    assert DEFAULT_OUTPUT.read_text(encoding="utf-8") == dump_mutation_schema()


def test_mutation_schema_check_cli() -> None:
    process = subprocess.run(
        [sys.executable, "scripts/export_mutation_schema.py", "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr


def test_mutation_schema_independent_whitelist() -> None:
    schema = build_mutation_schema()
    assert schema["additionalProperties"] is False
    for fragment in schema["$defs"].values():
        if fragment.get("type") == "object":
            assert fragment["additionalProperties"] is False
            assert {"href", "authorization", "credential", "metadata", "locator"}.isdisjoint(
                fragment["properties"]
            )
    assert "MutationManifest" not in schema["$defs"]
    assert "JobDTO" not in schema["$defs"]
    assert "ConfirmationToken" not in schema["$defs"]


def test_check_detects_drift_without_overwriting(tmp_path: Path) -> None:
    output = tmp_path / "schema.json"
    output.write_text("{}\n", encoding="utf-8")
    process = subprocess.run(
        [sys.executable, "scripts/export_mutation_schema.py", "--check", "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 1
    assert output.read_text(encoding="utf-8") == "{}\n"
