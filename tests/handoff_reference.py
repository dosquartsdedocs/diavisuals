"""Explicit, immutable test reference; never imported by the installed producer."""

from __future__ import annotations

import os
import pathlib
import runpy
import subprocess
import tempfile
from contextlib import contextmanager

REVISION = "9167e3efb5968a64bb9100792163a179c1491860"
REFERENCE = os.environ.get("DIAVISUALS_HANDOFF_REFERENCE", "")
PREFIX = "src/bash/mcp_factories"
FIXTURES = "tests/fixtures/mcp-artifact-handoff"


@contextmanager
def pinned_reference():
    """Read Git objects, not the sibling's working files; create only a temp fixture."""
    root = pathlib.Path(REFERENCE)
    if not REFERENCE or not root.is_absolute():
        raise ValueError("set DIAVISUALS_HANDOFF_REFERENCE to an explicit reference repository root")
    paths = [f"{PREFIX}/{name}" for name in (
        "ARTIFACT_HANDOFF.md", "artifact-handoff-v1.schema.json", "mcp-artifact-handoff.py",
    )] + [FIXTURES, "tests/test_mcp_artifact_handoff.py"]

    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, timeout=30).stdout

    with tempfile.TemporaryDirectory(prefix="diavisuals-pinned-reference-") as directory:
        snapshot = pathlib.Path(directory)
        for name in git("ls-tree", "-r", "--name-only", REVISION, "--", *paths).decode().splitlines():
            destination = snapshot / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(git("show", f"{REVISION}:{name}"))
        verifier = runpy.run_path(str(snapshot / PREFIX / "mcp-artifact-handoff.py"))
        yield snapshot, verifier["check"]
