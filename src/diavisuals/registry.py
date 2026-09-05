from __future__ import annotations

import base64
import csv
import fcntl
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import yaml

from . import __version__

DEFAULT_RELEASE = f"v{__version__}"
DEFAULT_COMPATIBILITY = "mermaid-11.16.0-plantuml-1.2026.1"
DEFAULT_FAMILY = "benizar"
DEFAULT_REMOTE = "git@github.com:dosquartsdedocs/diavisuals.git"
MCP_VERSION = "1.29.0"
RENDERER_CONTAINER_LABEL = "io.context.mcp-factory=diavisuals"
RENDERER_WORKSPACE_LABEL = "io.context.mcp-factory.workspace"
HEX_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
STYLE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
DOCKER_IMAGE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/@:-]*\Z")
DOCKER_IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
DOCKER_CONTAINER_ID_RE = re.compile(r"[0-9a-f]{12,64}\Z")
MAX_RENDERED_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_INLINE_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_DIAGRAM_SOURCE_BYTES = 4 * 1024 * 1024
MAX_RENDER_DIAGNOSTIC_BYTES = 64 * 1024
RENDER_TIMEOUT_SECONDS = 300
RENDERER_FALLBACK_UID_GID = "65532:65532"
RENDERER_MEMORY = "1g"
RENDERER_CPUS = "2"
RENDERER_PIDS_LIMIT = "256"
RENDERER_NOFILE_LIMIT = "1024:1024"
RENDERER_FSIZE_LIMIT = f"{MAX_RENDERED_ARTIFACT_BYTES}:{MAX_RENDERED_ARTIFACT_BYTES}"
RENDERER_TMPFS = "/tmp:rw,nosuid,nodev,noexec,size=512m,mode=1777"
MERMAID_TEXT_STARTS = {
    "architecture-beta",
    "block",
    "classdiagram",
    "erdiagram",
    "flowchart",
    "gantt",
    "gitgraph",
    "graph",
    "journey",
    "kanban",
    "mindmap",
    "packet-beta",
    "pie",
    "quadrantchart",
    "requirementdiagram",
    "sankey-beta",
    "sequencediagram",
    "statediagram",
    "statediagram-v2",
    "timeline",
    "treemap-beta",
    "xychart-beta",
}
OUTPUT_MIME_TYPES = {
    "svg": "image/svg+xml",
    "png": "image/png",
    "pdf": "application/pdf",
}
UNALTRAWEB_DIAGRAM_ROOTS = ("assets", "_chapters", "_documentation")
DIAGRAM_SOURCE_SUFFIXES = frozenset({".mmd", ".mermaid", ".puml", ".plantuml", ".uml"})
PROJECT_RECEIPT_PATH = pathlib.Path(".unaltraweb/receipts/diavisuals.json")
PROJECT_RECEIPT_PREFIX = b"unaltraweb-companion-receipt-v1\0diavisuals\0"
MAX_PROJECT_DIAGRAMS = 500
MAX_PROJECT_SCAN_ENTRIES = 100_000
MAX_PROJECT_SCAN_DEPTH = 64
MAX_COMPANION_ARTIFACT_BYTES = 16 * 1024 * 1024
MCP_TOOL_NAMES = (
    "style_inventory",
    "style_audit",
    "check_styles",
    "compatibility_status",
    "release_status",
    "submodule_plan",
    "project_check",
    "render_diagram",
    "render_diagram_text",
    "update",
    "factory_manifest",
)
MCP_RESOURCE_URIS = (
    "diavisuals://agent-guide",
    "diavisuals://styles",
    "diavisuals://compatibility",
    "diavisuals://style-audit",
    "diavisuals://examples",
    "diavisuals://project/check",
    "diavisuals://factory-manifest",
)


def repo_dir() -> pathlib.Path:
    env = os.environ.get("DIAVISUALS_DIR", "").strip()
    if env:
        return pathlib.Path(env).expanduser().resolve()

    module_path = pathlib.Path(__file__).resolve()
    checkout = module_path.parents[2]
    if (checkout / "styles").is_dir() and (checkout / "compat").is_dir():
        return checkout

    packaged = module_path.parent / "assets"
    if packaged.is_dir():
        return packaged

    return checkout


def source_checkout() -> pathlib.Path | None:
    candidate = pathlib.Path(__file__).resolve().parents[2]
    if (candidate / ".git").exists() and (candidate / "pyproject.toml").is_file():
        return candidate
    return None


def factory_metadata_root() -> pathlib.Path:
    checkout = source_checkout()
    return checkout if checkout is not None else pathlib.Path(__file__).resolve().parent / "assets"


def _docker_config_root() -> pathlib.Path:
    configured = os.environ.get("DOCKER_CONFIG", "").strip()
    root = pathlib.Path(configured).expanduser() if configured else pathlib.Path.home() / ".docker"
    return pathlib.Path(os.path.abspath(root))


def _docker_endpoint_scope() -> dict[str, str]:
    context = os.environ.get("DOCKER_CONTEXT", "").strip()
    if context:
        if context == "default":
            return {"kind": "host", "value": "unix:///var/run/docker.sock"}
        return {"kind": "context", "value": context, "config": str(_docker_config_root())}

    host = os.environ.get("DOCKER_HOST", "").strip()
    if host:
        return {"kind": "host", "value": host}

    config_root = _docker_config_root()
    try:
        with (config_root / "config.json").open("rb") as config_handle:
            raw = config_handle.read(1024 * 1024 + 1)
        config = json.loads(raw) if len(raw) <= 1024 * 1024 else {}
        current = str(config.get("currentContext") or "").strip() if isinstance(config, dict) else ""
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        current = ""
    if current and current != "default":
        return {"kind": "context", "value": current, "config": str(config_root)}
    return {"kind": "host", "value": "unix:///var/run/docker.sock"}


