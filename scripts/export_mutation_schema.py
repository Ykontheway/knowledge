#!/usr/bin/env python3
"""Export independent mutation schemas from the actual Backend A Pydantic models."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

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
            if name in definitions and definitions[name] != fragment:
                raise ValueError(f"conflicting schema definition: {name}")
            definitions[name] = fragment
        name = model.__name__
        if name in definitions and definitions[name] != schema:
            raise ValueError(f"conflicting schema definition: {name}")
        definitions[name] = schema
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "MutationApiSchemaBundle",
        "type": "object",
        "additionalProperties": False,
        "properties": {},
        "$defs": {name: definitions[name] for name in sorted(definitions)},
    }


def dump_mutation_schema() -> str:
    return json.dumps(build_mutation_schema(), ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = dump_mutation_schema()
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if current != rendered:
            print(
                "Mutation schema is out of date; run python scripts/export_mutation_schema.py",
                file=sys.stderr,
            )
            return 1
        print("Mutation schema is up to date.")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
