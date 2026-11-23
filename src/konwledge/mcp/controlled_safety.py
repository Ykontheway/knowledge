"""B4 prepare 格式的固定 root 验证；wheel 不依赖 scripts。

同 OS owner 可修改终端、文件及 SQLite，非生产身份认证边界。
预检全程 mode=ro；路径身份在连接创建及每次操作前重新检查。
"""

from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from konwledge.mutations.models import MutationScope
from konwledge.mutations.safety import _safe_json_load, load_mutation_scope


class ScopeSafetyError(ValueError):
    def __init__(self) -> None:
        super().__init__("mcp_mutation_scope_invalid")


def no_symlinks(path: Path) -> Path:
    candidate = path.expanduser().absolute()
    if ".." in candidate.parts:
        raise ScopeSafetyError
    for part in (candidate, *candidate.parents):
        if part.is_symlink():
            raise ScopeSafetyError
    return candidate


def private_owned(path: Path, *, directory: bool = False) -> None:
    info = no_symlinks(path).lstat()
    valid_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (
        not valid_type
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
        or (not directory and info.st_nlink != 1)
    ):
        raise ScopeSafetyError


def validate_scope(database: Path, manifest: Path, root: Path) -> MutationScope:
    try:
        database, manifest, root = map(no_symlinks, (database, manifest, root))
        parent = manifest.parent
        if (
            manifest.name != "mutation-manifest.json"
            or parent.parent != root
            or str(UUID(parent.name)) != parent.name
            or database.name != "knowledge.db"
            or database.parent.parent != parent
        ):
            raise ScopeSafetyError
        private_owned(root, directory=True)
        private_owned(parent, directory=True)
        # B4 prepare 私有化整个 scope，包含 report、seed 和批准文件。
        for directory, dirs, files in os.walk(parent, followlinks=False):
            for name in dirs:
                private_owned(Path(directory) / name, directory=True)
            for name in files:
                private_owned(Path(directory) / name)
        scope = load_mutation_scope(manifest, database)
        if str(scope.scope_id) != parent.name:
            raise ScopeSafetyError
        report = database.parent / "report.json"
        private_owned(report)
        payload = _safe_json_load(report)
        artifacts = payload.get("artifacts")
        if (
            payload.get("status") != "passed"
            or not isinstance(artifacts, dict)
            or artifacts.get("database") != "knowledge.db"
        ):
            raise ScopeSafetyError
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            if connection.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise ScopeSafetyError
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not {
                "mutation_previews",
                "mutation_commands",
                "auto_evaluation_jobs",
                "knowledge_units_fts",
            }.issubset(tables):
                raise ScopeSafetyError
            config = connection.execute(
                "SELECT enabled, dataset_id, dataset_version, dataset_hash "
                "FROM auto_evaluation_config WHERE id=1"
            ).fetchone()
            if not config or config[0] != 1:
                raise ScopeSafetyError
            if not connection.execute(
                "SELECT 1 FROM evaluation_sets WHERE id=? AND version=? AND content_hash=?",
                config[1:],
            ).fetchone():
                raise ScopeSafetyError
            rows = connection.execute(
                "SELECT s.id,s.kind,d.content_type FROM sources s "
                "LEFT JOIN documents d ON d.source_id=s.id"
            ).fetchall()
            if not rows or any(
                kind != "file" or content not in {"text", "markdown"} for _, kind, content in rows
            ):
                raise ScopeSafetyError
            if {UUID(row[0]) for row in rows} != set(scope.allowed_source_ids):
                raise ScopeSafetyError
        finally:
            connection.close()
        return scope
    except Exception:
        raise ScopeSafetyError from None


@dataclass(frozen=True)
class ScopeGuard:
    database: Path
    manifest: Path
    root: Path
    scope: MutationScope
    identities: tuple[tuple[int, int], ...]

    @classmethod
    def prepare(cls, database: Path, manifest: Path, root: Path) -> ScopeGuard:
        database, manifest, root = map(no_symlinks, (database, manifest, root))
        scope = validate_scope(database, manifest, root)
        paths = (
            root,
            manifest.parent,
            database.parent,
            database,
            manifest,
            database.parent / "report.json",
        )
        return cls(
            database,
            manifest,
            root,
            scope,
            tuple((path.stat().st_dev, path.stat().st_ino) for path in paths),
        )

    def check_paths(self) -> None:
        paths = (
            self.root,
            self.manifest.parent,
            self.database.parent,
            self.database,
            self.manifest,
            self.database.parent / "report.json",
        )
        for index, path in enumerate(paths):
            private_owned(path, directory=index < 3)
            info = path.stat()
            if (info.st_dev, info.st_ino) != self.identities[index]:
                raise ScopeSafetyError

    def validate(self) -> None:
        self.check_paths()
        if validate_scope(self.database, self.manifest, self.root) != self.scope:
            raise ScopeSafetyError
