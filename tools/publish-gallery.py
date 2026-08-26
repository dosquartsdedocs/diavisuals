#!/usr/bin/env python3
from __future__ import annotations

import csv
import ctypes
import errno
import os
import pathlib
import re
import shutil
import stat
import sys
import uuid
import xml.etree.ElementTree as ET

MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def validate_name(value: str, label: str) -> None:
    if value in {".", ".."} or not SAFE_NAME.fullmatch(value):
        raise ValueError(f"unsafe {label}: {value}")


def validate_gallery(result: pathlib.Path, family: str, compatibility: str) -> None:
    metadata = result.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or result.is_symlink():
        raise ValueError("gallery result is not a regular directory")

    manifest = result / "manifest.csv"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("gallery manifest was not created")

    prefix = pathlib.PurePosixPath("docs", "gallery", family, compatibility)
    expected_svgs: set[pathlib.PurePosixPath] = set()
    with manifest.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["engine", "type", "status", "output"]:
            raise ValueError("gallery manifest has an invalid header")
        for row in reader:
            engine = row["engine"]
            diagram_type = row["type"]
            if engine not in {"mermaid", "plantuml"} or not SAFE_NAME.fullmatch(diagram_type):
                raise ValueError(f"gallery manifest has an unsafe row: {row}")
            if row["status"] != "rendered":
                raise ValueError(f"gallery manifest has a non-rendered row: {row}")
            output = pathlib.PurePosixPath(row["output"])
            expected = prefix / engine / f"{diagram_type}.svg"
            if output != expected:
                raise ValueError(f"gallery manifest has an unsafe output path: {output}")
            expected_svgs.add(pathlib.PurePosixPath(engine, f"{diagram_type}.svg"))
    if not expected_svgs:
        raise ValueError("gallery manifest contains no rendered outputs")

    actual_svgs: set[pathlib.PurePosixPath] = set()
    preview_count = 0
    allowed_directories = {
        pathlib.PurePosixPath("mermaid"),
        pathlib.PurePosixPath("plantuml"),
        pathlib.PurePosixPath("readme"),
    }
    for artifact in result.rglob("*"):
        relative = pathlib.PurePosixPath(artifact.relative_to(result).as_posix())
        artifact_metadata = artifact.lstat()
        if stat.S_ISLNK(artifact_metadata.st_mode):
            raise ValueError(f"gallery output must not be a symlink: {relative}")
        if stat.S_ISDIR(artifact_metadata.st_mode):
            if relative not in allowed_directories:
                raise ValueError(f"unexpected gallery directory: {relative}")
            continue
        if not stat.S_ISREG(artifact_metadata.st_mode):
            raise ValueError(f"gallery output is not a regular file: {relative}")
        if artifact_metadata.st_size <= 0 or artifact_metadata.st_size > MAX_ARTIFACT_BYTES:
            raise ValueError(f"gallery output has an invalid size: {relative}")
        if relative == pathlib.PurePosixPath("manifest.csv"):
            continue
        if relative.suffix == ".svg" and relative.parts[0] in {"mermaid", "plantuml"}:
            root = ET.parse(artifact).getroot()
            if root.tag.rsplit("}", 1)[-1].lower() != "svg":
                raise ValueError(f"gallery output is not an SVG: {relative}")
            actual_svgs.add(relative)
            continue
        if relative.suffix == ".png" and relative.parts[0] == "readme":
            with artifact.open("rb") as handle:
                if handle.read(8) != b"\x89PNG\r\n\x1a\n":
                    raise ValueError(f"gallery output is not a PNG: {relative}")
            preview_count += 1
            continue
        raise ValueError(f"unexpected gallery output: {relative}")

    if actual_svgs != expected_svgs:
        raise ValueError("gallery SVG outputs do not match the manifest")
    if preview_count == 0:
        raise ValueError("gallery contains no README previews")


def open_directory(name: str | pathlib.Path, *, dir_fd: int | None = None) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.open(name, flags, dir_fd=dir_fd)


def remove_entry(parent_fd: int, name: str) -> None:
    path = pathlib.Path(f"/proc/self/fd/{parent_fd}") / name
    metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if stat.S_ISDIR(metadata.st_mode):
        shutil.rmtree(path)
    else:
        os.unlink(name, dir_fd=parent_fd)


def publish_gallery(result: pathlib.Path, repository: pathlib.Path, family: str, compatibility: str) -> None:
    repository_fd = open_directory(repository)
    docs_fd = gallery_fd = family_fd = -1
    replacement_name = f".{compatibility}.new.{uuid.uuid4().hex}"
    replacement_exists = False
    try:
        docs_fd = open_directory("docs", dir_fd=repository_fd)
        gallery_fd = open_directory("gallery", dir_fd=docs_fd)
        try:
            os.mkdir(family, mode=0o755, dir_fd=gallery_fd)
        except FileExistsError:
            pass
        family_fd = open_directory(family, dir_fd=gallery_fd)
        os.mkdir(replacement_name, mode=0o755, dir_fd=family_fd)
        replacement_exists = True
        replacement = pathlib.Path(f"/proc/self/fd/{family_fd}") / replacement_name
        shutil.copytree(result, replacement, dirs_exist_ok=True)
        for path in [replacement, *replacement.rglob("*")]:
            path.chmod(0o755 if path.is_dir() else 0o644)

        try:
            os.stat(compatibility, dir_fd=family_fd, follow_symlinks=False)
            target_exists = True
        except FileNotFoundError:
            target_exists = False
        if target_exists:
            libc = ctypes.CDLL(None, use_errno=True)
            renameat2 = getattr(libc, "renameat2", None)
            if renameat2 is None:
                raise OSError(errno.ENOSYS, "atomic gallery replacement requires libc renameat2")
            renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            result_code = renameat2(
                family_fd,
                os.fsencode(replacement_name),
                family_fd,
                os.fsencode(compatibility),
                2,
            )
            if result_code != 0:
                raise OSError(ctypes.get_errno(), "renameat2 exchange failed")
            remove_entry(family_fd, replacement_name)
        else:
            os.rename(replacement_name, compatibility, src_dir_fd=family_fd, dst_dir_fd=family_fd)
        replacement_exists = False
        os.fsync(family_fd)
    finally:
        if replacement_exists and family_fd >= 0:
            try:
                remove_entry(family_fd, replacement_name)
            except FileNotFoundError:
                pass
        for descriptor in (family_fd, gallery_fd, docs_fd, repository_fd):
            if descriptor >= 0:
                os.close(descriptor)


def main() -> int:
    if len(sys.argv) != 5:
        raise SystemExit("usage: publish-gallery.py RESULT REPOSITORY FAMILY COMPATIBILITY")
    result = pathlib.Path(sys.argv[1])
    repository = pathlib.Path(sys.argv[2])
    family = sys.argv[3]
    compatibility = sys.argv[4]
    try:
        validate_name(family, "family")
        validate_name(compatibility, "compatibility id")
        validate_gallery(result, family, compatibility)
        publish_gallery(result, repository, family, compatibility)
    except (OSError, ValueError, ET.ParseError) as exc:
        print(f"gallery publication failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
