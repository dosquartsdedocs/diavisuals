"""Exact-package stdio entry point, without importing from a consumer cwd."""
from __future__ import annotations

import pathlib
import sys

# Running this owned file (rather than `-m` from an arbitrary consumer cwd)
# binds the same package as the CLI that generated the client configuration.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from diavisuals.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["mcp", "serve"]))
