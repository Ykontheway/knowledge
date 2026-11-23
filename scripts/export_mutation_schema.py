#!/usr/bin/env python3
"""Export independent mutation schemas from the actual Backend A Pydantic models."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaMode

from konwledge.mutations.models import (
    CommandDTO,
    CommandRequest,
    DocumentDTO,
    PreviewDTO,
    PreviewRequest,
    SessionDTO,
)

if TYPE_CHECKING or __package__:
    from .schema_utils import check_or_write, dump_json, insert_definition_strict
else:
    from schema_utils import check_or_write, dump_json, insert_definition_strict

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "web/src/mutations/schema.json"
MODEL_SOURCES: tuple[tuple[type[BaseModel], JsonSchemaMode], ...] = (
    (SessionDTO, "serialization"),
    (DocumentDTO, "serialization"),
    (PreviewRequest, "validation"),
    (PreviewDTO, "serialization"),
    (CommandRequest, "validation"),
    (CommandDTO, "serialization"),
)


def build_mutation_schema() -> dict[str, Any]:
    definitions: dict[str, Any] = {}
    for model, mode in MODEL_SOURCES:
        schema = model.model_json_schema(mode=mode)
        for name, fragment in schema.pop("$defs", {}).items():
            insert_definition_strict(definitions, name, fragment)
        insert_definition_strict(definitions, model.__name__, schema)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "MutationApiSchemaBundle",
        "type": "object",
        "additionalProperties": False,
        "properties": {},
        "$defs": {name: definitions[name] for name in sorted(definitions)},
    }


def dump_mutation_schema() -> str:
    return dump_json(build_mutation_schema())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = dump_mutation_schema()
    return check_or_write(
        args.output,
        rendered,
        check=args.check,
        up_to_date_message="Mutation schema is up to date.",
        out_of_date_message=(
            "Mutation schema is out of date; run python scripts/export_mutation_schema.py"
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
