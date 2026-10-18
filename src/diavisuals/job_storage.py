"""Standalone private-registry W1 manager for one-diagram jobs.

Bulk bytes are streamed into named Docker volumes. The private host registry
contains bounded identities, leases, coverage maps, decisions and tombstones only.
"""
from __future__ import annotations

import contextlib
import copy
import datetime as dt
import fcntl
import hmac
import json
import os
import pathlib
import secrets
import stat
import threading
import uuid

from . import __version__, artifacts, job_io
from . import registry as core
from .handoff_fs import Workspace, digest, parse_json
from .session import CURRENT_SESSION, DAEMON_LABEL, IMAGE_LABEL, JOB_LABEL, owner_labels, owner_state, process_owner

CONTRACT = "docker-job-volumes-v1"
REFERENCE = "83cb0d3e2f424759475ae70b423a0f8dca8520b2"
MARKER = ".diavisuals-w1-marker.json"
MAX_LEDGER = 1024 * 1024
MAX_INPUT = 32 * 1024 * 1024
CONTEXT_ENV = "DIAVISUALS_JOB_STORAGE_GRANT"


class StorageError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def need(condition, code, message):
    if not condition:
        raise StorageError(code, message)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode()


def fresh(value):
    try:
        age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return 0 <= age.total_seconds() <= 30
    except (ValueError, TypeError, AttributeError):
        return False


def identifier():
    return uuid.uuid4().hex


def declaration():
    with Workspace(core.factory_metadata_root()) as package:
        raw = package.read("mcp-job-storage.json", 65536, package_asset=True)
        package.recheck()
    value = parse_json(raw)
    need(value.keys() == {"kind", "schema_version", "contract", "provider", "storage_tool", "job_root", "scratch_root", "path_policies", "limits"}
         and value["kind"] == "gacontext.job-storage-provider" and type(value["schema_version"]) is int and value["schema_version"] == 1
         and value["contract"] == CONTRACT and value["provider"] == "diavisuals" and value["storage_tool"] == "job_storage"
         and value["job_root"] == "/work" and value["scratch_root"] == "/work/scratch", "storage-binding-mismatch", "unsupported installed storage declaration")
    policies = {"inputs": ("input-snapshots", "resolved-retention"), "results": ("results", "resolved-retention"),
                "exports": ("sealed-products", "resolved-retention"), "recovery": ("recovery", "resolved-retention"), "scratch": ("regenerable", "on-release")}
    need(len(value["path_policies"]) == 5 and {item["path"]: (item["role"], item["cleanup"]) for item in value["path_policies"]} == policies
         and all(item.keys() == {"path", "role", "cleanup", "type"} and item["type"] == "directory" for item in value["path_policies"]),
         "storage-binding-mismatch", "installed job path policies differ from W1")
    limits = value["limits"]
    maximum = {"max_scratch_bytes": 1024 ** 4, "max_retained_bytes": 1024 ** 4, "max_entries": 1000000,
               "max_jobs": 128, "min_free_bytes": 1024 ** 4, "monitor_interval_seconds": 10}
    need(limits.keys() == {*maximum, "quota_enforcement"} and limits["quota_enforcement"] == "monitored"
         and all(type(limits[key]) is int and 1 <= limits[key] <= high for key, high in maximum.items()),
         "storage-binding-mismatch", "unsupported installed storage budget")
    return value, digest(raw)


def label_tuple(job, volume):
    return {"io.context.mcp-storage." + key: value for key, value in {
        "contract": CONTRACT, "registry": job["registry_id"], "provider": "diavisuals", "binding": job["binding_id"],
        "job": job["job_id"], "volume": volume["id"], "role": volume["role"],
    }.items()}


def request_check(request, job):
    base = {"kind", "schema_version", "operation", "registry_id", "job_id"}
    operation = request.get("operation") if isinstance(request, dict) else None
    expected = base if operation == "status" else base | {"expected_revision", "expected_epoch"}
    need(type(request) is dict and request.keys() == expected and request.get("kind") == "gacontext.job-storage-request"
         and type(request.get("schema_version")) is int and request["schema_version"] == 1
         and operation in {"status", "quiesce", "seal"}, "storage-binding-mismatch", "unsupported storage request envelope")
    need(all(request[key] == job[key] for key in ("registry_id", "job_id")), "storage-binding-mismatch", "request addresses another registered job")
    if operation != "status":
        need(type(request["expected_revision"]) is int and type(request["expected_epoch"]) is int
             and request["expected_revision"] == job["revision"] and request["expected_epoch"] == job["epoch"],
             "storage-revision-conflict", "stale job revision or epoch")


def private_file(path, maximum=MAX_LEDGER):
    path = pathlib.Path(path).absolute()
    need(not any(parent.is_symlink() for parent in [path, *path.parents]), "storage-binding-mismatch", "private registry paths must not contain symlinks")
    info = path.stat()
    need(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and not info.st_mode & 0o077
         and info.st_nlink == 1 and info.st_size <= maximum, "storage-binding-mismatch", "private registry file is not owned/bounded/private")
    with Workspace(path.parent) as workspace:
        data = workspace.read(path.name, maximum)
        workspace.recheck()
    return parse_json(data)