def _renderer_lock_name(image: str) -> str:
    scope = json.dumps(_docker_endpoint_scope(), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(scope.encode("utf-8") + b"\0" + image.encode("utf-8")).hexdigest()
    return f"{digest}.lock"


def _open_renderer_lock_directory() -> int:
    uid = os.geteuid()
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    candidates = (
        (pathlib.Path(f"/run/user/{uid}"), ".unaltra-renderer-locks", True),
        (pathlib.Path("/tmp"), f".unaltra-renderer-locks-{uid}", False),
    )
    failures: list[str] = []
    for parent, name, private_parent in candidates:
        parent_descriptor = -1
        directory_descriptor = -1
        try:
            parent_descriptor = os.open(parent, directory_flags)
            parent_status = os.fstat(parent_descriptor)
            parent_mode = stat.S_IMODE(parent_status.st_mode)
            if not stat.S_ISDIR(parent_status.st_mode):
                raise OSError("lock parent is not a directory")
            if private_parent:
                if parent_status.st_uid != uid or parent_mode & 0o077:
                    raise OSError("runtime lock parent is not private to the current user")
            elif parent_status.st_uid not in {0, uid} or not parent_status.st_mode & stat.S_ISVTX:
                raise OSError("temporary lock parent is not sticky and trusted")

            try:
                os.mkdir(name, mode=0o700, dir_fd=parent_descriptor)
            except FileExistsError:
                pass
            directory_descriptor = os.open(name, directory_flags, dir_fd=parent_descriptor)
            directory_status = os.fstat(directory_descriptor)
            directory_mode = stat.S_IMODE(directory_status.st_mode)
            if (
                not stat.S_ISDIR(directory_status.st_mode)
                or directory_status.st_uid != uid
                or directory_mode & 0o077
            ):
                raise OSError("renderer lock directory is not private to the current user")
            return directory_descriptor
        except OSError as exc:
            if directory_descriptor >= 0:
                os.close(directory_descriptor)
            failures.append(f"{parent}: {exc}")
        finally:
            if parent_descriptor >= 0:
                os.close(parent_descriptor)
    raise RuntimeError(f"cannot open shared renderer lock directory: {'; '.join(failures)}")


@contextmanager
def _renderer_build_lock(image: str) -> Iterator[None]:
    directory_descriptor = _open_renderer_lock_directory()
    descriptor = -1
    locked = False
    try:
        try:
            descriptor = os.open(
                _renderer_lock_name(image),
                os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_descriptor,
            )
            lock_status = os.fstat(descriptor)
            if (
                not stat.S_ISREG(lock_status.st_mode)
                or lock_status.st_uid != os.geteuid()
                or stat.S_IMODE(lock_status.st_mode) & 0o077
                or lock_status.st_nlink != 1
            ):
                raise RuntimeError("renderer build lock is not a private regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            raise RuntimeError(f"cannot open renderer build lock: {exc}") from exc
        locked = True
        yield
    finally:
        try:
            if locked:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(directory_descriptor)


def rel(path: pathlib.Path, root: pathlib.Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def run(command: list[str], cwd: pathlib.Path | None = None, timeout: int = 120) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd or repo_dir()),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return {
            "command": command,
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
        return {
            "command": command,
            "returncode": 124,
            "stdout": stdout[-MAX_RENDER_DIAGNOSTIC_BYTES:],
            "stderr": stderr[-MAX_RENDER_DIAGNOSTIC_BYTES:] or f"command timed out after {timeout} seconds",
        }
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-MAX_RENDER_DIAGNOSTIC_BYTES:],
        "stderr": completed.stderr[-MAX_RENDER_DIAGNOSTIC_BYTES:],
    }


def git_head(path: pathlib.Path | None = None) -> str | None:
    root = path or repo_dir()
    result = run(["git", "-C", str(root), "rev-parse", "HEAD"], cwd=root)
    if result["returncode"] == 0:
        return str(result["stdout"]).strip()
    return None


def git_tag(path: pathlib.Path | None = None) -> str | None:
    root = path or repo_dir()
    result = run(["git", "-C", str(root), "describe", "--tags", "--exact-match"], cwd=root)
    if result["returncode"] == 0:
        return str(result["stdout"]).strip()
    return None


def parse_env(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def renderer_profile(profile: str = DEFAULT_COMPATIBILITY) -> dict[str, Any]:
    compat = compatibility_status(profile)
    values = compat.get("values", {}) if isinstance(compat.get("values"), dict) else {}
    image = str(values.get("DIAVISUALS_RENDER_IMAGE") or "").strip()
    dockerfile = str(values.get("DIAVISUALS_RENDER_DOCKERFILE") or "").strip()
    plantuml_sha256 = str(values.get("PLANTUML_SHA256") or "").strip()
    profile_status = str(values.get("DIAVISUALS_PROFILE_STATUS") or "").strip()
    issues: list[str] = []
    if not compat.get("ok"):
        issues.append(f"missing compatibility profile: {profile}")
    if profile_status != "supported-renderer":
        issues.append(f"compatibility profile is not renderable: {profile_status or 'status missing'}")
    if not image:
        issues.append("compatibility profile does not define DIAVISUALS_RENDER_IMAGE")
    elif not DOCKER_IMAGE_RE.fullmatch(image):
        issues.append("compatibility profile defines an invalid renderer image")
    if not dockerfile:
        issues.append("compatibility profile does not define DIAVISUALS_RENDER_DOCKERFILE")
    if dockerfile and not re.fullmatch(r"[0-9A-Fa-f]{64}", plantuml_sha256):
        issues.append("compatibility profile does not define a valid PLANTUML_SHA256")

    root = repo_dir().resolve()
    dockerfile_path = (root / dockerfile).resolve() if dockerfile else None
    if dockerfile_path is not None:
        if not path_within(dockerfile_path, root):
            issues.append(f"renderer Dockerfile is outside the asset root: {dockerfile}")
        elif not dockerfile_path.is_file():
            issues.append(f"renderer Dockerfile not found: {dockerfile}")

    return {
        "ok": not issues,
        "profile": str(compat.get("requested") or pathlib.Path(profile).stem),
        "image": image,
        "dockerfile": dockerfile,
        "dockerfile_path": str(dockerfile_path) if dockerfile_path else None,
        "values": values,
        "issues": issues,
    }


def _build_renderer_image(renderer: dict[str, Any], root: pathlib.Path, *, dry_run: bool) -> dict[str, Any]:
    values = renderer["values"]

    def command_for(context: pathlib.Path | str) -> list[str]:
        return [
            "docker",
            "build",
            "--pull",
            "-f",
            str(pathlib.Path(context) / "Dockerfile"),
            "--build-arg",
            f"MERMAID_CLI_VERSION={values.get('MERMAID_CLI_VERSION', '')}",
            "--build-arg",
            f"PUPPETEER_VERSION={values.get('PUPPETEER_VERSION', '')}",
            "--build-arg",
            f"PLANTUML_VERSION={values.get('PLANTUML_VERSION', '')}",
            "--build-arg",
            f"PLANTUML_SHA256={values.get('PLANTUML_SHA256', '')}",
            "-t",
            renderer["image"],
            str(context),
        ]

    if dry_run:
        command = command_for("/tmp/diavisuals-build-PRIVATE")
        return {"ok": True, "dry_run": True, "renderer": renderer, "command": command}
    with tempfile.TemporaryDirectory(prefix="diavisuals-build-") as temporary:
        context = pathlib.Path(temporary)
        shutil.copyfile(renderer["dockerfile_path"], context / "Dockerfile")
        docker_assets = pathlib.Path(renderer["dockerfile_path"]).parent
        for package_file in ("package.json", "package-lock.json"):
            source = docker_assets / package_file
            if not source.is_file() or source.is_symlink():
                return {
                    "ok": False,
                    "renderer": renderer,
                    "message": f"renderer build asset is missing or unsafe: {package_file}",
                }
            shutil.copyfile(source, context / package_file)
        command = command_for(context)
        result = run(command, cwd=root, timeout=1800)
    return {"ok": result["returncode"] == 0, "renderer": renderer, "result": result}


def build_renderer_image(profile: str = DEFAULT_COMPATIBILITY, *, dry_run: bool = False) -> dict[str, Any]:
    root = repo_dir()
    renderer = renderer_profile(profile)
    if not renderer["ok"]:
        return {"ok": False, "renderer": renderer}
    if dry_run:
        return _build_renderer_image(renderer, root, dry_run=True)
    with _renderer_build_lock(renderer["image"]):
        return _build_renderer_image(renderer, root, dry_run=False)


def _inspect_renderer_image(renderer: dict[str, Any], root: pathlib.Path) -> dict[str, Any]:
    inspect = run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", renderer["image"]],
        cwd=root,
        timeout=60,
    )
    output = str(inspect.get("stdout") or "").strip()
    image_id = output if inspect["returncode"] == 0 and DOCKER_IMAGE_ID_RE.fullmatch(output) else None
    return {**inspect, "image_id": image_id}


def ensure_renderer_image(profile: str = DEFAULT_COMPATIBILITY) -> dict[str, Any]:
    root = repo_dir()
    renderer = renderer_profile(profile)
    if not renderer["ok"]:
        return {"ok": False, "renderer": renderer}
    with _renderer_build_lock(renderer["image"]):
        inspect = _inspect_renderer_image(renderer, root)
        if inspect["image_id"]:
            return {
                "ok": True,
                "renderer": renderer,
                "inspect": inspect,
                "image_id": inspect["image_id"],
                "built": False,
            }
        build = _build_renderer_image(renderer, root, dry_run=False)
        if not build.get("ok", False):
            return {"ok": False, "renderer": renderer, "inspect": inspect, "build": build, "built": True}
        reinspect = _inspect_renderer_image(renderer, root)
        return {
            "ok": bool(reinspect["image_id"]),
            "renderer": renderer,
            "inspect": reinspect,
            "image_id": reinspect["image_id"],
            "build": build,
            "built": True,
        }


def path_within(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_project_path(root: pathlib.Path, raw: str, *, must_exist: bool = False) -> pathlib.Path:
    candidate = pathlib.Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = pathlib.Path(os.path.abspath(candidate))
    if not path_within(candidate, root):
        raise ValueError(f"path is outside the project root: {raw}")
    reject_symlink_components(candidate, root)
    if must_exist and not candidate.is_file():
        raise FileNotFoundError(f"diagram source not found: {raw}")
    if not must_exist and candidate.exists() and not candidate.is_file():
        raise ValueError(f"output path is not a regular file: {raw}")
    return candidate


def reject_symlink_components(path: pathlib.Path, root: pathlib.Path) -> None:
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"generated path contains a symlink: {rel(current, root)}")


def _open_confined_parent(
    root: pathlib.Path,
    path: pathlib.Path,
    *,
    create: bool = False,
) -> tuple[int, str]:
    parts = path.relative_to(root).parts
    if not parts:
        raise ValueError("path must name a file inside the project root")

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root, directory_flags)
    try:
        for part in parts[:-1]:
            if create:
                try:
                    os.mkdir(part, mode=0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child_descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child_descriptor
        return descriptor, parts[-1]
    except Exception:
        os.close(descriptor)
        raise


def _open_confined_file(root: pathlib.Path, path: pathlib.Path) -> int:
    parent_descriptor, name = _open_confined_parent(root, path)
    try:
        return os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_descriptor)
    finally:
        os.close(parent_descriptor)


def _ensure_confined_directory(root: pathlib.Path, path: pathlib.Path) -> None:
    try:
        parent_descriptor, name = _open_confined_parent(root, path, create=True)
    except OSError as exc:
        raise ValueError(f"generated path contains a symlink or unsafe directory: {rel(path, root)}") from exc
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        try:
            os.mkdir(name, mode=0o755, dir_fd=parent_descriptor)
        except FileExistsError:
            pass
        descriptor = os.open(name, directory_flags, dir_fd=parent_descriptor)
        os.close(descriptor)
    except OSError as exc:
        raise ValueError(f"generated path contains a symlink or unsafe directory: {rel(path, root)}") from exc
    finally:
        os.close(parent_descriptor)


def _read_bounded_regular_file(
    root: pathlib.Path,
    path: pathlib.Path,
    *,
    max_bytes: int,
    description: str,
) -> tuple[bytes, os.stat_result]:
    try:
        descriptor = _open_confined_file(root, path)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ValueError(f"{description} could not be opened without following symlinks: {rel(path, root)}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{description} is not a regular file: {rel(path, root)}")
        if before.st_size > max_bytes:
            raise ValueError(f"{description} exceeds the {max_bytes}-byte limit: {rel(path, root)}")
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(content) > max_bytes:
            raise ValueError(f"{description} exceeds the {max_bytes}-byte limit: {rel(path, root)}")
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or len(content) != after.st_size:
            raise ValueError(f"{description} changed while it was being checked: {rel(path, root)}")
        return content, after
    finally:
        os.close(descriptor)


