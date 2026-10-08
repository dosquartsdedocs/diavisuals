"""Offline independent W1 checks; optional comparison to exact reviewed Git objects."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import types
from contextlib import contextmanager

REVISION = "83cb0d3e2f424759475ae70b423a0f8dca8520b2"
REFERENCE = os.environ.get("DIAVISUALS_STORAGE_REFERENCE", "")
PREFIX = "src/bash/mcp_factories"
ARCHIVE_SHA256 = "92a3e3dd65a8bd50d72301c42971a8c47fbe031c851b2237937f389ad3d2a95d"
FILES = [f"{PREFIX}/{name}" for name in ("job-storage-v1.schema.json", "mcp_job_storage/contract.py", "mcp_job_storage/planner.py")]


def reference_primitives():
    """Adapt the upstream imports, not its schema/semantic/release decisions."""
    from diavisuals.handoff_fs import Workspace, parse_json

    class PreparationError(ValueError):
        def __init__(self, code, message, invalid=False):
            super().__init__(message)
            self.code, self.invalid = code, invalid

    def fail(code, message, *, invalid=False):
        raise PreparationError(code, message, invalid)

    def parse(data, *, maximum=1024 * 1024):
        if len(data) > maximum:
            fail("limit-exceeded", "JSON input exceeds bound", invalid=True)
        try:
            return parse_json(data)
        except ValueError as error:
            fail("invalid-document", str(error), invalid=True)

    def read(path, *, maximum=1024 * 1024):
        path = pathlib.Path(path)
        with Workspace(path.parent) as workspace:
            data = workspace.read(path.name, maximum)
            workspace.recheck()
        return data

    def check_sha(value):
        import re
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            fail("invalid-document", "invalid SHA-256", invalid=True)
        return value

    package = types.ModuleType("mcp_preparation")
    package.__path__ = []
    contract = types.ModuleType("mcp_preparation.contract")
    contract.PreparationError, contract.fail, contract.parse_json = PreparationError, fail, parse
    contract.digest = lambda raw: hashlib.sha256(raw).hexdigest()
    contract.sha256 = check_sha
    contract.json_bytes = lambda value: (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode()
    storage = types.ModuleType("mcp_preparation.storage")
    storage.read_regular = read
    sys.modules.update({module.__name__: module for module in (package, contract, storage)})


@contextmanager
def pinned_reference():
    if REFERENCE and not pathlib.Path(REFERENCE).is_absolute():
        raise ValueError("DIAVISUALS_STORAGE_REFERENCE must be absolute")

    def git(*args):
        return subprocess.run(["git", "-C", REFERENCE, *args], check=True, capture_output=True, timeout=30).stdout

    paths = [f"{PREFIX}/{name}" for name in ("job-storage-v1.schema.json", "mcp_job_storage", "mcp_preparation", "mcp_distribution")]
    with tempfile.TemporaryDirectory(prefix="diavisuals-w1-reference-") as temporary:
        root = pathlib.Path(temporary)
        archive_path = pathlib.Path(__file__).parent / "fixtures/w1-reference/reference.tar"
        raw = archive_path.read_bytes()
        assert len(raw) <= 128 * 1024 and hashlib.sha256(raw).hexdigest() == ARCHIVE_SHA256
        frozen = {}
        with tarfile.open(archive_path, "r:") as archive:
            for item in archive:
                if item.isdir():
                    continue
                assert item.isfile() and item.name in FILES and item.name not in frozen and item.size <= 65536
                frozen[item.name] = archive.extractfile(item).read(65537)
        assert frozen.keys() == set(FILES)
        selected = git("ls-tree", "-r", "--name-only", REVISION, "--", *paths).decode().splitlines() if REFERENCE else FILES
        for name in selected:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            data = git("show", f"{REVISION}:{name}") if REFERENCE else frozen[name]
            if name in frozen:
                assert data == frozen[name], "reference fixture differs from pinned Git objects"
            path.write_bytes(data)
        if not REFERENCE:
            reference_primitives()
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
