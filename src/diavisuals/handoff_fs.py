"""Bounded, no-follow host I/O for the opt-in artifact producer (Linux).

Protocol paths follow MCP artifact handoff v1, reviewed at central revision
9167e3efb5968a64bb9100792163a179c1491860. No central checkout is used at runtime.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import math
import os
import pathlib
import re
import stat
import unicodedata
from contextlib import contextmanager

MAX_FILE = 64 * 1024 * 1024  # Owner profile is deliberately smaller than v1.
MAX_MANIFEST = 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024
MAX_ENTRIES = 10000
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def parse_json(raw: bytes) -> dict:
    def pairs(items: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(value: str) -> None:
        raise ValueError("non-finite JSON number")

    require(len(raw) <= MAX_MANIFEST, "JSON exceeds manifest limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("expected bounded UTF-8 JSON") from exc
    require(type(value) is dict, "JSON document must be an object")
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        require(depth <= 32 and nodes <= 100000, "JSON depth or node limit exceeded")
        require(not isinstance(item, float) or math.isfinite(item), "non-finite JSON number")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def safe_path(value: str) -> str:
    require(isinstance(value, str) and 0 < len(value) <= 1024, "invalid relative path")
    require(unicodedata.normalize("NFC", value) == value, "paths must use NFC Unicode")
    require(not any(unicodedata.category(c).startswith("C") or c in '\\:%$*?[]{}<>"|' for c in value),
            "path contains reserved characters")
    parts = value.split("/")
    require(len(parts) <= 64, "path depth exceeds 64")
    for part in parts:
        require(part not in ("", ".", "..") and part == part.strip() and not part.endswith("."),
                "path must be normalized and relative")
        require(part.casefold() not in {".git", ".hg", ".svn"} and not part.startswith("~"), "reserved path component")
        require(re.fullmatch(r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?", part) is None, "reserved device name")
    return value


def unique_paths(paths: list[str]) -> None:
    require(len(paths) == len(set(paths)), "duplicate path")
    files = set(paths)
    aliases: dict[str, str] = {}
    for path in paths:
        parts = safe_path(path).split("/")
        for length in range(1, len(parts) + 1):
            prefix = "/".join(parts[:length])
            require(aliases.get(prefix.casefold(), prefix) == prefix, "case-aliased path")
            aliases[prefix.casefold()] = prefix
            require(length == len(parts) or prefix not in files, "file/directory collision")


def signature(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class Workspace:
    def __init__(self, root: str | pathlib.Path):
        raw = os.fspath(root)
        require(os.path.isabs(raw) and raw != "/" and str(pathlib.PurePosixPath(raw)) == raw
                and not raw.startswith("//") and not any(unicodedata.category(char).startswith("C") for char in raw)
                and ".." not in pathlib.PurePosixPath(raw).parts, "workspace must be an explicit normalized absolute directory")
        self.root = pathlib.Path(raw)
        self.fd = os.open("/", DIR_FLAGS)
        self.snapshots: dict[str, tuple] = {}
        self.directories: dict[str, tuple] = {}
        self.total = 0
        try:
            for part in self.root.parts[1:]:
                child = os.open(part, DIR_FLAGS, dir_fd=self.fd)
                os.close(self.fd)
                self.fd = child
        except BaseException:
            os.close(self.fd)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        os.close(self.fd)

    @contextmanager
    def directory(self, path: str = "", *, create: bool = False):
        fd = os.dup(self.fd)
        try:
            for part in safe_path(path).split("/") if path else []:
                # Detect directory-component aliases, including pre-existing ones.
                require(not any(name != part and name.casefold() == part.casefold() for name in os.listdir(fd)),
                        "case-aliased directory")
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                child = os.open(part, DIR_FLAGS, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd
        finally:
            os.close(fd)

    def read(self, path: str, limit: int = MAX_FILE, *, package_asset: bool = False) -> bytes:
        safe_path(path)
        require(path in self.snapshots or len(self.snapshots) < MAX_ENTRIES, "file count limit exceeded")
        parent, _, name = path.rpartition("/")
        with self.directory(parent) as parent_fd:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent_fd)
            try:
                before = os.fstat(fd)
                # uv may hardlink installed package files to its immutable cache.
                # This exception is for factory package reads only; consumer and
                # protocol trees always require ordinary independent files.
                require(stat.S_ISREG(before.st_mode) and (package_asset or before.st_nlink == 1),
                        "only regular non-hardlinked files are supported")
                require(before.st_size <= limit, "file byte limit exceeded")
                chunks = []
                size = 0
                while True:
                    chunk = os.read(fd, min(1024 * 1024, limit - size + 1))
                    if not chunk:
                        break
                    size += len(chunk)
                    self.total += len(chunk)
                    require(size <= limit and self.total <= MAX_TOTAL, "read byte limit exceeded")
                    chunks.append(chunk)
                after = os.fstat(fd)
                linked = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                require(signature(before) == signature(after) == signature(linked) and size == after.st_size,
                        "file changed during read")
                require(self.snapshots.get(path, signature(after)) == signature(after), "file changed between reads")
                self.snapshots[path] = signature(after)
                return b"".join(chunks)
            finally:
                os.close(fd)

    def write_new(self, path: str, data: bytes, *, mode: int = 0o600) -> None:
        safe_path(path)
        parent, _, name = path.rpartition("/")
        with self.directory(parent, create=True) as fd:
            require(not any(entry.casefold() == name.casefold() for entry in os.listdir(fd)), "destination already exists or is case-aliased")
            output = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode, dir_fd=fd)
            with os.fdopen(output, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fchmod(handle.fileno(), mode)
                os.fsync(handle.fileno())
            os.fsync(fd)

    def inventory(self, base: str) -> set[str]:
        files: set[str] = set()
        directories: set[str] = set()
        count = 0

        def walk(fd: int, prefix: str) -> None:
            nonlocal count
            before = signature(os.fstat(fd))
            for name in os.listdir(fd):
                count += 1
                require(count <= MAX_ENTRIES, "tree entry limit exceeded")
                path = safe_path(f"{prefix}/{name}" if prefix else name)
                safe_path(f"{base}/{path}" if base else path)
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    directories.add(path)
                    child = os.open(name, DIR_FLAGS, dir_fd=fd)
                    try:
                        require(signature(info) == signature(os.fstat(child)), "directory changed")
                        walk(child, path)
                    finally:
                        os.close(child)
                else:
                    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "tree contains a link or special file")
                    files.add(path)
            require(signature(os.fstat(fd)) == before, "directory changed during inventory")
            self.directories["/".join(part for part in (base, prefix) if part)] = before

        with self.directory(base) as fd:
            walk(fd, "")
        expected_dirs = {str(parent) for file in files for parent in pathlib.PurePosixPath(file).parents if str(parent) != "."}
        require(directories == expected_dirs, "undeclared or empty directory")
        unique_paths(sorted(files))
        return files

    def recheck(self) -> None:
        # Re-open the absolute root as well: do not hide ancestor substitutions.
        with Workspace(self.root) as current:
            actual, expected = os.fstat(current.fd), os.fstat(self.fd)
            require((actual.st_dev, actual.st_ino) == (expected.st_dev, expected.st_ino), "workspace changed")
        for path, expected in self.directories.items():
            with self.directory(path) as fd:
                require(signature(os.fstat(fd)) == expected, "directory changed before completion")
        for path, expected in self.snapshots.items():
            parent, _, name = path.rpartition("/")
            with self.directory(parent) as fd:
                require(signature(os.stat(name, dir_fd=fd, follow_symlinks=False)) == expected, "file changed before completion")


def rename_new(source_fd: int, source: str, target_fd: int, target: str) -> None:
    """Atomic directory publication with kernel-enforced no-replacement."""
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, "renameat2", None)
    require(function is not None, "artifact publication requires libc renameat2")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(source_fd, os.fsencode(source), target_fd, os.fsencode(target), 1) != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise FileExistsError("bundle destination already exists; choose a new bundle_id")
        raise OSError(code, os.strerror(code))
    os.fsync(source_fd)
    os.fsync(target_fd)
