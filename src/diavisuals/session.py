"""Bounded native-stdio process observations and per-connection job ownership.

This is not a shared backend. Identity reads package/process metadata only; it
does not initialize or inspect consumer content, prepare Docker, or claim that
a reply from a still-running process proves resource release.
"""
from __future__ import annotations

import contextvars
import datetime
import hashlib
import inspect
import json
import os
import pathlib
import re
import site
import stat
import sys
import threading
import types
import uuid
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from . import __version__

REQUIREMENTS_REVISION = "5634ea2e3e42122bb365992dfca9f248feb89dec"
INSTANCE_LABEL = "io.context.mcp-instance"
JOB_LABEL = "io.context.mcp-job"
OWNER_PID_LABEL = "io.context.mcp-owner.pid"
OWNER_START_LABEL = "io.context.mcp-owner.start"
OWNER_BOOT_LABEL = "io.context.mcp-owner.boot"
OWNER_NAMESPACE_LABEL = "io.context.mcp-owner.pid-namespace"
OWNER_UID_LABEL = "io.context.mcp-owner.uid"
IMAGE_LABEL = "io.context.mcp-job.image"
DAEMON_LABEL = "io.context.mcp-job.daemon"
MAX_CODE_BYTES = 4 * 1024 * 1024
CURRENT_SESSION: contextvars.ContextVar[ServerSession | None] = contextvars.ContextVar("diavisuals_session", default=None)
_OWNER: dict[str, Any] | None = None
_OWNER_LOCK = threading.Lock()


