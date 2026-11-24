"""Safety validation for mutation demo manifests and local database scope."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from knowledge.mutations.models import (
    MAX_REQUEST_BYTES,
    MutationError,
    MutationManifest,
    MutationScope,
)


def _safe_json_load(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise MutationError(
            "invalid_manifest", "mutation manifest is invalid", status_code=503
        ) from exc
    if len(raw) > MAX_REQUEST_BYTES:
        raise MutationError("invalid_manifest", "mutation manifest is invalid", status_code=503)

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def constant(value: str) -> None:
        raise ValueError(value)

    try:
        loaded = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise MutationError(
            "invalid_manifest", "mutation manifest is invalid", status_code=503
        ) from exc
    if not isinstance(loaded, dict):
        raise MutationError("invalid_manifest", "mutation manifest is invalid", status_code=503)
    return loaded


def _no_symlink_components(path: Path) -> Path:
    # Check lexical ancestors BEFORE resolve(), including ancestors of the
    # manifest directory and nested database paths inside that directory.
    absolute = path.expanduser().absolute()
    for component in (absolute, *absolute.parents):
        if component.is_symlink():
            raise OSError("symlink component")
    return absolute.resolve(strict=True)


def _private_owned(path: Path, *, directory: bool = False) -> None:
    info = path.stat()
    valid_kind = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (
        not valid_kind
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
        or (not directory and info.st_nlink != 1)
    ):
        raise OSError("scope must be private and owned")


def load_mutation_scope(manifest_path: Path, database_path: Path) -> MutationScope:
    """Load and validate an opt-in local mutation manifest without leaking paths."""

    try:
        manifest_real = _no_symlink_components(manifest_path)
        _private_owned(manifest_real)
        parent = manifest_real.parent
        _private_owned(parent, directory=True)
        data = _safe_json_load(manifest_real)
        manifest = MutationManifest.model_validate(data)
        manifest_db = _no_symlink_components(parent / manifest.database)
        requested_db = _no_symlink_components(database_path)
        if manifest_db != requested_db:
            raise OSError
        manifest_db.relative_to(parent)
        _private_owned(manifest_db)
        for directory in manifest_db.parents:
            _private_owned(directory, directory=True)
            if directory == parent:
                break
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        if isinstance(exc, MutationError):
            raise
        raise MutationError(
            "invalid_manifest", "mutation manifest is invalid", status_code=503
        ) from exc
    return MutationScope(
        scope_id=manifest.scope_id,
        database_path=manifest_db,
        allowed_source_ids=manifest.allowed_source_ids,
    )


__all__ = ["load_mutation_scope"]