def _discover_project_diagrams(root: pathlib.Path) -> list[pathlib.Path]:
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    root_descriptor = os.open(root, directory_flags)
    paths: list[pathlib.Path] = []
    entries_seen = 0

    def walk(directory_descriptor: int, relative: pathlib.Path, depth: int) -> None:
        nonlocal entries_seen
        if depth > MAX_PROJECT_SCAN_DEPTH:
            raise ValueError(f"diagram source scan exceeds the {MAX_PROJECT_SCAN_DEPTH}-level limit")
        with os.scandir(directory_descriptor) as entries:
            names = sorted(entry.name for entry in entries)
        for name in names:
            entries_seen += 1
            if entries_seen > MAX_PROJECT_SCAN_ENTRIES:
                raise ValueError(f"diagram source scan exceeds the {MAX_PROJECT_SCAN_ENTRIES}-entry limit")
            candidate_relative = relative / name
            try:
                metadata = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
            except OSError as exc:
                raise ValueError(f"diagram source path changed during inspection: {candidate_relative.as_posix()}") from exc
            if stat.S_ISLNK(metadata.st_mode):
                if pathlib.Path(name).suffix.lower() in DIAGRAM_SOURCE_SUFFIXES:
                    raise ValueError(f"diagram source must not be a symlink: {candidate_relative.as_posix()}")
                continue
            if stat.S_ISDIR(metadata.st_mode):
                try:
                    child_descriptor = os.open(name, directory_flags, dir_fd=directory_descriptor)
                except OSError as exc:
                    raise ValueError(f"diagram source directory is unsafe: {candidate_relative.as_posix()}") from exc
                try:
                    walk(child_descriptor, candidate_relative, depth + 1)
                finally:
                    os.close(child_descriptor)
                continue
            if pathlib.Path(name).suffix.lower() not in DIAGRAM_SOURCE_SUFFIXES:
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError(f"diagram source is not a regular file: {candidate_relative.as_posix()}")
            paths.append(root / candidate_relative)
            if len(paths) > MAX_PROJECT_DIAGRAMS:
                raise ValueError(f"diagram source inventory exceeds the {MAX_PROJECT_DIAGRAMS}-file limit")

    try:
        for root_name in UNALTRAWEB_DIAGRAM_ROOTS:
            try:
                directory_descriptor = os.open(root_name, directory_flags, dir_fd=root_descriptor)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise ValueError(f"diagram source root is not a safe directory: {root_name}") from exc
            try:
                walk(directory_descriptor, pathlib.Path(root_name), 1)
            finally:
                os.close(directory_descriptor)
    finally:
        os.close(root_descriptor)
    return sorted(paths, key=lambda path: rel(path, root))


