"""Export only self-generated public synthetic replay, or check an existing static file."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from knowledge.replay import ReplayError, export_replay, load_validate


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # Do not reflect arbitrary arguments, paths, URLs, queries or credentials.
        self.exit(2, "REPLAY_ARGUMENT_INVALID\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output", type=Path, default=Path("web/public/replay.json"))
    parser.add_argument("--check", action="store_true", help="Read-only validation of static JSON.")
    args = parser.parse_args(argv)
    try:
        if args.check:
            load_validate(args.output)
        else:
            export_replay(args.output)
    except ReplayError as error:
        print(error.code, file=sys.stderr)
        return 1
    except Exception:
        # Storage/SDK/IO exceptions must not expose raw input or local paths.
        print("REPLAY_OPERATION_FAILED", file=sys.stderr)
        return 1
    print("REPLAY_VALID" if args.check else "REPLAY_EXPORTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
