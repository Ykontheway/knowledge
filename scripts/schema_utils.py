"""Shared formatting, definition checks and file handling for schema exporters."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def dump_json(value: Any) -> str:
    """Render UTF-8-friendly JSON with two-space indentation and a final newline."""
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def insert_definition_strict(
    definitions: dict[str, Any],
    name: str,
    fragment: dict[str, Any],
    *,
    conflict_message: str = "conflicting schema definition",
) -> None:
    """Allow identical named fragments, but reject conflicting ones before insertion."""
    if name in definitions and definitions[name] != fragment:
        raise ValueError(f"{conflict_message}: {name}")
    definitions[name] = fragment


def check_or_write(
    output: Path,
    rendered: str,
    *,
    check: bool,
    up_to_date_message: str,
    out_of_date_message: str,
) -> int:
    """Check without writing, or create the parent directory and write the schema.

    Paths and CLI-specific messages are supplied by the caller without normalization.
    """
    if check:
        current = output.read_text(encoding="utf-8") if output.exists() else ""
        if current != rendered:
            print(out_of_date_message, file=sys.stderr)
            return 1
        print(up_to_date_message)
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(f"Wrote {output}")
    return 0
