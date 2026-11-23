from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import create_model
from scripts import export_mutation_schema
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
    assert DEFAULT_OUTPUT.read_bytes() == dump_mutation_schema().encode("utf-8")


def test_mutation_schema_check_cli() -> None:
    process = subprocess.run(
        [sys.executable, "scripts/export_mutation_schema.py", "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout == "Mutation schema is up to date.\n"
    assert process.stderr == ""


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


@pytest.mark.parametrize(
    "invocation",
    [("scripts/export_mutation_schema.py",), ("-m", "scripts.export_mutation_schema")],
    ids=["direct-script", "package-module"],
)
def test_mutation_cli_output_and_read_only_checks(
    tmp_path: Path, invocation: tuple[str, ...]
) -> None:
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "new directory" / "schema.json"
    relative_output = os.path.relpath(output, root)
    command = [sys.executable, *invocation, "--output", relative_output]
    failure_message = (
        "Mutation schema is out of date; run python scripts/export_mutation_schema.py\n"
    )

    missing = subprocess.run(
        [*command, "--check"], cwd=root, capture_output=True, text=True, check=False
    )
    assert missing.returncode == 1
    assert missing.stdout == ""
    assert missing.stderr == failure_message
    assert not output.exists()
    assert not output.parent.exists()

    written = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    assert written.returncode == 0
    assert written.stdout == f"Wrote {relative_output}\n"
    assert written.stderr == ""
    assert output.read_bytes() == dump_mutation_schema().encode("utf-8")

    matching = subprocess.run(
        [*command, "--check"], cwd=root, capture_output=True, text=True, check=False
    )
    assert matching.returncode == 0
    assert matching.stdout == "Mutation schema is up to date.\n"
    assert matching.stderr == ""

    original = b"{}\n"
    output.write_bytes(original)
    mismatching = subprocess.run(
        [*command, "--check"], cwd=root, capture_output=True, text=True, check=False
    )
    assert mismatching.returncode == 1
    assert mismatching.stdout == ""
    assert mismatching.stderr == failure_message
    assert output.read_bytes() == original


def test_mutation_sources_preserve_whitelist_modes_and_order() -> None:
    assert tuple((model.__name__, mode) for model, mode in MODEL_SOURCES) == (
        ("SessionDTO", "serialization"),
        ("DocumentDTO", "serialization"),
        ("PreviewRequest", "validation"),
        ("PreviewDTO", "serialization"),
        ("CommandRequest", "validation"),
        ("CommandDTO", "serialization"),
    )
    definitions = build_mutation_schema()["$defs"]
    assert list(definitions) == sorted(definitions)


@pytest.mark.parametrize("nested", [False, True], ids=["root", "nested-definition"])
def test_mutation_schema_preserves_conflict_messages(
    monkeypatch: pytest.MonkeyPatch, nested: bool
) -> None:
    first = create_model("Example", value=(str, ...))
    second = create_model("Example", value=(int, ...))
    if nested:
        first = create_model("First", child=(first, ...))
        second = create_model("Second", child=(second, ...))
    monkeypatch.setattr(
        export_mutation_schema,
        "MODEL_SOURCES",
        ((first, "validation"), (second, "validation")),
    )
    with pytest.raises(ValueError) as error:
        build_mutation_schema()
    assert str(error.value) == "conflicting schema definition: Example"
