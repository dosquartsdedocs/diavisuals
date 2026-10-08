"""Optional independent W1 checks from the exact reviewed Git objects."""
from __future__ import annotations

import importlib
import os
import pathlib
import subprocess
import sys
import tempfile
from contextlib import contextmanager

REVISION = "83cb0d3e2f424759475ae70b423a0f8dca8520b2"
REFERENCE = os.environ.get("DIAVISUALS_STORAGE_REFERENCE", "")
PREFIX = "src/bash/mcp_factories"


@contextmanager
def pinned_reference():
    if not REFERENCE or not pathlib.Path(REFERENCE).is_absolute():
        raise ValueError("select DIAVISUALS_STORAGE_REFERENCE explicitly")

    def git(*args):
        return subprocess.run(["git", "-C", REFERENCE, *args], check=True, capture_output=True, timeout=30).stdout

    paths = [f"{PREFIX}/{name}" for name in ("job-storage-v1.schema.json", "mcp_job_storage", "mcp_preparation", "mcp_distribution")]
    with tempfile.TemporaryDirectory(prefix="diavisuals-w1-reference-") as temporary:
        root = pathlib.Path(temporary)
        for name in git("ls-tree", "-r", "--name-only", REVISION, "--", *paths).decode().splitlines():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(git("show", f"{REVISION}:{name}"))
        sys.path.insert(0, str(root / PREFIX))
        try:
            contract = importlib.import_module("mcp_job_storage.contract")
            planner = importlib.import_module("mcp_job_storage.planner")
            yield contract, planner
        finally:
            sys.path.remove(str(root / PREFIX))
            for name in list(sys.modules):
                if name.split(".")[0] in {"mcp_job_storage", "mcp_preparation", "mcp_distribution"}:
                    del sys.modules[name]