class Registry:
    def __init__(self, grant_path, consumer=None):
        grant = private_file(grant_path, 65536)
        self.root = pathlib.Path(grant["registry_root"]).absolute()
        self.grant = grant
        self.consumer = pathlib.Path(consumer).resolve(strict=True) if consumer else None
        self.descriptor, self.descriptor_sha = declaration()
        self.producer_sources = artifacts._producer_snapshot()[1]
        self._mutex = threading.RLock()
        self._local = threading.local()
        need(not any(parent.is_symlink() for parent in [self.root, *self.root.parents]), "storage-binding-mismatch", "unsafe registry root")
        info = self.root.stat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and not info.st_mode & 0o077,
             "storage-binding-mismatch", "registry must be private to this user")

    @classmethod
    def create(cls, path, consumer, runtime=None, limits=None):
        root = pathlib.Path(path).absolute()
        consumer = pathlib.Path(consumer).resolve(strict=True)
        with Workspace(root.parent), Workspace(consumer):
            pass
        need(not core.path_within(root, consumer) and not core.path_within(root, core.repo_dir()),
             "storage-binding-mismatch", "registry state must be outside consumer and engine roots")
        provider, provider_sha = declaration()
        effective = copy.deepcopy(provider["limits"])
        for key, value in (limits or {}).items():
            need(key in effective, "storage-budget-exceeded", "unknown budget field")
            if key == "quota_enforcement":
                need(value == "monitored", "storage-unsupported-quota", "hard quotas require a different verified storage deployment")
            else:
                need(type(value) is int and value >= 1 and (value >= effective[key] if key == "min_free_bytes" else value <= effective[key]),
                     "storage-budget-exceeded", "effective limits may only tighten the provider budget")
            effective[key] = value
        image = core.renderer_status(runtime=runtime)
        need(image["ok"], "storage-binding-mismatch", "explicitly prepare the selected renderer first")
        daemon = core.renderer_daemon_identity()
        need(daemon["ok"], "storage-observation-unknown", "Docker daemon identity is unavailable")
        topology = job_io.local_capacity_profile()
        need(topology["daemon_id"] == daemon["id"], "storage-binding-mismatch", "capacity daemon differs")
        root.mkdir(mode=0o700)
        (root / "bindings").mkdir(mode=0o700)
        token, registry_id = secrets.token_hex(32), identifier()
        document = {"registry_id": registry_id, "version": __version__, "provider_sha256": provider_sha,
                    "admin_sha256": digest(token.encode()), "daemon_id": daemon["id"], "image_id": image["image_id"],
                     "profile": image["renderer"], "runtime": image["runtime"], "jobs": {}, "receivers": {}, "revision": 1,
                     "topology": topology, "limits": effective}
        (root / "ledger.json").write_bytes(json_bytes(document))
        (root / "ledger.json").chmod(0o600)
        (root / "lock").touch(mode=0o600)
        grant = {"registry_root": str(root), "registry_id": registry_id, "role": "admin", "token": token}
        target = root / "admin.json"
        target.write_bytes(json_bytes(grant))
        target.chmod(0o600)
        return {"ok": True, "registry_id": registry_id, "admin_grant": str(target), "limits": effective}

    @contextlib.contextmanager
    def locked(self):
        with self._mutex:
            if getattr(self._local, "state", None) is not None:
                yield self._local.state
                return
            with self._file_lock() as state:
                self._local.state = state
                try:
                    yield state
                finally:
                    self._local.state = None

    @contextlib.contextmanager
    def _file_lock(self):
        fd = os.open(self.root / "lock", os.O_RDWR | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid() and not info.st_mode & 0o077,
                 "storage-binding-mismatch", "unsafe registry lock")
            fcntl.flock(fd, fcntl.LOCK_EX)
            state = private_file(self.root / "ledger.json")
            need(state["registry_id"] == self.grant["registry_id"] and state["provider_sha256"] == self.descriptor_sha,
                 "storage-binding-mismatch", "registry/provider identity mismatch")
            need(state["version"] == __version__, "storage-binding-mismatch", "use this registry's exact native controller version")
            expected = state["admin_sha256"] if self.grant["role"] == "admin" else state["jobs"].get(self.grant.get("job_id"), {}).get("grant_sha256", "")
            need(hmac.compare_digest(expected, digest(self.grant["token"].encode())), "storage-binding-mismatch", "private manager grant was not issued by this registry")
            daemon = core.renderer_daemon_identity()
            need(daemon["ok"] and daemon["id"] == state["daemon_id"], "storage-binding-mismatch", "Docker daemon changed or is unknown")
            yield state
        finally:
            os.close(fd)

    def save(self, state, job=None):
        state["revision"] += 1
        if job is not None:
            job["revision"] += 1
        data = json_bytes(state)
        need(len(data) <= MAX_LEDGER, "storage-budget-exceeded", "bounded registry ledger is full")
        temporary = self.root / ("ledger-" + identifier())
        with temporary.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, self.root / "ledger.json")
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def job(self, state, job_id=None):
        job_id = job_id or self.grant.get("job_id")
        need(self.grant["role"] == "admin" or job_id == self.grant.get("job_id"), "storage-binding-mismatch", "grant does not authorise this job")
        need(job_id in state["jobs"], "storage-binding-mismatch", "job is not registered")
        job = state["jobs"][job_id]
        if self.consumer is not None:
            need(job["consumer"] == str(self.consumer), "storage-binding-mismatch", "original consumer binding differs")
            info = self.consumer.stat()
            need([info.st_dev, info.st_ino] == job["consumer_identity"], "storage-binding-mismatch", "consumer incarnation changed")
        return job

    def admin(self):
        need(self.grant["role"] == "admin", "storage-binding-mismatch", "operation requires the private manager authority")

    def volume_inspect(self, volume):
        result = core.run(["docker", "volume", "inspect", volume["name"]], timeout=10)
        if result["returncode"]:
            return {"state": "absent" if "no such volume" in result["stderr"].lower() else "unknown"}
        try:
            actual = json.loads(result["stdout"])[0]
            valid = (actual["Name"] == volume["name"] and actual["Driver"] == "local" and actual["Scope"] == "local"
                     and not actual.get("Options") and actual["Labels"] == volume["labels"] and actual["CreatedAt"] == volume["created_at"])
        except (ValueError, KeyError, TypeError, IndexError):
            valid = False
        return {"state": "verified" if valid else "unknown"}

    def attachments(self, volume):
        result = core.run(["docker", "container", "ls", "--all", "--quiet", "--no-trunc", "--filter", f"volume={volume['name']}"], timeout=10)
        ids = result["stdout"].split()
        valid = not result["returncode"] and len(ids) <= 256 and all(core.DOCKER_CONTAINER_ID_RE.fullmatch(value) and len(value) == 64 for value in ids)
        return valid, ids if valid else []

    def marker(self, job, volume):
        return {**{key: job[key] for key in ("registry_id", "job_id", "binding_id", "provider", "provider_sha256", "daemon_id")},
                "contract": CONTRACT, "volume_id": volume["id"], "name": volume["name"], "role": volume["role"]}

    def binding(self, job, lease, readonly):
        return {"kind": "gacontext.job-storage-binding", "schema_version": 1,
                **{key: job[key] for key in ("registry_id", "job_id", "binding_id", "provider", "provider_sha256", "daemon_id", "epoch")},
                "lease_id": lease["id"], "access": "read-only" if readonly else "read-write", "job_root": "/work",
                "mounts": [{key: value[key] for key in ("id", "name", "role", "marker_sha256")} for value in job["volumes"] if not readonly or value["role"] == "retained"]}

    def new_lease(self, state, job, kind):
        job["leases"] = [item for item in job["leases"] if item["state"] != "released"]
        need(len(job["leases"]) < 128, "storage-budget-exceeded", "lease bound reached")
        lease = {"id": identifier(), "kind": kind, "state": "active", "epoch": job["epoch"], "owner": process_owner(), "worker": None}
        job["leases"].append(lease)
        self.save(state, job)
        return lease

    def worker(self, state, job, request, *, lease=None, roles=("retained", "scratch"), readonly=False, data=None, receive=None):
        """Admission and exact worker identity are persisted before Docker attachment.

        Domain work runs outside the ledger lock. Control probes are short,
        manager-only operations under the admission fence, with task leases.
        """
        job_id, owned_lease = job["job_id"], lease is None
        with self.locked() as state:
            job = self.job(state, job_id)
            request = copy.deepcopy(request)
            if request.get("operation_id"):
                request["controller_hashes"] = job["operations"][request["operation_id"]]["controller_hashes"]
            if lease is None:
                lease = self.new_lease(state, job, "task")
            else:
                lease = next(item for item in job["leases"] if item["id"] == lease["id"])
            need(lease["state"] == "active" and lease["epoch"] == job["epoch"] and lease["owner"] == process_owner()
                 and lease["worker"] is None, "storage-lease-mismatch", "worker lease is stale, busy or belongs to another process")
            if not owned_lease:
                need(lease["kind"] in ({"reader", "transfer"} if readonly else {"writer"}),
                     "storage-lease-mismatch", "lease access kind does not authorize these mounts")
                need(job["phase"] in {"open", "draining", "closed"} and (readonly or job["phase"] != "closed"),
                     "storage-admission-closed", "worker admission is fenced")
            volumes = [volume for volume in job["volumes"] if volume["role"] in roles]
            need(len(volumes) == len(roles), "storage-volume-mismatch", "registered volume is missing")
            for volume in volumes:
                need(self.volume_inspect(volume)["state"] == "verified", "storage-volume-mismatch", "registered volume is missing or replaced")
            metadata = self.root / "bindings" / (identifier() + ".json")
            binding = self.binding(job, lease, readonly) if not owned_lease else {"manager_control": request["op"], "registry_id": state["registry_id"]}
            metadata.write_bytes(json_bytes(binding))
            metadata.chmod(0o444)
            name = "diavisuals-w1-" + identifier()
            labels = {**owner_labels(), "io.context.mcp-factory": "diavisuals", core.RENDERER_WORKSPACE_LABEL: core.renderer_workspace_id(pathlib.Path(job["consumer"])),
                      JOB_LABEL: name, IMAGE_LABEL: state["image_id"], DAEMON_LABEL: state["daemon_id"],
                      **{"io.context.mcp-storage." + key: value for key, value in {"contract": CONTRACT, "registry": state["registry_id"],
                         "provider": "diavisuals", "binding": job["binding_id"], "job": job_id}.items()}}
            lease["worker"] = {"name": name, "id": None, "labels": labels, "metadata": metadata.name, "operation": request["op"]}
            self.save(state, job)
            mounts = []
            for volume in volumes:
                target = "/work/scratch" if volume["role"] == "scratch" else "/work"
                mounts.extend(["--mount", f"type=volume,source={volume['name']},target={target},volume-nocopy" + (",readonly" if readonly else "")])
            mounts.extend(["--mount", core._docker_mount_spec("type=bind", f"source={metadata}", "target=/run/gacontext/job-storage.json", "readonly")])
            need(artifacts._producer_snapshot()[1] == self.producer_sources, "storage-binding-mismatch", "loaded controller sources changed")
            script = self.producer_sources["payload/producer/job_worker.py"].decode()
            command = ["docker", "create", "--pull=never", "--interactive", "--name", name, "--network", "none", "--read-only", "--cap-drop", "ALL",
                       "--security-opt", "no-new-privileges=true", "--memory", "1g", "--memory-swap", "1g", "--cpus", "2", "--pids-limit", "256",
                       "--log-driver", "none", "--ulimit", "fsize=67108864:67108864", "--ulimit", "nofile=1024:1024",
                       "--user", "0:0" if request["op"] in {"bootstrap", "put"} else "65532:65532",
                       *(["--cap-add", "CHOWN"] if request["op"] == "bootstrap" else []), "--workdir", "/",
                       "-e", "MCP_JOB_STORAGE_BINDING=/run/gacontext/job-storage.json", "-e", "PYTHONDONTWRITEBYTECODE=1",
                       *[argument for key, value in labels.items() for argument in ("--label", f"{key}={value}")], *mounts,
                       "--entrypoint", "python3", state["image_id"], "-c", script]
        cid, session = None, CURRENT_SESSION.get()
        if session:
            session.job_started(name, state["image_id"], state["daemon_id"])
        try:
            # The persisted lease prevents retirement across this create/record gap.
            created = core.run(command, timeout=30)
            cid = created["stdout"].strip()
            need(created["returncode"] == 0 and len(cid) == 64 and core.DOCKER_CONTAINER_ID_RE.fullmatch(cid), "storage-observation-unknown", "worker creation failed")
            with self.locked() as current:
                live = self.job(current, job_id)
                active = next(item for item in live["leases"] if item["id"] == lease["id"])
                active["worker"]["id"] = cid
                self.save(current, live)
            if session:
                session.job_observed(name, cid)
            inspected = core.run(["docker", "container", "inspect", cid, "--format", "{{json .Mounts}}"], timeout=10)
            actual = json.loads(inspected["stdout"])
            need(len(actual) == len(volumes) + 1, "storage-volume-mismatch", "unexpected worker mount count")
            for volume in volumes:
                target = "/work/scratch" if volume["role"] == "scratch" else "/work"
                need(self.volume_inspect(volume)["state"] == "verified" and any(item["Type"] == "volume" and item["Name"] == volume["name"]
                     and item["Destination"] == target and item["RW"] == (not readonly) for item in actual), "storage-volume-mismatch", "actual mount/incarnation differs")
            need(any(item["Type"] == "bind" and item["Source"] == str(metadata) and item["Destination"] == "/run/gacontext/job-storage.json" and not item["RW"] for item in actual),
                 "storage-binding-mismatch", "binding mount differs")
            payload = json_bytes(request).replace(b"\n", b" ") + b"\n" + (data or b"")
            result = job_io.exchange(["docker", "start", "--attach", "--interactive", cid], payload, receive=receive)
            return result if receive else parse_json(result)
        finally:
            cleanup = core._remove_renderer_container(name, expected_labels=labels, container_id=cid or None)
            if session:
                session.job_finished(name, cleanup)
            with self.locked() as current:
                live = self.job(current, job_id)
                active = next(item for item in live["leases"] if item["id"] == lease["id"])
                if cleanup["ok"]:
                    active["worker"] = None
                    if owned_lease:
                        active["state"] = "released"
                    metadata.unlink(missing_ok=True)
                else:
                    active["state"] = "unknown"
                self.save(current, live)
            need(cleanup["ok"], "storage-observation-unknown", "exact worker absence was not verified")

    def allocate(self, consumer):
        self.admin()
        consumer = pathlib.Path(consumer).resolve(strict=True)
        with self.locked() as state:
            live = [job for job in state["jobs"].values() if job["phase"] != "released"]
            need(len(live) < state["limits"]["max_jobs"] and len(state["jobs"]) < 64, "storage-budget-exceeded", "registry job/reservation bound reached")
            token, job_id = secrets.token_hex(32), identifier()
            info = consumer.stat()
            job = {"registry_id": state["registry_id"], "job_id": job_id, "binding_id": identifier(), "provider": "diavisuals", "provider_sha256": self.descriptor_sha,
                   "daemon_id": state["daemon_id"], "consumer": str(consumer), "consumer_identity": [info.st_dev, info.st_ino],
                   "grant_sha256": digest(token.encode()), "revision": 1, "epoch": 1, "phase": "open", "leases": [], "products": [],
                    "holds": [], "operations": {}, "volumes": [], "coverage": {}, "limits": copy.deepcopy(state["limits"]),
                    "journal": [], "measurements": {}, "initialized": False, "plan": None}
            state["jobs"][job_id] = job
            self.save(state)
            self.budget(state, job, allocating=True)
            for role in ("retained", "scratch"):
                self.allocate_volume(state, job, role)
            job["initialized"] = True
            self.refresh(state, job)
            self.save(state, job)
            grant = {"registry_root": str(self.root), "registry_id": state["registry_id"], "role": "client", "job_id": job_id, "token": token}
            target = self.root / (job_id + ".grant.json")
            target.write_bytes(json_bytes(grant))
            target.chmod(0o600)
            return {"ok": True, "job_id": job_id, "registry_id": state["registry_id"], "grant": str(target)}

    def allocate_volume(self, state, job, role):
        identity = identifier()
        volume = {"id": identity, "name": "gacontext-job-" + identity, "role": role, "daemon_id": state["daemon_id"], "driver": "local",
                  "created_at": now(), "retired": False}
        volume["labels"] = label_tuple(job, volume)
        volume["marker_sha256"] = digest(json_bytes(self.marker(job, volume)))
        job["volumes"] = [item for item in job["volumes"] if item["role"] != role] + [volume]
        self.save(state, job)  # Allocation intent survives a crash before create returns.
        inspected = core.run(["docker", "volume", "inspect", volume["name"]], timeout=10)
        need(inspected["returncode"] != 0 and "no such volume" in inspected["stderr"].lower(), "storage-volume-mismatch", "new incarnation name already exists or is unknown")
        created = core.run(["docker", "volume", "create", "--driver", "local",
                            *[argument for key, value in volume["labels"].items() for argument in ("--label", f"{key}={value}")], volume["name"]])
        need(not created["returncode"], "storage-observation-unknown", "volume allocation failed; intent retained")
        actual = json.loads(core.run(["docker", "volume", "inspect", volume["name"]])["stdout"])[0]
        volume["created_at"] = actual["CreatedAt"]
        self.save(state, job)
        # Bootstrap independently: retained's physical scratch mountpoint must be
        # inspected without a nested volume hiding unclassified bytes.
        self.worker(state, job, {"op": "bootstrap", "markers": {role: self.marker(job, volume)}}, roles=(role,))

    def budget(self, state, job, *, allocating=False, incoming=0, entries=0):
        need(job["limits"]["quota_enforcement"] == "monitored", "storage-budget-exceeded", "this profile cannot enforce hard quotas")
        need(job_io.local_capacity_profile() == state["topology"], "storage-observation-unknown", "Docker capacity topology changed")
        capacity = self.worker(state, job, {"op": "capacity"}, roles=(), readonly=True)["filesystem"]
        # Reserve the full ceilings for every live incarnation, including pending
        # closed jobs. This deliberately over-reserves already occupied bytes.
        reservations = sum(item["limits"]["max_retained_bytes"] + item["limits"]["max_scratch_bytes"]
                           for item in state["jobs"].values() if item["phase"] != "released")
        need(capacity["free_bytes"] >= reservations + job["limits"]["min_free_bytes"], "storage-budget-exceeded", "daemon filesystem cannot cover live reservations and minimum free space")
        if not allocating:
            self.refresh(state, job)
            measurements = job["measurements"]
            need(all(role in measurements and fresh(measurements[role]["observed_at"]) for role in ("retained", "scratch")),
                 "storage-observation-unknown", "current job measurements are unavailable")
            need(measurements["retained"]["bytes"] + incoming <= job["limits"]["max_retained_bytes"]
                 and measurements["scratch"]["bytes"] <= job["limits"]["max_scratch_bytes"]
                 and sum(item["entries"] for item in measurements.values()) + entries <= job["limits"]["max_entries"],
                 "storage-budget-exceeded", "job byte/entry budget exceeded")
        job["capacity"] = {**capacity, "reserved_bytes": reservations, "observed_at": now(), "quota_enforcement": "monitored"}
        self.save(state, job)

    def refresh(self, state, job):
        """Explicit mutating manager observation. `status` never calls this."""
        need(not any(item["state"] != "released" and item["kind"] in {"writer", "transfer", "reader"} for item in job["leases"]),
             "storage-busy", "active domain/transfer lease prevents protected inventory")
        for volume in job["volumes"]:
            observed = self.volume_inspect(volume)
            complete, attachments = self.attachments(volume)
            if observed["state"] != "verified" or not complete or attachments:
                job["measurements"].pop(volume["role"], None)
                continue
            try:
                measured = self.worker(state, job, {"op": "observe", "markers": {volume["role"]: self.marker(job, volume)},
                                       "max_entries": job["limits"]["max_entries"]}, roles=(volume["role"],), readonly=True)["measurements"][volume["role"]]
                job["measurements"][volume["role"]] = {**measured, "observed_at": now(), "volume_id": volume["id"]}
            except (ValueError, OSError):
                job["measurements"].pop(volume["role"], None)
        self.save(state, job)

    def inventory(self, job):
        if job["phase"] == "released":
            return job["retired_inventory"], []
        measured = job["measurements"].get("retained", {})
        if not fresh(measured.get("observed_at")):
            return {"state": "unknown", "tree_sha256": None, "unresolved_entries": 0}, [{"id": job["job_id"], "reason": "unknown-content"}]
        if job.get("discarded_inventory", {}).get("tree_sha256") == measured["tree_sha256"]:
            return {"state": "verified", "tree_sha256": measured["tree_sha256"], "unresolved_entries": 0}, []
        files = [item for item in measured["inventory"] if item["kind"] != "directory"]
        parents = {parent.as_posix() for item in files for parent in pathlib.PurePosixPath(item["path"]).parents if parent.as_posix() != "."}
        unresolved = set(measured["unknown"])
        for item in files:
            covered = job["coverage"].get(item["path"], {})
            if item.get("sha256") is None or covered.get("sha256") != item.get("sha256"):
                unresolved.add(item["path"])
        unresolved.update(item["path"] for item in measured["inventory"] if item["kind"] == "directory"
                          and item["path"] not in {"inputs", "results", "exports", "recovery", "scratch", *parents})
        reasons = {"inputs": "unsealed-source", "results": "unsealed-result", "exports": "unsealed-result", "recovery": "recovery"}
        holds = [{"id": uuid.uuid5(uuid.UUID(job["job_id"]), reason).hex, "reason": reason}
                 for reason in sorted({reasons.get(path.split("/")[0], "unknown-content") for path in unresolved})]
        return {"state": "verified", "tree_sha256": measured["tree_sha256"], "unresolved_entries": len(unresolved)}, holds

    def product_view(self, state, job, product):
        value = {key: copy.deepcopy(product[key]) for key in ("id", "bundle_sha256", "disposition", "decision")}
        if value["disposition"] == "discarded" and job["phase"] != "released":
            decision = job.get("discarded_inventory", {})
            valid = (digest(json_bytes(decision)) == value["decision"]["evidence_sha256"] and
                     {"id": product["id"], "bundle_sha256": product["bundle_sha256"]} in decision.get("products", []))
            value["decision"].update(status="verified" if valid else "unknown", verified_at=now())
            return value
        if value["disposition"] != "acknowledged" or job["phase"] == "released":
            return value
        try:
            receipt = product["retention"]
            receiver = state["receivers"][receipt["receiver_binding_id"]]
            evidence = job_io.verify_directory(receiver, receipt["destination"]["path"], product["bundle_sha256"])
            need(evidence["domain_check_sha256"] == receipt["domain_check_sha256"] and digest(json_bytes(receipt)) == value["decision"]["evidence_sha256"],
                 "storage-export-incomplete", "retention evidence changed")
            value["decision"].update(status="verified", verified_at=now())
        except (OSError, ValueError, KeyError):
            value["decision"]["status"] = "stale"
        return value

    def state_view(self, state, job):
        need(len(job["volumes"]) == 2 and job["initialized"], "storage-observation-unknown", "incomplete allocation remains recorded for manager recovery")
        leases, activity = [], "idle"
        for lease in job["leases"]:
            lease_state = lease["state"]
            if lease_state != "released" and owner_state(lease["owner"]) != "alive":
                lease_state = "unknown"
            leases.append({"id": lease["id"], "kind": lease["kind"], "state": lease_state})
            if lease_state == "unknown":
                activity = "unknown"
            elif lease_state == "active" and lease["kind"] in {"task", "writer"} and activity != "unknown":
                activity = "busy"
        volumes = []
        for volume in job["volumes"]:
            info = self.volume_inspect(volume)
            complete, attachments = self.attachments(volume)
            measured = job["measurements"].get(volume["role"], {})
            if info["state"] == "verified" and (not fresh(measured.get("observed_at")) or measured.get("volume_id") != volume["id"]):
                info["state"] = "unknown"
            if not complete or attachments:
                if activity != "busy":
                    activity = "unknown"
            # Native Docker timestamps need normalising for the common UTC wire.
            created = dt.datetime.fromisoformat(volume["created_at"].replace("Z", "+00:00")).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
            volumes.append({**{key: volume[key] for key in ("id", "name", "role", "daemon_id", "driver", "marker_sha256", "labels")},
                            "created_at": created, "state": info["state"], "observed_at": measured.get("observed_at", now()) if info["state"] != "absent" else now(), "attachments_complete": complete,
                            "attachments": attachments, "bytes": 0 if info["state"] == "absent" else measured.get("bytes")})
        protected, holds = self.inventory(job)
        if job["phase"] == "released":
            need(all(item["state"] == "absent" for item in volumes), "storage-volume-mismatch", "a retired incarnation name is present again or its absence is unknown")
        retained = next(item for item in volumes if item["role"] == "retained")
        if retained["state"] == "absent" and job.get("retired_inventory") and any(
            item["volume"] == retained["id"] and item["action"] == "remove-intent" for item in job["journal"]
        ):
            protected, holds = job["retired_inventory"], []
        products = [self.product_view(state, job, item) for item in job["products"]]
        if any(item["decision"] and item["decision"]["status"] != "verified" for item in products):
            holds.append({"id": uuid.uuid5(uuid.UUID(job["job_id"]), "destination-unavailable").hex, "reason": "destination-unavailable"})
        return {"kind": "gacontext.job-storage-state", "schema_version": 1, "contract": CONTRACT,
                **{key: job[key] for key in ("registry_id", "job_id", "binding_id", "provider", "provider_sha256", "daemon_id", "revision", "epoch", "phase", "limits")},
                "observed_at": now(), "activity": activity, "leases_complete": True, "leases": leases, "volumes": volumes,
                "products": products, "holds": holds, "protected_inventory": protected}

    def status(self, job_id=None):
        with self.locked() as state:
            return self.state_view(state, self.job(state, job_id))

    def cas(self, job, revision, epoch):
        need(type(revision) is int and type(epoch) is int and (revision, epoch) == (job["revision"], job["epoch"]),
             "storage-revision-conflict", "stale revision or epoch; inspect current state")

    def client_attach(self, job_id=None):
        with self.locked() as state:
            job = self.job(state, job_id)
            need(job["phase"] == "open" and job["initialized"], "storage-admission-closed", "job does not admit new clients")
            lease = self.new_lease(state, job, "client")
            return {"ok": True, "lease_id": lease["id"], "job_id": job["job_id"], "epoch": job["epoch"]}

    def client_detach(self, lease_id, job_id=None):
        with self.locked() as state:
            job = self.job(state, job_id)
            lease = next((item for item in job["leases"] if item["id"] == lease_id), None)
            need(lease and lease["kind"] == "client" and lease["owner"] == process_owner(), "storage-lease-mismatch", "client interest belongs to another native process")
            lease["state"] = "released"
            self.save(state, job)
            if not any(item["state"] != "released" and item["kind"] == "client" for item in job["leases"]):
                self.drain(state, job)
            job_id = job["job_id"]
        return self.release_idle(job_id)

    def release_idle(self, job_id):
        with self.locked() as state:
            job = self.job(state, job_id)
            if job["phase"] != "closed" or any(item["state"] != "released" for item in job["leases"]):
                return self.state_view(state, job)
            result = self.plan_release(job_id)
            plan = result["plan"]
            if any(item["action"] == "remove-volume" for item in plan["volumes"]):
                return self.release(result["plan_sha256"], plan["expected_revision"], plan["expected_epoch"], job_id)
            return result["state"]

    def toggle_group(self, job_ids):
        self.admin()
        need(isinstance(job_ids, list) and 0 < len(job_ids) <= 128 and len(set(job_ids)) == len(job_ids),
             "storage-binding-mismatch", "select a bounded distinct group of registered jobs")
        outcomes = []
        for job_id in job_ids:
            try:
                with self.locked() as state:
                    job = self.job(state, job_id)
                    for lease in job["leases"]:
                        if lease["kind"] == "client" and lease["owner"] == process_owner() and lease["state"] == "active":
                            lease["state"] = "released"
                            self.save(state, job)
                    if job["phase"] in {"open", "draining"} and not any(item["state"] != "released" and item["kind"] == "client" for item in job["leases"]):
                        self.drain(state, job)
                outcomes.append({"ok": True, "state": self.release_idle(job_id)})
            except (ValueError, OSError) as error:
                outcomes.append({"ok": False, "job_id": job_id, "code": getattr(error, "code", "storage-observation-unknown"), "error": str(error)[:512]})
        return {"ok": all(item["ok"] for item in outcomes), "outcomes": outcomes}

    def drain(self, state, job):
        need(job["phase"] in {"open", "draining", "closed"}, "storage-admission-closed", "job is releasing or released")
        if job["phase"] == "closed":
            return
        if job["phase"] == "open":
            job["phase"] = "draining"
            self.save(state, job)
        if any(item["state"] != "released" and item["kind"] != "client" for item in job["leases"]):
            return
        self.refresh(state, job)
        observed = self.state_view(state, job)
        if observed["activity"] != "idle":
            return
        job["holds"] = observed["holds"]
        job["phase"], job["epoch"] = "closed", job["epoch"] + 1
        self.save(state, job)

    @contextlib.contextmanager
    def writer(self, revision, epoch, job_id=None, incoming=0, entries=0):
        with self.locked() as state:
            job = self.job(state, job_id)
            self.cas(job, revision, epoch)
            need(job["initialized"] and job["phase"] == "open", "storage-admission-closed", "write admission is closed")
            need(not any(item["state"] != "released" and item["kind"] != "client" for item in job["leases"]), "storage-busy", "domain or transfer work is active")
            self.budget(state, job, incoming=incoming, entries=entries)
            lease = self.new_lease(state, job, "writer")
            job_id = job["job_id"]
        try:
            yield state, job, lease
        finally:
            with self.locked() as state:
                job = self.job(state, job_id)
                lease = next(item for item in job["leases"] if item["id"] == lease["id"])
                if lease["worker"] is None and lease["state"] == "active":
                    lease["state"] = "released"
                    self.save(state, job)
                    self.refresh(state, job)
                    if job["phase"] == "draining":
                        self.drain(state, job)
                        self.release_idle(job_id)

    def control(self, request):
        with self.locked() as state:
            job = self.job(state, request.get("job_id") if isinstance(request, dict) else None)
            request_check(request, job)
            if request["operation"] == "status":
                return self.state_view(state, job)
            if request["operation"] == "quiesce":
                self.drain(state, job)
                return self.state_view(state, job)
            job_id = job["job_id"]
        self.seal(request["expected_revision"], request["expected_epoch"], job_id)
        return self.status(job_id)

    def render(self, revision, epoch, *, job_id=None, input_path=None, diagram_text=None, engine="auto", family=core.DEFAULT_FAMILY,
               style="", output_format="svg", original_path=None, edited_paths=None, runtime=None):
        """One bounded native diagram operation; bulk bytes never stage on the host."""
        import yaml

        need((input_path is None) != (diagram_text is None), "storage-export-incomplete", "select one file or inline source")
        edits = edited_paths or []
        need(len(edits) <= 32 and len(set(edits)) == len(edits) and bool(edits) == bool(original_path),
             "storage-export-incomplete", "edits require one selected original and at most 32 unique variants")
        operation = identifier()
        with self.locked() as state:
            job = self.job(state, job_id)
            self.cas(job, revision, epoch)
            need(len(job["operations"]) < 16, "storage-budget-exceeded", "bounded job operation count reached")
            if runtime is not None:
                selected = core.renderer_status(runtime=runtime)
                need(selected["ok"] and selected["image_id"] == state["image_id"] and selected["runtime"] == state["runtime"],
                     "storage-binding-mismatch", "selected native runtime differs from the manager's pinned renderer")
            root, job_id = pathlib.Path(job["consumer"]), job["job_id"]
            profile = state["profile"]["profile"]
            image_id, runtime_identity = state["image_id"], state["runtime"]
        files = {}
        with Workspace(root) as workspace:
            for path in ([input_path] if input_path else []) + ([original_path, *edits] if original_path else []):
                artifacts._reject_composite_input(workspace, path)
            source = workspace.read(input_path, core.MAX_DIAGRAM_SOURCE_BYTES) if input_path is not None else diagram_text.encode("utf-8")
            need(0 < len(source) <= core.MAX_DIAGRAM_SOURCE_BYTES, "storage-budget-exceeded", "source exceeds diagram profile")
            engine = core.diagram_engine(pathlib.Path(input_path), engine) if input_path else core.diagram_engine_from_text(diagram_text, engine)
            artifacts._source_check(source, engine)
            output_format = core.resolve_output_format(None, output_format)
            style = core.resolve_style_name(engine, style or family)
            need(core.STYLE_NAME_RE.fullmatch(family), "storage-export-incomplete", "invalid style family")
            suffix = "mmd" if engine == "mermaid" else "puml"
            files[f"source/source.{suffix}"] = source
            for index, path in enumerate([original_path, *edits] if original_path else []):
                need(path.endswith(".svg"), "storage-export-incomplete", "original and edited variants must be SVG")
                data = workspace.read(path)
                artifacts._svg_check(data)
                files["variants/" + ("original.svg" if index == 0 else f"edited-{index}.svg")] = data
                need(sum(map(len, files.values())) <= MAX_INPUT, "storage-budget-exceeded", "selected variants exceed bounded input stream")
            workspace.recheck()
        assets = core.repo_dir()
        with Workspace(assets) as package:
            for path in core.renderer_asset_paths(engine, style, output_format):
                relative = path.relative_to(assets).as_posix()
                files["render/" + relative] = package.read(relative, package_asset=True)
                if relative.startswith("styles/"):
                    artifacts._source_check(files["render/" + relative], engine, resource=True)
            files["profile.env"] = package.read(f"compat/{profile}.env", package_asset=True)
            package.recheck()
        need(digest(files["profile.env"]) == runtime_identity["profile_sha256"], "storage-binding-mismatch", "effective profile changed")
        for path, data in artifacts._producer_sources().items():
            files["controller/diavisuals/" + path.rsplit("/", 1)[1]] = data
        # Pure Python PyYAML only: no host ABI extension is sent into the image.
        yaml_root = pathlib.Path(yaml.__file__).parent
        with Workspace(yaml_root) as package:
            for path in sorted(yaml_root.glob("*.py")):
                files["controller/yaml/" + path.name] = package.read(path.name, package_asset=True)
            package.recheck()
        options = {"engine": engine, "style": style, "family": family, "output_format": output_format, "profile": profile,
                   "image_id": image_id, "runtime": runtime_identity, "source_origin": {"kind": "file", "path": input_path} if input_path else {"kind": "inline"},
                   "original": original_path, "edits": edits}
        files["request.json"] = json_bytes(options)
        files = {f"inputs/{operation}/{path}": data for path, data in files.items()}
        need(sum(map(len, files.values())) <= MAX_INPUT and len(files) <= 512, "storage-budget-exceeded", "input snapshot exceeds profile")
        entry_count = len(files) + len({parent.as_posix() for path in files for parent in pathlib.PurePosixPath(path).parents})
        with self.writer(revision, epoch, job_id, incoming=sum(map(len, files.values())) + 64 * 1024 * 1024, entries=entry_count + 8) as (state, job, lease):
            with self.locked() as current:
                live = self.job(current, job_id)
                live["operations"][operation] = {"state": "snapshotting", "product": None,
                    "controller_hashes": {path.split("/controller/", 1)[1]: digest(data) for path, data in files.items() if "/controller/" in path}}
                self.save(current, live)
            expected = {path: {"sha256": digest(data), "executable": "/render/tools/" in path and path.endswith(".sh")} for path, data in files.items()}
            self.worker(state, job, {"op": "put", "files": expected, "max_bytes": MAX_INPUT}, lease=lease, data=job_io.input_archive(files))
            with self.locked() as current:
                live = self.job(current, job_id)
                live["operations"][operation]["state"] = "rendering"
                self.save(current, live)
            result = self.worker(state, job, {"op": "render", "operation_id": operation, "limits": job["limits"]}, lease=lease)
            with self.locked() as current:
                live = self.job(current, job_id)
                live["operations"][operation]["state"] = "rendered" if result["ok"] else "failed"
                self.save(current, live)
        return {"ok": result["ok"], "operation_id": operation, "job_id": job_id, "result": result, "state": self.status(job_id)}

    def seal(self, revision, epoch, job_id=None):
        with self.locked() as state:
            job = self.job(state, job_id)
            self.cas(job, revision, epoch)
            need(job["phase"] == "open", "storage-admission-closed", "sealing requires open admission")
            need(not any(item["state"] != "released" and item["kind"] != "client" for item in job["leases"]), "storage-busy", "sealing requires domain-idle state")
            pending = [key for key, item in job["operations"].items() if item["state"] == "rendered"]
            if not pending:
                return  # Stable IDs/revision for unchanged completed products.
        with self.writer(revision, epoch, job_id, incoming=artifacts.MAX_PRODUCT_BYTES, entries=1024) as (state, job, lease):
            for operation in pending:
                product_id = identifier()
                with self.locked() as current:
                    live = self.job(current, job["job_id"])
                    live["operations"][operation]["sealing"] = product_id
                    self.save(current, live)
                result = self.worker(state, job, {"op": "seal", "operation_id": operation, "product_id": product_id,
                                     "render_teardown_verified": True}, lease=lease)
                with self.locked() as current:
                    live = self.job(current, job["job_id"])
                    product = {"id": product_id, "bundle_sha256": result["bundle_sha256"], "disposition": "pending", "decision": None, "operation_id": operation}
                    live["products"].append(product)
                    live["operations"][operation]["state"] = "sealed"
                    live["coverage"].update({path: {"sha256": sha, "product": product_id} for path, sha in result["coverage"].items()})
                    self.save(current, live)

    def register_receiver(self, root, prefix):
        self.admin()
        receiver = job_io.receiver_binding(root, prefix)
        with self.locked() as state:
            need(len(state["receivers"]) < 16, "storage-budget-exceeded", "receiver registry is full")
            need(not core.path_within(pathlib.Path(root).absolute(), self.root), "storage-binding-mismatch", "registry metadata is not a durable receiver")
            identity = identifier()
            state["receivers"][identity] = receiver
            self.save(state)
            return {"ok": True, "receiver_binding_id": identity, "format": "directory", "policy": receiver}

    def deliver(self, product_id, receiver_id, destination, revision, epoch, job_id=None):
        # Receiver selection is an authenticated private-manager action, not a
        # producer tool accepting arbitrary host paths or self-authored receipts.
        self.admin()
        with self.locked() as state:
            job = self.job(state, job_id)
            self.cas(job, revision, epoch)
            need(job["phase"] in {"open", "draining", "closed"}, "storage-admission-closed", "delivery admission is closed")
            need(not any(item["state"] != "released" and item["kind"] != "client" for item in job["leases"]), "storage-busy", "job is in use")
            product = next((item for item in job["products"] if item["id"] == product_id), None)
            need(product is not None and receiver_id in state["receivers"], "storage-binding-mismatch", "unknown product or receiver")
            receiver = state["receivers"][receiver_id]
            lease = self.new_lease(state, job, "transfer")
            transaction, job_id = identifier(), job["job_id"]
        try:
            result = self.worker(state, job, {"op": "transfer", "operation_id": product["operation_id"], "product_id": product_id,
                                 "bundle_sha256": product["bundle_sha256"]}, lease=lease, roles=("retained",), readonly=True,
                                 receive=lambda stream: job_io.receive_directory(stream, receiver, destination, product["bundle_sha256"], transaction))
            receipt = {"kind": "gacontext.job-product-retention", "schema_version": 1, "registry_id": job["registry_id"], "job_id": job_id,
                       "product_id": product_id, "bundle_sha256": product["bundle_sha256"], "receiver_binding_id": receiver_id,
                       "destination": {"path": destination, "format": "directory", "content_sha256": product["bundle_sha256"]},
                       "domain_profile": "diavisuals-leaf-v1", "domain_check_sha256": result["domain_check_sha256"], "verified_at": now()}
            verified = job_io.verify_directory(receiver, destination, product["bundle_sha256"])
            need(verified == result, "storage-export-incomplete", "receiver changed before acknowledgement")
            with self.locked() as current:
                live = self.job(current, job_id)
                actual = next(item for item in live["products"] if item["id"] == product_id)
                need(actual["bundle_sha256"] == receipt["bundle_sha256"] and live["epoch"] == epoch, "storage-revision-conflict", "product or fence changed during transfer")
                actual.update(disposition="acknowledged", retention=receipt, decision={"id": identifier(), "kind": "retention",
                              "evidence_sha256": digest(json_bytes(receipt)), "bundle_sha256": actual["bundle_sha256"], "verified_at": now(), "status": "verified"})
                self.save(current, live)
            return {"ok": True, "retention": receipt, "sha256": digest(json_bytes(receipt))}
        finally:
            with self.locked() as current:
                live = self.job(current, job_id)
                actual = next(item for item in live["leases"] if item["id"] == lease["id"])
                if actual["worker"] is None and actual["state"] == "active":
                    actual["state"] = "released"
                    self.save(current, live)

    def plan_release(self, job_id=None):
        with self.locked() as state:
            job = self.job(state, job_id)
            if not any(item["state"] != "released" for item in job["leases"]) and job["phase"] != "released":
                self.refresh(state, job)
            self.save(state, job)
            observed = self.state_view(state, job)
            common = []
            if job["phase"] not in {"closed", "releasing", "released"}:
                common.append("admission-not-closed")
            if observed["activity"] != "idle" or any(item["state"] != "released" for item in observed["leases"]):
                common.append("active-or-unknown-lease")
            obligations = []
            if observed["holds"] or observed["protected_inventory"]["state"] != "verified" or observed["protected_inventory"]["unresolved_entries"]:
                obligations.append("unresolved-protected-content")
            if any(item["disposition"] == "pending" or item["decision"]["status"] != "verified" for item in observed["products"]):
                obligations.append("pending-or-unverified-product")
            volumes = []
            for volume in observed["volumes"]:
                blockers = common + (obligations if volume["role"] == "retained" else [])
                if volume["state"] == "unknown" or not volume["attachments_complete"] or volume["attachments"]:
                    blockers = blockers + ["volume-identity-or-attachment-unknown"]
                volumes.append({"id": volume["id"], "name": volume["name"], "role": volume["role"], "estimated_bytes": volume["bytes"],
                                "action": "blocked" if blockers else "already-absent" if volume["state"] == "absent" else "remove-volume", "blockers": blockers})
            plan = {"registry_id": job["registry_id"], "job_id": job["job_id"], "expected_revision": job["revision"] + 1, "expected_epoch": job["epoch"],
                    "planned_at": now(), "volumes": volumes, "requires_live_revalidation": True, "execution_supported": True,
                    "all_releasable": all(item["action"] != "blocked" for item in volumes)}
            job["plan"] = plan
            self.save(state, job)
            return {"ok": True, "plan": plan, "plan_sha256": digest(json_bytes(plan)), "state": self.state_view(state, job)}

    def release(self, plan_sha256, revision, epoch, job_id=None):
        with self.locked() as state:
            job = self.job(state, job_id)
            self.cas(job, revision, epoch)
            plan = job["plan"]
            need(plan and digest(json_bytes(plan)) == plan_sha256 and fresh(plan["planned_at"]), "storage-revision-conflict", "release plan is missing, stale or changed")
            need(job["phase"] in {"closed", "releasing", "released"} and not any(item["state"] != "released" for item in job["leases"]),
                 "storage-busy", "admission or leases prevent retirement")
            if job["phase"] == "released":
                return self.state_view(state, job)
            job["phase"] = "releasing"
            self.save(state, job)
            for role in ("scratch", "retained"):
                volume = next(item for item in job["volumes"] if item["role"] == role)
                planned = next(item for item in plan["volumes"] if item["role"] == role)
                if planned["action"] == "blocked":
                    continue
                self.refresh(state, job)
                observed = self.state_view(state, job)
                actual = next(item for item in observed["volumes"] if item["role"] == role)
                need(actual["state"] != "unknown" and actual["attachments_complete"] and not actual["attachments"] and observed["activity"] == "idle",
                     "storage-observation-unknown", "live volume identity, marker or attachment differs")
                if role == "retained":
                    need(not observed["holds"] and observed["protected_inventory"]["state"] == "verified" and not observed["protected_inventory"]["unresolved_entries"]
                         and all(item["disposition"] != "pending" and item["decision"]["status"] == "verified" for item in observed["products"]),
                         "storage-export-incomplete", "live retained content or destination is unresolved")
                    job["retired_inventory"] = observed["protected_inventory"]
                    for item in observed["products"]:
                        next(product for product in job["products"] if product["id"] == item["id"])["decision"] = item["decision"]
                job["journal"] = (job["journal"] + [{"volume": volume["id"], "action": "remove-intent", "at": now()}])[-128:]
                self.save(state, job)
                # Flock/admission fence remain held. Non-force exact-name removal
                # makes Docker reject even a racing external attachment.
                if actual["state"] != "absent":
                    removed = core.run(["docker", "volume", "rm", volume["name"]], timeout=30)
                    need(not removed["returncode"], "storage-busy", "Docker refused exact non-force retirement")
                need(self.volume_inspect(volume)["state"] == "absent", "storage-observation-unknown", "exact volume absence was not observed")
                volume["retired"] = True
                self.save(state, job)
            job["phase"] = "released" if all(item.get("retired") for item in job["volumes"]) else "closed"
            self.save(state, job)
            return self.state_view(state, job)

    def recover(self, job_id=None):
        self.admin()
        with self.locked() as state:
            job = self.job(state, job_id)
            recovered = []
            for lease in job["leases"]:
                if lease["state"] == "released" or owner_state(lease["owner"]) != "dead":
                    continue
                worker = lease["worker"]
                if worker:
                    result = core._remove_renderer_container(worker["name"], expected_labels=worker["labels"], container_id=worker["id"])
                    if not result["ok"]:
                        continue
                    (self.root / "bindings" / worker["metadata"]).unlink(missing_ok=True)
                    lease["worker"] = None
                lease["state"] = "released"
                recovered.append(lease["id"])
                self.save(state, job)
            if not job["initialized"] and len(job["volumes"]) == 2 and all(item["state"] == "released" for item in job["leases"]):
                for volume in job["volumes"]:
                    self.worker(state, job, {"op": "bootstrap", "resume": True, "markers": {volume["role"]: self.marker(job, volume)}}, roles=(volume["role"],))
                job["initialized"] = True
                self.refresh(state, job)
                self.save(state, job)
            if job["phase"] == "draining":
                self.drain(state, job)
            return {"ok": True, "recovered_leases": recovered, "state": self.state_view(state, job)}

    def discard(self, tree_sha256, revision, epoch, reason, *, confirm=False, job_id=None):
        self.admin()
        need(confirm is True and isinstance(reason, str) and 1 <= len(reason) <= 512,
             "storage-binding-mismatch", "discard requires an explicit user decision and bounded reason")
        with self.locked() as state:
            job = self.job(state, job_id)
            self.cas(job, revision, epoch)
            need(job["phase"] == "closed" and not any(item["state"] != "released" for item in job["leases"]),
                 "storage-busy", "explicit discard requires a closed, unleased job")
            self.refresh(state, job)
            measured = job["measurements"].get("retained", {})
            need(fresh(measured.get("observed_at")) and all(item["kind"] == "directory" or (item["kind"] == "file" and item.get("sha256"))
                 for item in measured.get("inventory", [])) and measured.get("tree_sha256") == tree_sha256,
                 "storage-revision-conflict", "discard does not cover the exact current known protected inventory")
            decision = {"id": identifier(), "kind": "user-discard", "tree_sha256": tree_sha256, "reason": reason, "at": now(),
                        "registry_id": job["registry_id"], "job_id": job["job_id"], "epoch": job["epoch"],
                        "products": [{"id": item["id"], "bundle_sha256": item["bundle_sha256"]} for item in job["products"]]}
            job["discarded_inventory"] = decision
            for product in job["products"]:
                product.update(disposition="discarded", decision={"id": identifier(), "kind": "user-discard", "bundle_sha256": product["bundle_sha256"],
                               "evidence_sha256": digest(json_bytes(decision)), "verified_at": now(), "status": "verified"})
            self.save(state, job)
            return self.state_view(state, job)

    def reopen(self, revision, epoch, job_id=None):
        self.admin()
        with self.locked() as state:
            job = self.job(state, job_id)
            self.cas(job, revision, epoch)
            need(job["phase"] == "closed" and not any(item["state"] != "released" for item in job["leases"]), "storage-busy", "reopen requires a closed, unleased job")
            retained = next(item for item in job["volumes"] if item["role"] == "retained")
            need(self.volume_inspect(retained)["state"] == "verified", "storage-volume-mismatch", "retained incarnation differs")
            self.budget(state, job, allocating=True)
            scratch = next(item for item in job["volumes"] if item["role"] == "scratch")
            if self.volume_inspect(scratch)["state"] == "absent" and scratch.get("retired"):
                job["journal"] = (job["journal"] + [{"volume": scratch["id"], "action": "retired-incarnation", "at": now()}])[-128:]
                self.allocate_volume(state, job, "scratch")
            else:
                need(self.volume_inspect(scratch)["state"] == "verified", "storage-volume-mismatch", "scratch is missing/replaced, not a retired incarnation")
            job["epoch"] += 1
            job["phase"], job["plan"] = "open", None
            self.refresh(state, job)
            self.save(state, job)
            return self.state_view(state, job)


def selected(consumer=None):
    grant = os.environ.get(CONTEXT_ENV)
    need(bool(grant), "storage-binding-mismatch", f"select a private manager-issued job with {CONTEXT_ENV}")
    return Registry(grant, consumer)