def _read(path: pathlib.Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError("identity observation is not a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        after = os.fstat(descriptor)
        if len(data) > limit or (before.st_mtime_ns, before.st_size, before.st_ino) != (after.st_mtime_ns, after.st_size, after.st_ino):
            raise ValueError("identity observation changed or exceeded its bound")
        return data
    finally:
        os.close(descriptor)


def process_stat(pid: int) -> tuple[str, str]:
    fields = _read(pathlib.Path(f"/proc/{pid}/stat"), 8192).decode().rsplit(")", 1)[1].split()
    return fields[0], fields[19]  # Linux state and starttime; never parse comm as words.


def process_owner() -> dict[str, Any]:
    global _OWNER
    with _OWNER_LOCK:
        if _OWNER is None or _OWNER["pid"] != os.getpid():
            owner = {"instance_id": uuid.uuid4().hex, "pid": os.getpid(), "parent_pid": os.getppid(),
                     "uid": os.geteuid(), "server_started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     "start_ticks": None, "pid_namespace": None, "boot_id": None}
            try:
                owner.update(start_ticks=process_stat(os.getpid())[1], pid_namespace=os.readlink("/proc/self/ns/pid"),
                             boot_id=_read(pathlib.Path("/proc/sys/kernel/random/boot_id"), 128).decode().strip())
            except (OSError, ValueError, IndexError):
                pass
            _OWNER = owner
        return dict(_OWNER)


def owner_state(owner: dict[str, Any]) -> str:
    """PID comparison is valid only on this boot and in this PID namespace."""
    current = process_owner()
    if any(not owner.get(key) or owner[key] != current[key] for key in ("boot_id", "pid_namespace")):
        return "unknown"
    try:
        pid = owner["pid"]
        if type(pid) is not int or pid <= 0 or not re.fullmatch(r"[0-9]+", str(owner.get("start_ticks", ""))):
            return "unknown"
        state, started = process_stat(pid)
        return "dead" if started != owner["start_ticks"] or state in {"Z", "X"} else "alive"
    except FileNotFoundError:
        return "dead"
    except (OSError, ValueError, IndexError):
        return "unknown"


def owner_labels() -> dict[str, str]:
    owner = process_owner()
    return {INSTANCE_LABEL: owner["instance_id"], OWNER_PID_LABEL: str(owner["pid"]),
            OWNER_START_LABEL: owner["start_ticks"] or "unknown", OWNER_BOOT_LABEL: owner["boot_id"] or "unknown",
            OWNER_NAMESPACE_LABEL: owner["pid_namespace"] or "unknown", OWNER_UID_LABEL: str(owner["uid"])}


def source_snapshot(root: pathlib.Path) -> dict[str, Any]:
    try:
        entries = []
        with os.scandir(root) as stream:
            for index, entry in enumerate(stream):
                if index >= 128:
                    raise ValueError("package inventory exceeds identity bound")
                if entry.name.endswith(".py"):
                    entries.append(entry.name)
        if not entries or len(entries) > 32:
            raise ValueError("package source count exceeds identity bound")
        inventory = []
        total = 0
        for name in sorted(entries):
            data = _read(root / name, MAX_CODE_BYTES)
            total += len(data)
            if total > MAX_CODE_BYTES:
                raise ValueError("package sources exceed identity bound")
            inventory.append({"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        encoded = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
        return {"state": "observed", "sha256": hashlib.sha256(encoded).hexdigest(), "files": len(inventory), "bytes": total}
    except (OSError, ValueError):
        return {"state": "unavailable", "sha256": None}


@lru_cache(maxsize=1)
def _distribution_root() -> pathlib.Path | None:
    # Do not use importlib.metadata's ambient sys.path search: `python -m` can
    # place a consumer cwd on that path. Observe only the loaded package's
    # installation and interpreter site directories, and keep the chosen root.
    roots = [pathlib.Path(__file__).resolve().parent.parent, *map(pathlib.Path, site.getsitepackages())]
    if site.ENABLE_USER_SITE:
        roots.append(pathlib.Path(site.getusersitepackages()))
    for root in roots:
        candidate = root / f"diavisuals-{__version__}.dist-info"
        if candidate.is_dir() and not candidate.is_symlink():
            return candidate
    return None


def distribution_snapshot() -> dict[str, Any]:
    try:
        root = _distribution_root()
        if root is None:
            raise ValueError("installed metadata location is unavailable")
        path = root / "METADATA"
        data = _read(path, 1024 * 1024)
        versions = [line[9:].strip() for line in data.decode().splitlines() if line.startswith("Version: ")]
        if len(versions) != 1 or not re.fullmatch(r"[A-Za-z0-9._+\-]{1,80}", versions[0]):
            raise ValueError("invalid installed version metadata")
        return {"state": "observed", "version": versions[0], "sha256": hashlib.sha256(data).hexdigest(), "root": str(path.parent)}
    except (OSError, ValueError, AttributeError):
        return {"state": "unavailable", "version": None, "sha256": None, "root": None}


def _code_value(value: Any) -> Any:
    if isinstance(value, types.CodeType):
        fields = ("co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals", "co_stacksize", "co_flags",
                  "co_code", "co_consts", "co_names", "co_varnames", "co_filename", "co_name", "co_firstlineno",
                  "co_freevars", "co_cellvars")
        fields += tuple(field for field in ("co_exceptiontable", "co_linetable", "co_qualname") if hasattr(value, field))
        return {field: _code_value(getattr(value, field)) for field in fields}
    if isinstance(value, tuple):
        return {"tuple": [_code_value(item) for item in value]}
    if isinstance(value, frozenset):
        return {"frozenset": sorted((_code_value(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))}
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, complex):
        return {"complex": [value.real, value.imag]}
    if value is Ellipsis:
        return {"ellipsis": True}
    return value


def _code_digest(code: types.CodeType) -> str:
    data = json.dumps(_code_value(code), sort_keys=True, separators=(",", ":")).encode()
    if len(data) > MAX_CODE_BYTES:
        raise ValueError("loaded code observation exceeds its bound")
    return hashlib.sha256(data).hexdigest()


def loaded_code_fingerprint() -> str:
    """Actual loaded code objects, not a reread of current source/metadata.

    Python-version and installation-path specific. The portable release pin is
    the externally verified wheel/source fingerprint, not this observation.
    """
    codes = {}
    for name, module in list(sys.modules.items()):
        if name != "diavisuals" and not name.startswith("diavisuals."):
            continue
        if module is None:
            continue
        for key, value in vars(module).copy().items():
            value = inspect.unwrap(value)
            if inspect.isfunction(value) and value.__module__ == name:
                codes[f"{name}.{key}"] = _code_digest(value.__code__)
            elif inspect.isclass(value) and value.__module__ == name:
                for method_name, method in vars(value).items():
                    if isinstance(method, property):
                        for accessor, function in (("get", method.fget), ("set", method.fset), ("delete", method.fdel)):
                            if function is not None:
                                codes[f"{name}.{key}.{method_name}.{accessor}"] = _code_digest(inspect.unwrap(function).__code__)
                        continue
                    if isinstance(method, (staticmethod, classmethod)):
                        method = method.__func__
                    method = inspect.unwrap(method)
                    if inspect.isfunction(method):
                        codes[f"{name}.{key}.{method_name}"] = _code_digest(method.__code__)
    if len(codes) > 512:
        raise ValueError("loaded callable inventory exceeds its bound")
    return hashlib.sha256(json.dumps(codes, sort_keys=True).encode()).hexdigest()


class ServerSession:
    def __init__(self, consumer: pathlib.Path, runtime: Any):
        from . import registry as core

        self.consumer = consumer
        self.runtime = runtime
        self.owner = process_owner()
        self.package_root = pathlib.Path(__file__).resolve().parent
        self.loaded_version = __version__
        try:
            self.loaded_code_sha256 = loaded_code_fingerprint()
        except (TypeError, ValueError, RecursionError):
            self.loaded_code_sha256 = None
        self.startup_source = source_snapshot(self.package_root)
        self.startup_distribution = distribution_snapshot()
        checkout = core.source_checkout()
        self.mode = "development" if checkout else "installed"
        self.checkout_head = core.git_head(checkout) if checkout else None
        self.asset_root = str(core.repo_dir())
        self.startup_profile = self.profile_observation()
        self._lock = threading.Lock()
        self._active: str | None = None
        self._jobs: dict[str, dict[str, Any]] = {}
        self._draining = False
        self._closed = False
        self._daemon_id: str | None = None

    def profile_observation(self) -> dict[str, Any]:
        from . import registry as core

        try:
            profile = core.renderer_profile()
            return {"root": str(core.repo_dir()), "name": profile["profile"], "sha256": profile["profile_sha256"], "ok": profile["ok"]}
        except (OSError, ValueError):
            return {"root": str(core.repo_dir()), "name": core.DEFAULT_COMPATIBILITY, "sha256": None, "ok": False}

    def disk_observation(self) -> dict[str, Any]:
        source = source_snapshot(self.package_root)
        distribution = distribution_snapshot()
        available = source["state"] == "observed" and self.startup_source["state"] == "observed"
        drift = (source != self.startup_source or distribution != self.startup_distribution) if available else None
        return {"sources": source, "distribution": distribution, "drift": drift,
                "metadata_matches_loaded_version": distribution.get("version") == self.loaded_version}

    @contextmanager
    def operation(self, name: str):
        with self._lock:
            if self._closed or self._draining:
                raise ValueError("session is draining; reconnect before starting work")
            if self._active is not None:
                raise ValueError("session is busy; retry after its current operation")
            self._active = name
        token = CURRENT_SESSION.set(self)
        try:
            disk = self.disk_observation()
            if not self.loaded_code_sha256 or disk["drift"] is not False or not disk["metadata_matches_loaded_version"]:
                raise ValueError("loaded package observation is unavailable or on-disk bytes changed; restart before work")
            if self.profile_observation() != self.startup_profile or not self.startup_profile["ok"]:
                raise ValueError("startup profile is unavailable or changed; restart before work")
            yield
        finally:
            CURRENT_SESSION.reset(token)
            with self._lock:
                self._active = None

    def observe_daemon(self, identity: str | None) -> bool:
        with self._lock:
            if self._daemon_id is None and identity:
                self._daemon_id = identity
            return bool(identity and self._daemon_id == identity)

    def job_started(self, name: str, image_id: str, daemon_id: str) -> None:
        with self._lock:
            self._jobs[name] = {"name": name, "image_id": image_id, "daemon_id": daemon_id, "container_id": None, "state": "starting"}

    def job_observed(self, name: str, container_id: str | None) -> None:
        with self._lock:
            if name in self._jobs and container_id:
                self._jobs[name].update(container_id=container_id, state="identified")

    def job_finished(self, name: str, cleanup: dict) -> None:
        with self._lock:
            if cleanup["ok"]:
                self._jobs.pop(name, None)
            elif name in self._jobs:
                self._jobs[name]["state"] = "unknown"

    def lifecycle(self) -> dict[str, Any]:
        with self._lock:
            state = "draining" if self._closed or self._draining else "busy" if self._active else "unknown" if self._jobs else "connected"
            return {"state": state, "active_operation": self._active, "jobs": [dict(item) for item in self._jobs.values()],
                    "scope": "this-stdio-process", "shared_backend": False, "max_concurrent_operations": 1,
                    "legacy_down_scope": "explicit-workspace-force-all-instances",
                    "protocol_closed": self._closed,
                    "idle_expiry": "stdio EOF after work completes", "process_release_verified": False}

    def release(self, expected_instance_id: str) -> dict[str, Any]:
        with self._lock:
            if expected_instance_id != self.owner["instance_id"]:
                return {"ok": False, "error": "serving instance does not match expected identity"}
            if self._active or self._jobs:
                return {"ok": False, "state": "busy" if self._active else "unknown", "error": "active work or unverified cleanup prevents release"}
            self._draining = True
        return {"ok": True, "state": "draining", "instance_id": expected_instance_id,
                "process_release_verified": False, "next_action": "close this stdio connection and wait for this process to exit"}

    def close(self) -> None:
        with self._lock:
            self._draining = True
            self._closed = self._active is None and not self._jobs

    def identity(self) -> dict[str, Any]:
        from . import registry as core

        try:
            observed = core.renderer_status(runtime=self.runtime)
        except (OSError, ValueError):
            observed = {"ok": False, "error": "renderer observation unavailable"}
        daemon = core.renderer_daemon_identity()
        daemon_matches = self.observe_daemon(daemon.get("id"))
        disk = self.disk_observation()
        current_profile = self.profile_observation()
        profile_drift = current_profile != self.startup_profile
        complete = all(self.owner.get(key) for key in ("boot_id", "pid_namespace", "start_ticks"))
        lifecycle = self.lifecycle()
        return {"ok": True, "schema_version": 1, "scope": "live-serving-process", "factory": "diavisuals",
                "observation_only": True,
                "requirements_revision": REQUIREMENTS_REVISION, "profile": "native-stdio", "instance": dict(self.owner),
                "loaded": {"version": self.loaded_version, "mode": self.mode, "package_root": str(self.package_root),
                           "revision": f"sha256:{self.loaded_code_sha256}" if self.loaded_code_sha256 else None,
                           "revision_kind": "loaded-python-code-objects-v1",
                           "code_objects_sha256": self.loaded_code_sha256, "startup_sources": self.startup_source,
                           "startup_distribution": self.startup_distribution, "checkout_head_at_startup": self.checkout_head},
                "current_disk": disk, "interpreter": {"executable": sys.executable, "resolved_executable": os.path.realpath(sys.executable),
                                                       "version": sys.version.split()[0], "implementation": sys.implementation.name},
                "binding": {"kind": "consumer", "startup_fixed": True, "path": str(self.consumer),
                            "effective_runtime_path": str(self.consumer), "renderer_consumer_mount": False,
                            "renderer_input": "/diavisuals/input/source.<engine-suffix>", "renderer_output": "/output"},
                "resources": {"startup_root": self.asset_root, "startup_profile": dict(self.startup_profile),
                              "current_profile": current_profile, "profile_drift": profile_drift},
                "docker_daemon": {**daemon, "first_observed_id": self._daemon_id, "matches_first_observation": daemon_matches},
                "renderer": {"ok": observed["ok"], "selection": observed.get("runtime"),
                             "observed_image_id": observed.get("image_id"),
                             "error": observed.get("error") or ("renderer profile or image observation unavailable" if not observed["ok"] else None),
                             "profile": observed.get("renderer", {}).get("profile"),
                             "profile_sha256": observed.get("renderer", {}).get("profile_sha256")},
                "lifecycle": lifecycle,
                "bounds": {"worker_memory": core.RENDERER_MEMORY, "worker_cpus": core.RENDERER_CPUS,
                           "worker_pids": core.RENDERER_PIDS_LIMIT, "worker_timeout_seconds": core.RENDER_TIMEOUT_SECONDS},
                "pinned_runtime_ready": bool(lifecycle["state"] in {"connected", "busy"} and complete and daemon_matches and self.runtime.explicit and observed["ok"]
                                      and self.loaded_code_sha256 and disk["drift"] is False and disk["metadata_matches_loaded_version"] and not profile_drift and current_profile["ok"])}
