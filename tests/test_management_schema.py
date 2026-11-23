from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from scripts import export_management_schema
from scripts.export_management_schema import (
    DEFAULT_OUTPUT,
    SCHEMA_ID,
    build_management_schema,
    dump_management_schema,
)

OUTPUT_DEF_NAMES = (
    "JobDTO",
    "RevisionDTO",
    "UnitDTO",
    "LineageDTO",
    "DocumentDTO",
    "DocumentDiffDTO",
    "EvidenceDTO",
    "ListJobsResponse",
    "GetJobResponse",
    "GetRevisionResponse",
    "GetDocumentResponse",
    "GetLineageResponse",
    "GetDocumentDiffResponse",
    "GetUnitResponse",
    "GetEvidenceResponse",
)
FORBIDDEN_OUTPUT_FIELDS = {"query", "locator", "metadata"}


def _iter_refs(
    schema: dict[str, object], definition: dict[str, object]
) -> Iterator[dict[str, object]]:
    stack: list[dict[str, object]] = [definition]
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        reference = current.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            name = reference.removeprefix("#/$defs/")
            if name not in seen:
                seen.add(name)
                definitions = schema["$defs"]
                assert isinstance(definitions, dict)
                target = definitions[name]
                assert isinstance(target, dict)
                stack.append(target)
            continue
        yield current
        for value in current.values():
            if isinstance(value, dict):
                stack.append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        stack.append(item)


def test_management_schema_matches_committed_file() -> None:
    assert DEFAULT_OUTPUT.read_bytes() == dump_management_schema().encode("utf-8")


def test_management_schema_check_cli_passes() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/export_management_schema.py", "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == f"Management schema is up to date: {DEFAULT_OUTPUT.resolve()}\n"
    assert completed.stderr == ""


def test_management_schema_omits_query_locator_and_metadata_from_outputs() -> None:
    schema = build_management_schema()
    for name in OUTPUT_DEF_NAMES:
        definition = schema["$defs"][name]
        assert isinstance(definition, dict)
        for node in _iter_refs(schema, definition):
            properties = node.get("properties")
            if isinstance(properties, dict):
                assert FORBIDDEN_OUTPUT_FIELDS.isdisjoint(properties)


def test_management_schema_bundle_contains_expected_roots() -> None:
    committed = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    for name in (
        "PageQuery",
        "JobsQuery",
        "DiffQuery",
        "JobDTO",
        "RevisionDTO",
        "DocumentDTO",
        "LineageDTO",
        "DocumentDiffDTO",
        "UnitDTO",
        "EvidenceDTO",
        "ListJobsResponse",
    ):
        assert name in committed["$defs"]


@pytest.mark.parametrize(
    "invocation",
    [("scripts/export_management_schema.py",), ("-m", "scripts.export_management_schema")],
    ids=["direct-script", "package-module"],
)
def test_management_cli_output_and_read_only_checks(
    tmp_path: Path, invocation: tuple[str, ...]
) -> None:
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "new directory" / "schema.json"
    relative_output = os.path.relpath(output, root)
    command = [sys.executable, *invocation, "--output", relative_output]
    failure_message = (
        f"{output.resolve()} is out of date; run `python scripts/export_management_schema.py`.\n"
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
    assert written.stdout == f"Wrote {output.resolve()}\n"
    assert written.stderr == ""
    assert output.read_bytes() == dump_management_schema().encode("utf-8")

    matching = subprocess.run(
        [*command, "--check"], cwd=root, capture_output=True, text=True, check=False
    )
    assert matching.returncode == 0
    assert matching.stdout == f"Management schema is up to date: {output.resolve()}\n"
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


def test_management_schema_preserves_bundle_metadata_refs_and_order() -> None:
    schema = build_management_schema()
    assert schema["$id"] == SCHEMA_ID
    assert schema["description"] == (
        "Read-only B1 management API queries and DTOs exported from Python models."
    )
    assert list(schema["$defs"]) == sorted(schema["$defs"])
    for name in ("Job", "Revision", "Document", "Lineage", "DocumentDiff", "Unit", "Evidence"):
        assert schema["$defs"][f"Get{name}Response"] == {"$ref": f"#/$defs/{name}DTO"}


@pytest.mark.parametrize("kind", ["definition", "fragment"])
def test_management_schema_preserves_conflict_messages(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    sources: tuple[tuple[str, dict[str, Any]], ...]
    if kind == "definition":
        sources = (
            ("First", {"$defs": {"Example": {"type": "string"}}}),
            ("Second", {"$defs": {"Example": {"type": "integer"}}}),
        )
    else:
        sources = (("Example", {"type": "string"}), ("Example", {"type": "integer"}))
    monkeypatch.setattr(export_management_schema, "_schema_sources", lambda: sources)
    with pytest.raises(ValueError) as error:
        build_management_schema()
    assert str(error.value) == f"conflicting schema {kind}: Example"
