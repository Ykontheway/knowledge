"""Installed core-only replay smoke: no source checkout, optional SDK or HTTP service."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path


def main() -> None:
    for name in ("fastapi", "uvicorn", "mcp", "tiktoken", "httpx", "openai", "lancedb"):
        assert importlib.util.find_spec(name) is None, "replay core optional boundary"
    import knowledge
    from knowledge.replay import export_replay, load_validate

    location = Path(knowledge.__file__).resolve()
    assert "site-packages" in location.parts, "replay must use installed package"
    original = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="replay-installed-") as temporary:
        os.chdir(temporary)
        try:
            output = Path("replay.json")
            export_replay(output)
            before = {p: p.read_bytes() for p in Path(".").rglob("*") if p.is_file()}
            bundle = load_validate(output)
            after = {p: p.read_bytes() for p in Path(".").rglob("*") if p.is_file()}
            assert before == after, "replay check wrote files"
            assert len(bundle.resources.jobs) == 3
            assert len(bundle.resources.diffs) == 16
            assert not any(
                name.startswith(
                    ("fastapi", "uvicorn", "mcp", "tiktoken", "httpx", "openai", "lancedb")
                )
                for name in sys.modules
            ), "replay eagerly imported optional runtime"
        finally:
            os.chdir(original)
    print(json.dumps({"passed": True, "mode": "replay_core", "jobs": 3, "diffs": 16}))


if __name__ == "__main__":
    main()
