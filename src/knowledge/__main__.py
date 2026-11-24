"""Allow ``python -m knowledge`` to run the CLI."""

from knowledge.cli import main

raise SystemExit(main())