def _atomic_write_confined(root: pathlib.Path, path: pathlib.Path, content: bytes) -> None:
    parent_descriptor = -1
    descriptor = -1
    temporary_name = ""
    temporary_created = False
    try:
        parent_descriptor, name = _open_confined_parent(root, path, create=True)
        try:
            existing = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and not stat.S_ISREG(existing.st_mode):
            raise ValueError(f"receipt path is not a regular file: {rel(path, root)}")
        temporary_name = f".{name}.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        temporary_created = True
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), 0o644)
        os.replace(temporary_name, name, src_dir_fd=parent_descriptor, dst_dir_fd=parent_descriptor)
        temporary_created = False
        os.fsync(parent_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_created and parent_descriptor >= 0:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def _invalidate_project_receipt(root: pathlib.Path) -> dict[str, Any]:
    receipt = root / PROJECT_RECEIPT_PATH
    parent_descriptor = -1
    try:
        parent_descriptor, name = _open_confined_parent(root, receipt)
        try:
            metadata = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return {"path": PROJECT_RECEIPT_PATH.as_posix(), "removed": False}
        if stat.S_ISDIR(metadata.st_mode):
            raise ValueError("receipt path is a directory")
        os.unlink(name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
        return {"path": PROJECT_RECEIPT_PATH.as_posix(), "removed": True}
    except FileNotFoundError:
        return {"path": PROJECT_RECEIPT_PATH.as_posix(), "removed": False}
    except (OSError, ValueError) as exc:
        return {"path": PROJECT_RECEIPT_PATH.as_posix(), "removed": False, "error": str(exc)}
    finally:
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def diagram_engine(input_path: pathlib.Path, requested: str = "auto") -> str:
    requested = (requested or "auto").strip().lower()
    if requested in {"mermaid", "plantuml"}:
        return requested
    suffix = input_path.suffix.lower()
    if suffix in {".mmd", ".mermaid"}:
        return "mermaid"
    if suffix in {".puml", ".plantuml", ".uml"}:
        return "plantuml"
    raise ValueError("engine must be mermaid or plantuml for sources without a known extension")


def diagram_engine_from_text(diagram_text: str, requested: str = "auto") -> str:
    requested = (requested or "auto").strip().lower()
    if requested in {"mermaid", "plantuml"}:
        return requested

    lines = [line.strip() for line in diagram_text.splitlines()]
    significant = [line for line in lines if line and not line.startswith(("%", "%%", "'", "//"))]
    first = significant[0].lower() if significant else ""
    if first.startswith("@start"):
        return "plantuml"
    if first.split(None, 1)[0] in MERMAID_TEXT_STARTS:
        return "mermaid"
    raise ValueError("engine must be mermaid or plantuml when diagram text cannot be inferred")


def resolve_style_name(engine: str, style: str) -> str:
    if not STYLE_NAME_RE.fullmatch(style):
        raise ValueError("style or family must be a simple ASCII name")
    root = repo_dir().resolve()
    if engine == "mermaid":
        style_root = (root / "styles" / "mermaid").resolve()
        if not path_within(style_root, root):
            raise ValueError("Mermaid style directory is outside the package root")
        candidates = [style, f"{style.removesuffix('-mermaid')}-mermaid"]
        for candidate in candidates:
            path = (style_root / f"{candidate}.json").resolve()
            if path_within(path, style_root) and path.is_file():
                return candidate
    elif engine == "plantuml":
        style_root = (root / "styles" / "plantuml").resolve()
        if not path_within(style_root, root):
            raise ValueError("PlantUML style directory is outside the package root")
        candidates = [style, f"{style.removesuffix('-plantuml')}-plantuml"]
        for candidate in candidates:
            path = (style_root / f"{candidate}.puml").resolve()
            if path_within(path, style_root) and path.is_file():
                return candidate
    else:
        raise ValueError("engine must be mermaid or plantuml")
    raise FileNotFoundError(f"unknown {engine} style or family: {style}")


def renderer_user() -> str:
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        uid = os.getuid()
        if uid > 0:
            return f"{uid}:{os.getgid()}"
    return RENDERER_FALLBACK_UID_GID


def renderer_workspace_id(root: pathlib.Path) -> str:
    return hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]


def renderer_container_name(root: pathlib.Path) -> str:
    return f"diavisuals-{renderer_workspace_id(root)}-{uuid.uuid4().hex[:12]}"


def _docker_mount_spec(*fields: str) -> str:
    encoded = io.StringIO()
    csv.writer(encoded, lineterminator="").writerow(fields)
    return encoded.getvalue()


def _copy_staged_asset(source: pathlib.Path, destination: pathlib.Path, asset_root: pathlib.Path, *, executable: bool = False) -> None:
    resolved = source.resolve(strict=True)
    if not path_within(resolved, asset_root) or not resolved.is_file():
        raise ValueError(f"renderer asset is outside the package root: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(resolved, destination)
    destination.chmod(0o555 if executable else 0o444)


def stage_renderer_bundle(
    stage_root: pathlib.Path,
    *,
    source: pathlib.Path,
    source_root: pathlib.Path | None = None,
    source_data: bytes | None,
    engine: str,
    style_name: str,
    output_format: str,
) -> dict[str, pathlib.Path]:
    asset_root = repo_dir().resolve()
    bundle = stage_root / "bundle"
    result = stage_root / "result"
    bundle.mkdir(mode=0o755)
    result.mkdir(mode=0o733)

    source_suffix = ".mmd" if engine == "mermaid" else ".puml"
    staged_source = bundle / "input" / f"source{source_suffix}"
    staged_source.parent.mkdir(parents=True)
    if source_data is None:
        if source_root is None:
            raise ValueError("source_root is required for file rendering")
        source_descriptor = _open_confined_file(source_root, source)
        try:
            metadata = os.fstat(source_descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError(f"diagram source is not a regular file: {source}")
            if metadata.st_size > MAX_DIAGRAM_SOURCE_BYTES:
                raise ValueError(
                    f"diagram source exceeds the {MAX_DIAGRAM_SOURCE_BYTES}-byte limit"
                )
            with os.fdopen(source_descriptor, "rb", closefd=False) as source_handle:
                source_bytes = source_handle.read(MAX_DIAGRAM_SOURCE_BYTES + 1)
            if len(source_bytes) > MAX_DIAGRAM_SOURCE_BYTES:
                raise ValueError(
                    f"diagram source exceeds the {MAX_DIAGRAM_SOURCE_BYTES}-byte limit"
                )
            staged_source.write_bytes(source_bytes)
        finally:
            os.close(source_descriptor)
    else:
        if len(source_data) > MAX_DIAGRAM_SOURCE_BYTES:
            raise ValueError(
                f"diagram source exceeds the {MAX_DIAGRAM_SOURCE_BYTES}-byte limit"
            )
        staged_source.write_bytes(source_data)
    staged_source.chmod(0o444)

    tool_names = ["render-one.sh", "style-diagram-source.sh", "resolve-style-name.sh"]
    if engine == "mermaid" and output_format == "svg":
        tool_names.append("normalize-mermaid-svg.py")
    for tool_name in tool_names:
        _copy_staged_asset(
            asset_root / "tools" / tool_name,
            bundle / "tools" / tool_name,
            asset_root,
            executable=tool_name.endswith(".sh"),
        )

    if engine == "mermaid":
        style_root = asset_root / "styles" / "mermaid"
        _copy_staged_asset(
            style_root / f"{style_name}.json",
            bundle / "styles" / "mermaid" / f"{style_name}.json",
            asset_root,
        )
        override_root = style_root / style_name
        for override in sorted(override_root.glob("*.mmd")):
            _copy_staged_asset(
                override,
                bundle / "styles" / "mermaid" / style_name / override.name,
                asset_root,
            )
    else:
        style_root = asset_root / "styles" / "plantuml"
        _copy_staged_asset(
            style_root / f"{style_name}.puml",
            bundle / "styles" / "plantuml" / f"{style_name}.puml",
            asset_root,
        )
        override_root = style_root / style_name
        for override in sorted(override_root.glob("*.puml")):
            _copy_staged_asset(
                override,
                bundle / "styles" / "plantuml" / style_name / override.name,
                asset_root,
            )

    for directory in sorted((path for path in bundle.rglob("*") if path.is_dir()), reverse=True):
        directory.chmod(0o555)
    bundle.chmod(0o555)
    return {
        "bundle": bundle,
        "result": result,
        "cidfile": stage_root / "container.cid",
        "artifact": result / f"artifact.{output_format}",
    }


def build_renderer_command(
    *,
    root: pathlib.Path,
    renderer: dict[str, Any],
    engine: str,
    style_name: str,
    output_format: str,
    bundle: pathlib.Path,
    result: pathlib.Path,
    cidfile: pathlib.Path,
    container_name: str,
) -> list[str]:
    workspace_id = renderer_workspace_id(root)
    return [
        "docker",
        "run",
        "--rm",
        "--cidfile",
        str(cidfile),
        "--name",
        container_name,
        "--label",
        RENDERER_CONTAINER_LABEL,
        "--label",
        f"{RENDERER_WORKSPACE_LABEL}={workspace_id}",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges=true",
        "--user",
        renderer_user(),
        "--memory",
        RENDERER_MEMORY,
        "--memory-swap",
        RENDERER_MEMORY,
        "--cpus",
        RENDERER_CPUS,
        "--pids-limit",
        RENDERER_PIDS_LIMIT,
        "--ulimit",
        f"nofile={RENDERER_NOFILE_LIMIT}",
        "--ulimit",
        f"fsize={RENDERER_FSIZE_LIMIT}",
        "--tmpfs",
        RENDERER_TMPFS,
        "--mount",
        _docker_mount_spec("type=bind", f"source={bundle}", "target=/diavisuals", "readonly"),
        "--mount",
        _docker_mount_spec("type=bind", f"source={result}", "target=/output"),
        "--workdir",
        "/tmp",
        "-e",
        "HOME=/tmp/home",
        "-e",
        "XDG_CACHE_HOME=/tmp/cache",
        "-e",
        "JAVA_TOOL_OPTIONS=-Duser.home=/tmp/home",
        "-e",
        "PLANTUML_SECURITY_PROFILE=SANDBOX",
        renderer["image"],
        "bash",
        "/diavisuals/tools/render-one.sh",
        engine,
        style_name,
        output_format,
    ]


def _remove_renderer_container(container_name: str) -> dict[str, Any]:
    remove = run(["docker", "container", "rm", "--force", container_name], timeout=30)
    remove_error = str(remove.get("stderr") or "")
    if remove["returncode"] == 0 or "No such container" in remove_error:
        return {"ok": True, "container": container_name, "remove": remove}

    inspect = run(["docker", "container", "inspect", container_name], timeout=30)
    inspect_error = str(inspect.get("stderr") or "")
    absent = inspect["returncode"] != 0 and (
        "No such object" in inspect_error or "No such container" in inspect_error
    )
    return {
        "ok": absent,
        "container": container_name,
        "remove": remove,
        "inspect": inspect,
    }


def _run_renderer(
    command: list[str],
    *,
    container_name: str,
    cwd: pathlib.Path,
    timeout: float = RENDER_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()

    def drain(stream: Any, buffer: bytearray) -> None:
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                remaining = MAX_RENDER_DIAGNOSTIC_BYTES - len(buffer)
                if remaining > 0:
                    buffer.extend(chunk[:remaining])
        finally:
            stream.close()

    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        cleanup = _remove_renderer_container(container_name)
        return {
            "command": command,
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc)[:MAX_RENDER_DIAGNOSTIC_BYTES],
            "timed_out": False,
            "cleanup": cleanup,
        }

    assert process.stdout is not None
    assert process.stderr is not None
    threads = [
        threading.Thread(target=drain, args=(process.stdout, stdout_buffer), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, stderr_buffer), daemon=True),
    ]
    for thread in threads:
        thread.start()

    timed_out = False
    cleanup: dict[str, Any]
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            process.kill()
        except ProcessLookupError:
            pass
        process.wait()
    finally:
        cleanup = _remove_renderer_container(container_name)
        for thread in threads:
            thread.join(timeout=5)

    stderr = bytes(stderr_buffer).decode("utf-8", errors="replace")
    if timed_out:
        timeout_message = f"\nrenderer timed out after {timeout} seconds"
        stderr = (stderr + timeout_message)[:MAX_RENDER_DIAGNOSTIC_BYTES]
    if not cleanup["ok"]:
        cleanup_message = "\nrenderer container cleanup could not be verified"
        stderr = (stderr + cleanup_message)[:MAX_RENDER_DIAGNOSTIC_BYTES]
    return {
        "command": command,
        "returncode": process.returncode,
        "stdout": bytes(stdout_buffer).decode("utf-8", errors="replace"),
        "stderr": stderr,
        "timed_out": timed_out,
        "cleanup": cleanup,
    }


def _validate_artifact_descriptor(
    descriptor: int,
    output: pathlib.Path,
    output_format: str,
) -> dict[str, Any]:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        return {"ok": False, "path": str(output), "reason": "output is not a regular file"}
    size = metadata.st_size
    if size <= 0:
        return {"ok": False, "path": str(output), "bytes": size, "reason": "output file is empty"}
    if size > MAX_RENDERED_ARTIFACT_BYTES:
        return {
            "ok": False,
            "path": str(output),
            "bytes": size,
            "reason": f"output exceeds the {MAX_RENDERED_ARTIFACT_BYTES}-byte limit",
        }

    os.lseek(descriptor, 0, os.SEEK_SET)
    header = os.read(descriptor, 4096)
    if output_format == "pdf" and not header.startswith(b"%PDF-"):
        return {"ok": False, "path": str(output), "bytes": size, "reason": "output is not a PDF"}
    if output_format == "png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
        return {"ok": False, "path": str(output), "bytes": size, "reason": "output is not a PNG"}
    if output_format == "svg" and b"<svg" not in header.lower():
        return {"ok": False, "path": str(output), "bytes": size, "reason": "output is not an SVG"}
    return {"ok": True, "path": str(output), "bytes": size, "format": output_format}


def validate_rendered_artifact(output: pathlib.Path, output_format: str) -> dict[str, Any]:
    try:
        descriptor = os.open(output, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except (FileNotFoundError, OSError) as exc:
        reason = "output file was not created" if isinstance(exc, FileNotFoundError) else "output is not a regular file"
        return {"ok": False, "path": str(output), "reason": reason}
    try:
        return _validate_artifact_descriptor(descriptor, output, output_format)
    finally:
        os.close(descriptor)


def atomic_publish_artifact(
    staged: pathlib.Path,
    output: pathlib.Path,
    root: pathlib.Path,
    output_format: str,
) -> dict[str, Any]:
    staged_descriptor = os.open(staged, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    parent_descriptor = -1
    descriptor = -1
    temporary_created = False
    try:
        staged_check = _validate_artifact_descriptor(staged_descriptor, staged, output_format)
        if not staged_check["ok"]:
            return staged_check

        reject_symlink_components(output, root)
        parent_descriptor, output_name = _open_confined_parent(root, output, create=True)
        temporary_name = f".{output_name}.{uuid.uuid4().hex}.tmp"
        try:
            metadata = os.stat(output_name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            metadata = None
        if metadata is not None and not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"output path is not a regular file: {rel(output, root)}")

        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        temporary_created = True
        os.lseek(staged_descriptor, 0, os.SEEK_SET)
        destination_handle = os.fdopen(descriptor, "wb")
        descriptor = -1
        with destination_handle as destination, os.fdopen(
            staged_descriptor, "rb", closefd=False
        ) as source_handle:
            shutil.copyfileobj(source_handle, destination)
            destination.flush()
            os.fsync(destination.fileno())
            os.fchmod(destination.fileno(), 0o644)
        os.replace(
            temporary_name,
            output_name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        temporary_created = False
        os.fsync(parent_descriptor)

        published_descriptor = os.open(
            output_name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        try:
            return _validate_artifact_descriptor(published_descriptor, output, output_format)
        finally:
            os.close(published_descriptor)
    finally:
        os.close(staged_descriptor)
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_created and parent_descriptor >= 0:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def resolve_output_format(output: pathlib.Path | None, requested: str | None) -> str:
    requested_format = (requested or "").strip().lower()
    suffix_format = output.suffix.lstrip(".") if output and output.suffix else ""
    if requested_format and requested_format not in OUTPUT_MIME_TYPES:
        raise ValueError("output_format must be svg, png, or pdf")
    if output is not None and not suffix_format:
        raise ValueError("output path must end with .svg, .png, or .pdf")
    if suffix_format != suffix_format.lower():
        raise ValueError("output path extension must be lowercase")
    if suffix_format and suffix_format not in OUTPUT_MIME_TYPES:
        raise ValueError("output path extension must be .svg, .png, or .pdf")
    output_format = requested_format or suffix_format or "svg"
    if suffix_format and suffix_format != output_format:
        raise ValueError(f"output path extension .{suffix_format} does not match output_format {output_format}")
    return output_format


def render_diagram(
    project_root: str | pathlib.Path,
    *,
    input_path: str,
    output_path: str,
    engine: str = "auto",
    family: str = DEFAULT_FAMILY,
    style: str | None = None,
    profile: str = DEFAULT_COMPATIBILITY,
    output_format: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    root = pathlib.Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"project root not found: {project_root}")
    source = resolve_project_path(root, input_path)
    output = resolve_project_path(root, output_path)
    try:
        source_descriptor = _open_confined_file(root, source)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"diagram source not found: {input_path}") from exc
    try:
        source_metadata = os.fstat(source_descriptor)
    finally:
        os.close(source_descriptor)
    if not stat.S_ISREG(source_metadata.st_mode):
        raise ValueError(f"diagram source is not a regular file: {input_path}")
    if source_metadata.st_size > MAX_DIAGRAM_SOURCE_BYTES:
        raise ValueError(f"diagram source exceeds the {MAX_DIAGRAM_SOURCE_BYTES}-byte limit")
    resolved_engine = diagram_engine(source, engine)
    if source == output:
        raise ValueError("input and output paths must be different")
    output_format = resolve_output_format(output, output_format)

    return _render_diagram_source(
        root,
        source=source,
        source_data=None,
        output=output,
        resolved_engine=resolved_engine,
        family=family,
        style=style,
        profile=profile,
        output_format=output_format,
        dry_run=dry_run,
    )


def _render_diagram_source(
    root: pathlib.Path,
    *,
    source: pathlib.Path,
    source_data: bytes | None,
    output: pathlib.Path,
    resolved_engine: str,
    family: str,
    style: str | None,
    profile: str,
    output_format: str,
    dry_run: bool,
) -> dict[str, Any]:

    renderer = renderer_profile(profile)
    if not renderer["ok"]:
        return {"ok": False, "renderer": renderer}

    style_query = (style or "").strip() or family
    style_name = resolve_style_name(resolved_engine, style_query)
    private_stage = pathlib.Path("/tmp/diavisuals-render-PRIVATE")
    container_name = renderer_container_name(root)
    command = build_renderer_command(
        root=root,
        renderer=renderer,
        engine=resolved_engine,
        style_name=style_name,
        output_format=output_format,
        bundle=private_stage / "bundle",
        result=private_stage / "result",
        cidfile=private_stage / "container.cid",
        container_name=container_name,
    )
    payload: dict[str, Any] = {
        "ok": True,
        "project": str(root),
        "engine": resolved_engine,
        "family": family,
        "style": style_name,
        "style_requested": style_query,
        "profile": profile.removesuffix(".env"),
        "input": rel(source, root),
        "output": rel(output, root),
        "output_format": output_format,
        "staging": "private",
        "renderer": renderer,
        "command": command,
    }
    if dry_run:
        payload["dry_run"] = True
        return payload

    image = ensure_renderer_image(profile)
    if not image.get("ok"):
        return {**payload, "ok": False, "image": image}
    image_id = str(image.get("image_id") or "")
    if not DOCKER_IMAGE_ID_RE.fullmatch(image_id):
        return {**payload, "ok": False, "image": image, "error": "renderer did not resolve to an immutable image ID"}

    with tempfile.TemporaryDirectory(prefix="diavisuals-render-") as temporary_root:
        stage = stage_renderer_bundle(
            pathlib.Path(temporary_root),
            source=source,
            source_root=root,
            source_data=source_data,
            engine=resolved_engine,
            style_name=style_name,
            output_format=output_format,
        )
        container_name = renderer_container_name(root)
        command = build_renderer_command(
            root=root,
            renderer={**renderer, "image": image_id},
            engine=resolved_engine,
            style_name=style_name,
            output_format=output_format,
            bundle=stage["bundle"],
            result=stage["result"],
            cidfile=stage["cidfile"],
            container_name=container_name,
        )
        payload["command"] = command
        completed = _run_renderer(
            command,
            container_name=container_name,
            cwd=root,
            timeout=RENDER_TIMEOUT_SECONDS,
        )
        artifact_check = validate_rendered_artifact(stage["artifact"], output_format)
        if completed["returncode"] == 0 and completed["cleanup"]["ok"] and artifact_check["ok"]:
            try:
                artifact_check = atomic_publish_artifact(stage["artifact"], output, root, output_format)
            except (OSError, ValueError) as exc:
                artifact_check = {
                    "ok": False,
                    "path": str(output),
                    "reason": f"failed to publish output atomically: {exc}",
                }
    payload.update({
        "image": image,
        "result": completed,
        "artifact_check": artifact_check,
        "ok": completed["returncode"] == 0 and completed["cleanup"]["ok"] and artifact_check["ok"],
    })
    return payload


def diagram_artifact_payload(output: pathlib.Path, root: pathlib.Path, output_format: str, *, include_data: bool) -> dict[str, Any]:
    reject_symlink_components(output, root)
    payload: dict[str, Any] = {
        "path": rel(output, root),
        "mime_type": OUTPUT_MIME_TYPES.get(output_format, "application/octet-stream"),
        "format": output_format,
        "exists": False,
    }
    try:
        descriptor = _open_confined_file(root, output)
    except FileNotFoundError:
        return payload
    except OSError as exc:
        raise ValueError(f"generated path could not be opened safely: {rel(output, root)}") from exc

    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        os.close(descriptor)
        return payload
    payload["exists"] = True

    size = metadata.st_size
    payload["bytes"] = size
    if not include_data:
        os.close(descriptor)
        return payload
    if size > MAX_INLINE_ARTIFACT_BYTES:
        payload.update({
            "data_included": False,
            "reason": f"artifact exceeds the {MAX_INLINE_ARTIFACT_BYTES}-byte inline response limit",
        })
        os.close(descriptor)
        return payload
    try:
        data = os.read(descriptor, MAX_INLINE_ARTIFACT_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(data) > MAX_INLINE_ARTIFACT_BYTES:
        payload.update({
            "data_included": False,
            "reason": f"artifact exceeds the {MAX_INLINE_ARTIFACT_BYTES}-byte inline response limit",
        })
        return payload
    payload["data_included"] = True
    if output_format == "svg":
        payload["svg"] = data.decode("utf-8", errors="replace")
    else:
        payload["data_base64"] = base64.b64encode(data).decode("ascii")
    return payload


def render_diagram_text(
    project_root: str | pathlib.Path,
    *,
    diagram_text: str,
    output_path: str | None = None,
    engine: str = "auto",
    family: str = DEFAULT_FAMILY,
    style: str | None = None,
    profile: str = DEFAULT_COMPATIBILITY,
    output_format: str = "",
    include_data: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = pathlib.Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"project root not found: {project_root}")
    requested_output = resolve_project_path(root, output_path) if output_path else None
    output_format = resolve_output_format(requested_output, output_format)
    resolved_engine = diagram_engine_from_text(diagram_text, engine)
    source_suffix = ".mmd" if resolved_engine == "mermaid" else ".puml"
    digest_values = {
        "engine": resolved_engine,
        "family": family,
        "style": style or "",
        "profile": profile,
        "output_format": output_format,
        "diagram_text": diagram_text,
    }
    digest = hashlib.sha256(json.dumps(digest_values, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    source = root / ".cache" / "diavisuals" / "inline" / resolved_engine / f"{digest}{source_suffix}"
    default_output = root / ".cache" / "diavisuals" / "outputs" / resolved_engine / f"{digest}.{output_format}"
    output = requested_output or resolve_project_path(root, rel(default_output, root))
    source_data = (diagram_text.rstrip() + "\n").encode("utf-8")
    if len(source_data) > MAX_DIAGRAM_SOURCE_BYTES:
        raise ValueError(
            f"diagram source exceeds the {MAX_DIAGRAM_SOURCE_BYTES}-byte limit"
        )

    rendered = _render_diagram_source(
        root,
        source=source,
        source_data=source_data,
        output=output,
        resolved_engine=resolved_engine,
        family=family,
        style=style,
        profile=profile,
        output_format=output_format,
        dry_run=dry_run,
    )
    artifact = (
        diagram_artifact_payload(output, root, output_format, include_data=include_data)
        if not dry_run and rendered.get("ok")
        else {
            "path": rel(output, root),
            "mime_type": OUTPUT_MIME_TYPES[output_format],
            "format": output_format,
            "exists": False,
        }
    )
    payload = {
        **rendered,
        "inline": True,
        "input_text_sha256": hashlib.sha256(diagram_text.encode("utf-8")).hexdigest(),
        "input_source": rel(source, root),
        "artifact": artifact,
    }
    return payload


def style_family_item(root: pathlib.Path, family: str) -> dict[str, Any]:
    mermaid_name = f"{family}-mermaid"
    plantuml_name = f"{family}-plantuml"
    mermaid_base = root / "styles" / "mermaid" / f"{mermaid_name}.json"
    mermaid_overrides = root / "styles" / "mermaid" / mermaid_name
    plantuml_base = root / "styles" / "plantuml" / f"{plantuml_name}.puml"
    plantuml_overrides = root / "styles" / "plantuml" / plantuml_name
    examples = root / "examples" / family
    tokens = root / "tokens" / f"{family}.yml"
    return {
        "family": family,
        "ok": mermaid_base.is_file() and plantuml_base.is_file(),
        "tokens": {"path": rel(tokens, root), "exists": tokens.is_file()},
        "mermaid": {
            "name": mermaid_name,
            "base": rel(mermaid_base, root),
            "base_exists": mermaid_base.is_file(),
            "overrides": [rel(path, root) for path in sorted(mermaid_overrides.glob("*.mmd"))] if mermaid_overrides.is_dir() else [],
            "examples": [rel(path, root) for path in sorted((examples / "mermaid").glob("*.mmd"))] if (examples / "mermaid").is_dir() else [],
        },
        "plantuml": {
            "name": plantuml_name,
            "base": rel(plantuml_base, root),
            "base_exists": plantuml_base.is_file(),
            "overrides": [rel(path, root) for path in sorted(plantuml_overrides.glob("*.puml"))] if plantuml_overrides.is_dir() else [],
            "examples": [rel(path, root) for path in sorted((examples / "plantuml").glob("*.puml"))] if (examples / "plantuml").is_dir() else [],
        },
    }


def style_inventory() -> dict[str, Any]:
    root = repo_dir()
    families: list[str] = []
    for style in sorted((root / "styles" / "mermaid").glob("*-mermaid.json")):
        family = style.name.removesuffix("-mermaid.json")
        if (root / "styles" / "plantuml" / f"{family}-plantuml.puml").is_file():
            families.append(family)
    items = [style_family_item(root, family) for family in families]
    return {
        "ok": bool(items) and all(item["ok"] for item in items),
        "repo": str(root),
        "git_head": git_head(root),
        "git_tag": git_tag(root),
        "families": items,
        "count": len(items),
    }


def compatibility_status(profile: str = DEFAULT_COMPATIBILITY) -> dict[str, Any]:
    root = repo_dir()
    compat_root = root / "compat"
    profile_path = pathlib.Path(profile)
    requested = profile_path.stem if profile_path.suffix == ".env" else profile_path.name
    profile_file = compat_root / f"{requested}.env"
    profiles = []
    for path in sorted(compat_root.glob("*.env")):
        values = parse_env(path)
        profile_status = values.get("DIAVISUALS_PROFILE_STATUS") or "unspecified"
        profiles.append(
            {
                "name": path.stem,
                "path": rel(path, root),
                "mermaid": values.get("MERMAID_CLI_VERSION"),
                "plantuml": values.get("PLANTUML_VERSION"),
                "family": values.get("DIAVISUALS_FAMILY"),
                "status": profile_status,
                "renderable": profile_status == "supported-renderer",
                "mermaid_types": values.get("MERMAID_TYPES"),
                "plantuml_types": values.get("PLANTUML_TYPES"),
            }
        )
    values = parse_env(profile_file)
    profile_status = values.get("DIAVISUALS_PROFILE_STATUS") or "unspecified"
    return {
        "ok": profile_file.is_file(),
        "requested": requested,
        "requested_path": rel(profile_file, root),
        "status": profile_status,
        "renderable": profile_status == "supported-renderer",
        "values": values,
        "profiles": profiles,
    }


def token_palette(root: pathlib.Path, family: str) -> dict[str, Any]:
    path = root / "tokens" / f"{family}.yml"
    if not path.is_file():
        return {
            "path": rel(path, root),
            "exists": False,
            "hex_colors": [],
            "hex_color_count": 0,
        }
    colors = sorted({match.group(0).upper() for match in HEX_COLOR_RE.finditer(path.read_text(encoding="utf-8"))})
    return {
        "path": rel(path, root),
        "exists": True,
        "hex_colors": colors,
        "hex_color_count": len(colors),
    }


def gallery_status(profile: str = DEFAULT_COMPATIBILITY, family: str = DEFAULT_FAMILY) -> dict[str, Any]:
    root = repo_dir()
    requested = profile.removesuffix(".env")
    gallery_root = root / "docs" / "gallery" / family / requested
    manifest = gallery_root / "manifest.csv"
    rows: list[dict[str, Any]] = []
    engines: dict[str, dict[str, Any]] = {}
    missing_outputs: list[str] = []
    non_rendered: list[dict[str, str]] = []

    if manifest.is_file():
        with manifest.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                engine = str(row.get("engine") or "")
                diagram_type = str(row.get("type") or "")
                status = str(row.get("status") or "")
                output = str(row.get("output") or "")
                output_path = root / output
                exists = output_path.is_file()
                if status != "rendered":
                    non_rendered.append({"engine": engine, "type": diagram_type, "status": status})
                if status == "rendered" and not exists:
                    missing_outputs.append(output)
                rows.append(
                    {
                        "engine": engine,
                        "type": diagram_type,
                        "status": status,
                        "output": output,
                        "exists": exists,
                    }
                )
                summary = engines.setdefault(
                    engine,
                    {
                        "rendered": 0,
                        "missing": 0,
                        "non_rendered": 0,
                        "types": [],
                    },
                )
                summary["types"].append(diagram_type)
                if status == "rendered" and exists:
                    summary["rendered"] += 1
                elif status == "rendered":
                    summary["missing"] += 1
                else:
                    summary["non_rendered"] += 1

    return {
        "ok": manifest.is_file() and not missing_outputs and not non_rendered,
        "profile": requested,
        "family": family,
        "gallery_root": rel(gallery_root, root),
        "manifest": {"path": rel(manifest, root), "exists": manifest.is_file()},
        "rendered_count": sum(1 for row in rows if row["status"] == "rendered" and row["exists"]),
        "row_count": len(rows),
        "engines": engines,
        "missing_outputs": missing_outputs,
        "non_rendered": non_rendered,
    }


def style_audit(profile: str = DEFAULT_COMPATIBILITY, family: str = DEFAULT_FAMILY) -> dict[str, Any]:
    root = repo_dir()
    inventory = style_inventory()
    compat = compatibility_status(profile)
    family_item = next((item for item in inventory["families"] if item["family"] == family), None)
    palette = token_palette(root, family)
    gallery = gallery_status(profile=profile, family=family)
    styles = {
        "family": family,
        "mermaid": f"{family}-mermaid",
        "plantuml": f"{family}-plantuml",
    }

    issues: list[str] = []
    if family_item is None:
        issues.append(f"missing style family: {family}")
    elif not family_item["ok"]:
        issues.append(f"incomplete style family: {family}")
    if not palette["exists"]:
        issues.append(f"missing token file: tokens/{family}.yml")
    if not compat["ok"]:
        issues.append(f"missing compatibility profile: {profile}")
    if not gallery["ok"]:
        issues.append(f"incomplete rendered gallery: {family}/{profile}")

    return {
        "ok": not issues,
        "issues": issues,
        "repo": str(root),
        "git_head": git_head(root),
        "git_tag": git_tag(root),
        "contract": {
            "source": "vendored-package-assets",
            "family": family,
            "compatibility": profile.removesuffix(".env"),
            "styles": styles,
        },
        "tokens": palette,
        "family": family_item,
        "compatibility": compat,
        "gallery": gallery,
    }


def check_styles(profile: str = DEFAULT_COMPATIBILITY, family: str = DEFAULT_FAMILY) -> dict[str, Any]:
    inventory = style_inventory()
    compat = compatibility_status(profile)
    family_item = next((item for item in inventory["families"] if item["family"] == family), None)
    issues: list[str] = []
    if family_item is None:
        issues.append(f"missing style family: {family}")
    elif not family_item["ok"]:
        issues.append(f"incomplete style family: {family}")
    if not compat["ok"]:
        issues.append(f"missing compatibility profile: {profile}")
    return {
        "ok": not issues,
        "issues": issues,
        "family": family_item,
        "compatibility": compat,
    }


def release_status(release: str = DEFAULT_RELEASE) -> dict[str, Any]:
    root = source_checkout()
    if root is None:
        return {
            "ok": release == DEFAULT_RELEASE,
            "source": "package",
            "requested": release,
            "current_tag": DEFAULT_RELEASE,
            "current_matches_release": release == DEFAULT_RELEASE,
        }
    tag_result = run(
        ["git", "-C", str(root), "rev-parse", "--verify", f"refs/tags/{release}^{{commit}}"],
        cwd=root,
    )
    current_tag = git_tag(root)
    status = run(["git", "-C", str(root), "status", "--porcelain"], cwd=root)
    requested_sha = str(tag_result["stdout"]).strip() if tag_result["returncode"] == 0 else None
    current_head = git_head(root)
    clean = status["returncode"] == 0 and not status["stdout"].strip()
    matches = current_tag == release and current_head == requested_sha
    return {
        "ok": release == DEFAULT_RELEASE and matches and clean,
        "source": "checkout",
        "requested": release,
        "requested_sha": requested_sha,
        "current_head": current_head,
        "current_tag": current_tag,
        "current_matches_release": matches,
        "clean": clean,
    }


def submodule_plan(
    project_root: str = ".",
    *,
    path: str = "docs/slides/resources/diavisuals",
    release: str = DEFAULT_RELEASE,
    remote: str = DEFAULT_REMOTE,
) -> dict[str, Any]:
    return {
        "ok": True,
        "project_root": project_root,
        "path": path,
        "release": release,
        "remote": remote,
        "commands": [
            ["git", "submodule", "add", remote, path],
            ["git", "-C", path, "checkout", release],
            ["git", "add", ".gitmodules", path],
        ],
    }


def update_factory(dry_run: bool = False) -> dict[str, Any]:
    root = source_checkout()
    if root is None:
        uv = shutil.which("uv")
        if not uv:
            return {
                "ok": False,
                "source": "package",
                "dry_run": dry_run,
                "message": "uv is required to update an installed diavisuals package",
            }
        command = [
            uv,
            "pip",
            "install",
            "--python",
            sys.executable,
            "--upgrade",
            "diavisuals[mcp]",
        ]
        if dry_run:
            return {
                "ok": True,
                "source": "package",
                "dry_run": True,
                "command": command,
            }
        result = run(command, cwd=pathlib.Path.cwd(), timeout=300)
        return {
            "ok": result["returncode"] == 0,
            "source": "package",
            "result": result,
        }
    if dry_run:
        return {
            "ok": True,
            "source": "checkout",
            "dry_run": True,
            "command": ["git", "-C", str(root), "pull", "--ff-only"],
            "repo": str(root),
        }
    status = run(["git", "-C", str(root), "status", "--porcelain"], cwd=root)
    if status["returncode"] != 0 or status["stdout"].strip():
        return {
            "ok": False,
            "message": "Refusing to update a dirty or unreadable diavisuals checkout.",
            "status": status,
        }
    result = run(["git", "-C", str(root), "pull", "--ff-only"], cwd=root, timeout=300)
    return {
        "ok": result["returncode"] == 0,
        "source": "checkout",
        "result": result,
        "git_head": git_head(root),
    }


def project_check(project_root: str | pathlib.Path = ".") -> dict[str, Any]:
    root = pathlib.Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"project root not found: {project_root}")
    receipt_path = root / PROJECT_RECEIPT_PATH
    base: dict[str, Any] = {
        "ok": False,
        "project": str(root),
        "sources_and_artifacts_read_only": True,
        "roots": list(UNALTRAWEB_DIAGRAM_ROOTS),
        "source_suffixes": sorted(DIAGRAM_SOURCE_SUFFIXES),
        "sources": [],
        "issues": [],
        "request_sha256": "",
        "inputs": [],
        "receipt": {"path": PROJECT_RECEIPT_PATH.as_posix(), "published": False},
    }
    try:
        sources = _discover_project_diagrams(root)
    except (OSError, UnicodeError, ValueError) as exc:
        invalidated = _invalidate_project_receipt(root)
        return {
            **base,
            "issues": [str(exc)],
            "receipt": {**base["receipt"], "invalidation": invalidated},
        }

    digest = hashlib.sha256()
    digest.update(PROJECT_RECEIPT_PREFIX)
    records: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    issues: list[str] = []
    for source in sources:
        source_name = rel(source, root)
        record: dict[str, Any] = {"source": source_name}
        try:
            source_data, source_metadata = _read_bounded_regular_file(
                root,
                source,
                max_bytes=MAX_DIAGRAM_SOURCE_BYTES,
                description="diagram source",
            )
            source_name_bytes = source_name.encode("utf-8")
            digest.update(len(source_name_bytes).to_bytes(8, "big"))
            digest.update(source_name_bytes)
            digest.update(len(source_data).to_bytes(8, "big"))
            digest.update(source_data)
            source_sha256 = hashlib.sha256(source_data).hexdigest()
            record["source_sha256"] = source_sha256

            edited = pathlib.Path(str(source) + ".edited.svg")
            generated = pathlib.Path(str(source) + ".svg")
            try:
                output_data, output_metadata = _read_bounded_regular_file(
                    root,
                    edited,
                    max_bytes=MAX_COMPANION_ARTIFACT_BYTES,
                    description="preferred diagram output",
                )
                output = edited
            except FileNotFoundError:
                output = generated
                try:
                    output_data, output_metadata = _read_bounded_regular_file(
                        root,
                        generated,
                        max_bytes=MAX_COMPANION_ARTIFACT_BYTES,
                        description="diagram output",
                    )
                except FileNotFoundError:
                    record.update({
                        "output": rel(generated, root),
                        "edited_override": False,
                        "state": "missing",
                    })
                    records.append(record)
                    issues.append(f"{source_name}: missing output {rel(generated, root)}")
                    continue
            output_name = rel(output, root)
            record.update({
                "output": output_name,
                "edited_override": output == edited,
            })
            if not output_data or b"<svg" not in output_data[:4096].lower():
                record["state"] = "invalid"
                records.append(record)
                issues.append(f"{source_name}: output is not an SVG: {output_name}")
                continue
            output_sha256 = hashlib.sha256(output_data).hexdigest()
            record["artifact_sha256"] = output_sha256
            if source_metadata.st_mtime_ns > output_metadata.st_mtime_ns:
                record["state"] = "stale"
                records.append(record)
                issues.append(f"{source_name}: stale output {output_name}")
                continue
            record["state"] = "fresh"
            records.append(record)
            snapshots.append({
                "source": source,
                "source_sha256": source_sha256,
                "output": output,
                "artifact_sha256": output_sha256,
            })
        except (OSError, UnicodeError, ValueError) as exc:
            record["state"] = "invalid"
            record["error"] = str(exc)
            records.append(record)
            issues.append(f"{source_name}: {exc}")

    base["sources"] = records
    base["issues"] = issues
    base["request_sha256"] = digest.hexdigest()
    if issues:
        invalidated = _invalidate_project_receipt(root)
        if invalidated.get("error"):
            base["issues"] = [*issues, f"receipt invalidation failed: {invalidated['error']}"]
        base["receipt"] = {**base["receipt"], "invalidation": invalidated}
        return base

    try:
        current_sources = _discover_project_diagrams(root)
        if current_sources != sources:
            raise ValueError("diagram source inventory changed while it was being checked")
        for snapshot in snapshots:
            source_data, source_metadata = _read_bounded_regular_file(
                root,
                snapshot["source"],
                max_bytes=MAX_DIAGRAM_SOURCE_BYTES,
                description="diagram source",
            )
            if hashlib.sha256(source_data).hexdigest() != snapshot["source_sha256"]:
                raise ValueError(f"diagram source changed while it was being checked: {rel(snapshot['source'], root)}")
            edited = pathlib.Path(str(snapshot["source"]) + ".edited.svg")
            generated = pathlib.Path(str(snapshot["source"]) + ".svg")
            try:
                output_data, output_metadata = _read_bounded_regular_file(
                    root,
                    edited,
                    max_bytes=MAX_COMPANION_ARTIFACT_BYTES,
                    description="preferred diagram output",
                )
                current_output = edited
            except FileNotFoundError:
                output_data, output_metadata = _read_bounded_regular_file(
                    root,
                    generated,
                    max_bytes=MAX_COMPANION_ARTIFACT_BYTES,
                    description="diagram output",
                )
                current_output = generated
            if current_output != snapshot["output"] or hashlib.sha256(output_data).hexdigest() != snapshot["artifact_sha256"]:
                raise ValueError(f"diagram output changed while it was being checked: {rel(current_output, root)}")
            if source_metadata.st_mtime_ns > output_metadata.st_mtime_ns:
                raise ValueError(f"diagram output became stale while it was being checked: {rel(current_output, root)}")

        artifacts = [
            {"path": rel(snapshot["output"], root), "sha256": snapshot["artifact_sha256"]}
            for snapshot in snapshots
        ]
        artifacts.sort(key=lambda item: item["path"])
        receipt = {
            "schema_version": 1,
            "provider": "diavisuals",
            "provider_version": __version__,
            "release": DEFAULT_RELEASE,
            "request_sha256": base["request_sha256"],
            "ok": True,
            "inputs": [],
            "artifacts": artifacts,
        }
        receipt_data = (json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        _atomic_write_confined(root, receipt_path, receipt_data)
    except (OSError, UnicodeError, ValueError) as exc:
        invalidated = _invalidate_project_receipt(root)
        publication_issues = [f"receipt publication failed: {exc}"]
        if invalidated.get("error"):
            publication_issues.append(f"receipt invalidation failed: {invalidated['error']}")
        base["issues"] = publication_issues
        base["receipt"] = {**base["receipt"], "invalidation": invalidated}
        return base

    base["ok"] = True
    base["receipt"] = {
        "path": PROJECT_RECEIPT_PATH.as_posix(),
        "published": True,
        "schema_version": 1,
    }
    base["artifacts"] = artifacts
    return base


def initialize_project(project_root: str | pathlib.Path = ".") -> dict[str, Any]:
    root = pathlib.Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"project root not found: {project_root}")
    cache = pathlib.Path(os.path.abspath(root / ".cache/diavisuals"))
    reject_symlink_components(cache, root)
    _ensure_confined_directory(root, cache)
    return {"ok": True, "project": str(root), "created": [rel(cache, root)]}


def down_factory(project_root: str | pathlib.Path = ".") -> dict[str, Any]:
    root = pathlib.Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"project root not found: {project_root}")
    docker = shutil.which("docker")
    if not docker:
        return {"ok": True, "containers": [], "message": "Docker is unavailable"}
    workspace_id = renderer_workspace_id(root)
    listed = run(
        [
            docker,
            "container",
            "ls",
            "--all",
            "--quiet",
            "--filter",
            f"label={RENDERER_CONTAINER_LABEL}",
            "--filter",
            f"label={RENDERER_WORKSPACE_LABEL}={workspace_id}",
        ],
        cwd=root,
    )
    if listed["returncode"] != 0:
        return {"ok": False, "containers": [], "result": listed}
    containers = listed["stdout"].split()
    if any(not DOCKER_CONTAINER_ID_RE.fullmatch(container) for container in containers):
        return {
            "ok": False,
            "containers": [],
            "message": "Docker returned an invalid container identifier; refusing cleanup.",
        }
    if not containers:
        return {"ok": True, "containers": []}
    removed = run([docker, "container", "rm", "--force", *containers], cwd=root)
    return {
        "ok": removed["returncode"] == 0,
        "containers": containers,
        "result": removed,
    }


def mcp_stdio_command() -> list[str]:
    return [sys.executable, "-m", "diavisuals.cli", "mcp", "serve"]


def client_config(project: str = "${workspaceFolder}", command: str = "") -> dict[str, Any]:
    server_command = [command, "mcp", "serve"] if command else mcp_stdio_command()
    return {
        "mcpServers": {
            "diavisuals": {
                "command": server_command[0],
                "args": server_command[1:],
                "env": {"MCP_CONSUMER_WORKSPACE": project},
            }
        }
    }


def vscode_client_config(project: str = "${workspaceFolder}", command: str = "") -> dict[str, Any]:
    server_command = [command, "mcp", "serve"] if command else mcp_stdio_command()
    return {
        "servers": {
            "diavisuals": {
                "type": "stdio",
                "command": server_command[0],
                "args": server_command[1:],
                "env": {"MCP_CONSUMER_WORKSPACE": project},
            }
        }
    }


def factory_manifest() -> dict[str, Any]:
    checkout = source_checkout()
    if checkout is not None:
        factory_make = ["make", "--no-print-directory", "-C", "${factoryRoot}"]
        factory_launcher = [
            "bash",
            "${factoryRoot}/scripts/factory-launcher",
        ]
        transport = [*factory_make, "mcp-stdio"]
        commands = {
            "build": [*factory_make, "mcp-build"],
            "init": [*factory_launcher, "init", "${workspaceFolder}"],
            "check": [*factory_make, "mcp-check"],
            "tests": [*factory_make, "tests"],
            "smoke": [*factory_make, "mcp-smoke"],
            "down": [*factory_launcher, "down", "${workspaceFolder}"],
            "update": [*factory_launcher, "update"],
            "release_status": [*factory_launcher, "release-status"],
            "install_check": [*factory_launcher, "install-check"],
            "factory_check": [*factory_launcher, "factory-check"],
            "install_codex_mcp": [*factory_launcher, "install-codex-mcp", "${workspaceFolder}"],
            "serve": [*factory_launcher, "serve", "${workspaceFolder}"],
            "manifest": [*factory_launcher, "manifest"],
            "styles": [*factory_launcher, "styles"],
            "audit": [*factory_launcher, "audit"],
            "project_check": [*factory_launcher, "project-check", "${workspaceFolder}"],
            "render": [*factory_launcher, "render", "${workspaceFolder}"],
            "render_text": [*factory_launcher, "render-text", "${workspaceFolder}"],
        }
    else:
        factory_cli = ["diavisuals"]
        project_cli = [*factory_cli, "--project", "${workspaceFolder}"]
        transport = [*factory_cli, "mcp", "serve"]
        commands = {
            "build": [*factory_cli, "ensure-renderer"],
            "init": [*project_cli, "init"],
            "check": [*factory_cli, "lifecycle-check"],
            "tests": [*factory_cli, "self-test"],
            "smoke": [*factory_cli, "mcp-smoke"],
            "down": [*project_cli, "down"],
            "update": [*factory_cli, "update"],
            "release_status": [*factory_cli, "release-status"],
            "install_check": [*factory_cli, "install-check"],
            "factory_check": [*factory_cli, "factory-check"],
            "install_codex_mcp": [*project_cli, "install-codex-mcp"],
            "serve": [*project_cli, "mcp", "serve"],
            "manifest": [*factory_cli, "factory-manifest"],
            "styles": [*factory_cli, "style-inventory"],
            "audit": [*factory_cli, "style-audit"],
            "project_check": [*project_cli, "project-check"],
            "render": [*project_cli, "render-diagram"],
            "render_text": [*project_cli, "render-diagram-text"],
        }
    return {
        "ok": True,
        "schema_version": 1,
        "name": "diavisuals",
        "kind": "codex-mcp-factory",
        "install_scope": "user",
        "version": __version__,
        "description": "Workspace-confined diagram styles and hardened Docker rendering for Mermaid and PlantUML.",
        "repository": "https://github.com/dosquartsdedocs/diavisuals",
        "workspace_rule": {
            "binding": "consumer",
            "consumer_root": ".",
            "source_paths": [
                "assets/**/*.{mmd,mermaid,puml,plantuml,uml}",
                "_chapters/**/*.{mmd,mermaid,puml,plantuml,uml}",
                "_documentation/**/*.{mmd,mermaid,puml,plantuml,uml}",
            ],
            "generated_paths": [
                ".cache/diavisuals",
                ".unaltraweb/receipts/diavisuals.json",
            ],
            "init_creates": [".cache/diavisuals"],
            "allowed_external_writes": [],
        },
        "runtime": {
            "kind": "python",
            "package_manager": "uv",
            "package": "diavisuals[mcp]",
            "module": "diavisuals",
            "mcp_version": MCP_VERSION,
        },
        "transport": {
            "type": "stdio",
            "command": transport,
            "env": {"MCP_CONSUMER_WORKSPACE": "${workspaceFolder}"},
        },
        "commands": commands,
        "discovery": {
            "file": "mcp-factory.yml",
            "suggested_scan_roots": ["~/git"],
            "checkout_required_for_make_lifecycle": checkout is not None,
        },
        "release": {
            "default": DEFAULT_RELEASE,
            "compatibility": DEFAULT_COMPATIBILITY,
            "family": DEFAULT_FAMILY,
        },
        "contracts": {
            "mcp_errors": "typed-is-error-result",
            "consumer_root_fixed_at_startup": True,
            "container_consumer_mount": "none",
            "renderer_staging": "selected-input-and-style-assets-only",
            "project_check_roots": list(UNALTRAWEB_DIAGRAM_ROOTS),
            "receipt": PROJECT_RECEIPT_PATH.as_posix(),
        },
        "mcp": {
            "server_name": "diavisuals",
            "transport": "stdio",
            "consumer_root_fixed_at_startup": True,
            "required_tools": list(MCP_TOOL_NAMES),
            "resources": list(MCP_RESOURCE_URIS),
        },
    }


def factory_check(project_root: str | pathlib.Path = ".") -> dict[str, Any]:
    issues: list[str] = []
    assets = repo_dir()
    required_assets = [
        assets / "docker/compat-renderer.Dockerfile",
        assets / "docker/package.json",
        assets / "docker/package-lock.json",
        assets / "tools/render-one.sh",
        assets / "styles/mermaid/benizar-mermaid.json",
        assets / "styles/plantuml/benizar-plantuml.puml",
    ]
    issues.extend(
        f"packaged asset is missing: {rel(path, assets)}"
        for path in required_assets
        if not path.is_file()
    )
    static_path = factory_metadata_root() / "mcp-factory.yml"
    static: dict[str, Any] = {}
    if not static_path.is_file():
        issues.append("factory discovery manifest is missing")
    else:
        try:
            loaded = yaml.safe_load(static_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("factory discovery manifest must be a mapping")
            static = loaded
            dynamic = factory_manifest()
            for key in (
                "schema_version",
                "name",
                "kind",
                "install_scope",
                "version",
                "description",
                "repository",
                "workspace_rule",
                "runtime",
                "transport",
                "commands",
                "discovery",
                "release",
                "contracts",
                "mcp",
            ):
                if static.get(key) != dynamic.get(key):
                    issues.append(f"static factory manifest does not match {key}")
        except (OSError, ValueError, yaml.YAMLError) as exc:
            issues.append(str(exc))
    styles = check_styles()
    issues.extend(styles["issues"])
    root = pathlib.Path(project_root).expanduser().resolve()
    if not root.is_dir():
        issues.append(f"consumer project root does not exist: {project_root}")
    return {
        "ok": not issues,
        "issues": issues,
        "project": str(root),
        "assets": {"root": str(assets), "manifest": str(static_path)},
        "styles": styles,
    }


def install_check(command: str = "diavisuals") -> dict[str, Any]:
    resolved = shutil.which(command)
    if not resolved and pathlib.Path(command).is_file():
        resolved = str(pathlib.Path(command).resolve())
    if resolved:
        resolved = str(pathlib.Path(resolved).resolve())
    result = None
    mcp_dependency = None
    if resolved:
        result = run([resolved, "--version"], cwd=repo_dir(), timeout=30)
        mcp_dependency = check_mcp_dependency(resolved)
    return {
        "ok": bool(
            resolved
            and result
            and result["returncode"] == 0
            and mcp_dependency
            and str(result["stdout"]).strip() == f"diavisuals {__version__}"
            and mcp_dependency["returncode"] == 0
            and str(mcp_dependency["stdout"]).strip() == MCP_VERSION
        ),
        "command": command,
        "resolved": resolved,
        "version_result": result,
        "mcp_dependency": mcp_dependency,
        "mcp_version": str(mcp_dependency["stdout"]).strip() if mcp_dependency else None,
        "mcp_version_matches": bool(
            mcp_dependency and str(mcp_dependency["stdout"]).strip() == MCP_VERSION
        ),
        "install_hints": [
            "uv sync --locked --extra mcp",
            "uv tool install 'diavisuals[mcp]'",
        ],
    }


def lifecycle_check(
    project_root: str | pathlib.Path = ".", command: str = "diavisuals"
) -> dict[str, Any]:
    install = install_check(command)
    factory = factory_check(project_root)
    return {
        "ok": install["ok"] and factory["ok"],
        "install": install,
        "factory": factory,
    }


def entrypoint_python(command_path: str) -> str | None:
    try:
        first_line = pathlib.Path(command_path).read_text(encoding="utf-8", errors="ignore").splitlines()[0]
    except (IndexError, OSError, UnicodeDecodeError):
        return None
    if not first_line.startswith("#!"):
        return None
    executable = first_line[2:].strip().split()[0]
    if pathlib.Path(executable).exists():
        return executable
    return None


def check_mcp_dependency(command_path: str) -> dict[str, Any]:
    python = entrypoint_python(command_path)
    if not python:
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": "Could not determine the Python interpreter used by the CLI entrypoint.",
            "command": [command_path],
        }
    return run(
        [
            python,
            "-c",
            "from importlib.metadata import version; "
            "from mcp.server.fastmcp import FastMCP; print(version('mcp'))",
        ],
        cwd=repo_dir(),
        timeout=30,
    )


def json_dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
