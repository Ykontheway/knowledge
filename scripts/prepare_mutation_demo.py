"""仅为本机演示新建隔离库；不接受业务数据库或用户文档，不声明真实身份。"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sqlite3
import stat
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
KIND = "knowledge-mutation-demo-v1"


class DemoError(Exception):
    """仅包含固定安全错误码。"""


def no_symlinks(path: Path) -> Path:
    candidate = path.expanduser().absolute()
    if ".." in candidate.parts:
        raise DemoError("INVALID_DEMO_PATH")
    for part in (candidate, *candidate.parents):
        if part.is_symlink():
            raise DemoError("INVALID_DEMO_PATH")
    return candidate


def private_owned(path: Path, mode: int, *, directory: bool = False) -> None:
    info = no_symlinks(path).stat()
    valid_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (
        not valid_type
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != mode
        or (not directory and info.st_nlink != 1)
    ):
        raise DemoError("DEMO_OWNERSHIP_REQUIRED")


def read_json(path: Path) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise DemoError("INVALID_DEMO_JSON")
            result[key] = value
        return result

    with path.open("rb") as stream:
        raw = stream.read(128 * 1024 + 1)
    if len(raw) > 128 * 1024:
        raise DemoError("INVALID_DEMO_JSON")
    value = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise DemoError("INVALID_DEMO_JSON")
    return value


def database_sources(database: Path) -> list[str]:
    """只读 ID/kind/content_type/config，不读取 source URI、locator、正文或 query。"""
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True, timeout=1)
    try:
        if connection.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
            raise DemoError("INVALID_DEMO_DATABASE")
        config = connection.execute(
            "SELECT enabled, dataset_id, dataset_version, dataset_hash "
            "FROM auto_evaluation_config WHERE id = 1"
        ).fetchone()
        if not config or config[0] != 1:
            raise DemoError("AUTO_EVALUATION_REQUIRED")
        dataset = connection.execute(
            "SELECT 1 FROM evaluation_sets WHERE id = ? AND version = ? AND content_hash = ?",
            config[1:],
        ).fetchone()
        if not dataset:
            raise DemoError("AUTO_EVALUATION_REQUIRED")
        rows = connection.execute(
            "SELECT s.id, s.kind, d.content_type FROM sources s "
            "LEFT JOIN documents d ON d.source_id = s.id"
        ).fetchall()
        if not rows or any(
            kind != "file" or content not in {"markdown", "text"} for _, kind, content in rows
        ):
            raise DemoError("INVALID_DEMO_SOURCES")
        sources = sorted({str(UUID(row[0])) for row in rows})
        if not 1 <= len(sources) <= 16:
            raise DemoError("INVALID_DEMO_SOURCES")
        return sources
    finally:
        connection.close()


def validate_demo(manifest_path: Path, database_path: Path) -> Path:
    """A 的严格 DTO/dbmatch 校验，加 B4 本机生成目录所有权和 enabled 门禁。"""
    try:
        manifest = no_symlinks(manifest_path)
        database = no_symlinks(database_path)
        root = no_symlinks(ROOT / ".knowledge" / "mutation-demo")
        parent = manifest.parent
        if (
            manifest.name != "mutation-manifest.json"
            or parent.parent != root
            or str(UUID(parent.name)) != parent.name
        ):
            raise DemoError("GENERATED_DEMO_REQUIRED")
        private_owned(root, 0o700, directory=True)
        private_owned(parent, 0o700, directory=True)
        private_owned(manifest, 0o600)
        private_owned(database, 0o600)
        database.relative_to(parent)
        if database.parent.parent != parent or database.name != "knowledge.db":
            raise DemoError("GENERATED_DEMO_REQUIRED")
        private_owned(database.parent, 0o700, directory=True)
        safety = importlib.import_module("knowledge.mutations.safety")
        scope = safety.load_mutation_scope(manifest, database)
        if str(scope.scope_id) != parent.name:
            raise DemoError("INVALID_DEMO_SCOPE")
        sources = database_sources(database)
        if sorted(str(value) for value in scope.allowed_source_ids) != sources:
            raise DemoError("INVALID_DEMO_SOURCES")
        report_path = database.parent / "report.json"
        private_owned(report_path, 0o600)
        report = read_json(report_path)
        if (
            report.get("status") != "passed"
            or report.get("artifacts", {}).get("database") != "knowledge.db"
        ):
            raise DemoError("ACCEPTANCE_REQUIRED")
        connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
        try:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not {"mutation_previews", "mutation_commands"}.issubset(tables):
                raise DemoError("MUTATION_SCHEMA_REQUIRED")
        finally:
            connection.close()
        return manifest
    except ImportError:
        raise DemoError("MUTATION_DEPENDENCIES_UNAVAILABLE") from None
    except DemoError:
        raise
    except Exception:
        raise DemoError("INVALID_DEMO") from None


@contextmanager
def local_environment() -> Iterator[None]:
    # runner 的正式 CLI 仅继承工具链环境，不继承认证 key/token/VITE_*。
    before = dict(os.environ)
    names = {"PATH", "HOME", "LANG", "VIRTUAL_ENV", "UV_CACHE_DIR", "TMPDIR", "SYSTEMROOT"}
    safe = {key: value for key, value in before.items() if key in names or key.startswith("LC_")}
    previous_umask = os.umask(0o077)
    try:
        os.environ.clear()
        os.environ.update(safe)
        yield
    finally:
        os.umask(previous_umask)
        os.environ.clear()
        os.environ.update(before)


def prepare() -> dict[str, object]:
    try:
        # 延迟 import：python scripts/prepare_mutation_demo.py --help 不需要 core/API 依赖。
        runner_module = importlib.import_module(
            "scripts.real_knowledge_acceptance" if __package__ else "real_knowledge_acceptance"
        )
        tables = importlib.import_module("knowledge.mutations.tables")
        storage = importlib.import_module("knowledge.storage")
    except ImportError:
        raise DemoError("MUTATION_DEPENDENCIES_UNAVAILABLE") from None
    except Exception:
        raise DemoError("DEMO_PREPARATION_FAILED") from None
    try:
        root = no_symlinks(ROOT / ".knowledge" / "mutation-demo")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        private_owned(root, 0o700, directory=True)
        scope_id = str(uuid4())
        parent = root / scope_id
        # 不复用、不覆盖、不 copy 已有数据库。UUID 冲突也失败。
        parent.mkdir(mode=0o700, exist_ok=False)
        with local_environment():
            runner = runner_module.Runner(parent)
            report_path = runner.run()
        if read_json(report_path).get("status") != "passed":
            raise DemoError("ACCEPTANCE_FAILED")
        database = no_symlinks(runner.database)
        sources = database_sources(database)
        engine = storage.create_sqlite_engine(f"sqlite+pysqlite:///{database.as_posix()}")
        try:
            tables.create_mutation_schema(engine)
        finally:
            engine.dispose()
        # 所有 seed/evaluation/report 副本仅当前用户可读。
        for directory, dirs, files in os.walk(parent, followlinks=False):
            for name in dirs:
                no_symlinks(Path(directory) / name).chmod(0o700)
            for name in files:
                target = no_symlinks(Path(directory) / name)
                if not target.is_file() or target.stat().st_nlink != 1:
                    raise DemoError("INVALID_DEMO_PATH")
                target.chmod(0o600)
        manifest = parent / "mutation-manifest.json"
        payload = {
            "kind": KIND,
            "scope_id": scope_id,
            "database": database.relative_to(parent).as_posix(),
            "allowed_source_ids": sources,
            "created_at": datetime.now(UTC).isoformat(),
        }
        descriptor = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        validate_demo(manifest, database)
        return {
            "status": "ready",
            "manifest": manifest.relative_to(ROOT).as_posix(),
            "database": database.relative_to(ROOT).as_posix(),
            "scope_id": scope_id,
            "source_ids": sources,
        }
    except DemoError:
        raise
    except Exception:
        raise DemoError("DEMO_PREPARATION_FAILED") from None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        result = prepare()
    except DemoError as error:
        print(json.dumps({"status": "unavailable", "error_code": str(error)}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
