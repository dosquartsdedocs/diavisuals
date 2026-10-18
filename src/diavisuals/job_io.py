"""Bounded W1 transport and explicit durable-directory receiver primitives."""
from __future__ import annotations

import io
import json
import os
import pathlib
import subprocess
import tarfile
import threading

from . import artifacts
from . import registry as core
from .handoff_fs import MAX_FILE, Workspace, digest, json_bytes, rename_new, require, safe_path


def exchange(command, payload, *, receive=None, maximum=1024 * 1024, timeout=330):
    """No unbounded communicate/spool; a watchdog also bounds blocked pipe readers."""
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    errors = bytearray()
    expired = threading.Event()

    def stop():
        expired.set()
        process.kill()

    def write():
        try:
            process.stdin.write(payload)
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    def drain():
        for chunk in iter(lambda: process.stderr.read(8192), b""):
            errors.extend(chunk[:max(0, 65536 - len(errors))])

    threads = [threading.Thread(target=write, daemon=True), threading.Thread(target=drain, daemon=True)]
    timer = threading.Timer(timeout, stop)
    timer.daemon = True
    timer.start()
    for thread in threads:
        thread.start()
    try:
        if receive:
            result = receive(process.stdout)
            require(not process.stdout.read(1), "unexpected trailing transfer data")
        else:
            result = process.stdout.read(maximum + 1)
            require(len(result) <= maximum, "worker metadata exceeds bound")
        process.wait(timeout=10)
        require(not expired.is_set(), "worker deadline exceeded")
        require(process.returncode == 0, errors.decode(errors="replace")[:1024] or "worker failed")
        return result
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
        for thread in threads:
            thread.join(timeout=5)


def input_archive(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, data in files.items():
            item = tarfile.TarInfo(safe_path(name))
            item.size, item.mode = len(data), 0o444
            archive.addfile(item, io.BytesIO(data))
    return stream.getvalue()


def local_capacity_profile():
    """Corroborate the local default-volume/overlay filesystem, without data access.

    /proc/self/mountinfo supplies topology only; no Docker private Mountpoint is
    opened. Remote daemons, custom volume submounts and quota claims are refused.
    Actual capacity is subsequently measured inside the selected Docker image.
    """
    context = core.run(["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"], timeout=10)
    endpoint = os.environ.get("DOCKER_HOST") or json.loads(context["stdout"])
    require(endpoint.startswith("unix://") and not os.environ.get("DOCKER_TLS_VERIFY"), "W1 requires a local Unix Docker daemon")
    info = core.run(["docker", "info", "--format", '{{json .}}'], timeout=10)
    require(not info["returncode"], "Docker topology is unavailable")
    doc = json.loads(info["stdout"])
    require(doc["Driver"] == "overlay2" and doc["OSType"] == "linux", "unsupported Docker storage capacity profile")
    root = pathlib.Path(doc["DockerRootDir"])
    mounts = []
    with open("/proc/self/mountinfo", encoding="utf-8") as source:
        for index, line in enumerate(source):
            require(index < 8192 and len(line) < 16384, "mount topology exceeds bound")
            fields = line.split()
            mount = fields[4].replace("\\040", " ").replace("\\134", "\\")
            mounts.append((pathlib.Path(mount), fields[2]))

    def containing(path):
        return max((item for item in mounts if path == item[0] or item[0] in path.parents), key=lambda item: len(item[0].parts))

    expected = containing(root)
    require(containing(root / "volumes") == expected and containing(root / "overlay2") == expected,
            "Docker image and default volumes are not on the same observed filesystem")
    require(not any(root / "volumes" in mount.parents for mount, _ in mounts), "custom Docker volume submounts are unsupported")
    return {"daemon_id": doc["ID"], "endpoint": endpoint, "filesystem_device": expected[1], "driver": "overlay2"}


def receiver_binding(root, prefix):
    safe_path(prefix)
    root = pathlib.Path(root).absolute()
    with Workspace(root) as workspace:
        info = os.fstat(workspace.fd)
        result = core.run(["findmnt", "--json", "--target", str(root), "--output", "FSTYPE,SOURCE,MAJ:MIN"], timeout=10)
        require(not result["returncode"], "receiver filesystem observation unavailable")
        fs = json.loads(result["stdout"])["filesystems"]
        require(len(fs) == 1 and fs[0]["fstype"] in {"ext4", "xfs", "btrfs", "zfs"}, "receiver must be an observed persistent local filesystem")
        require(not any(part.casefold() in {".cache", ".tmp", "scratch", "tmp", "temp", "previews", ".diavisuals"}
                        for part in (*root.parts, *pathlib.PurePosixPath(prefix).parts)), "temporary/cache/job paths cannot receive durable acknowledgement")
        workspace.recheck()
    return {"root": str(root), "prefix": prefix, "identity": [info.st_dev, info.st_ino], "filesystem": fs[0]}


def receive_directory(stream, receiver, destination, bundle_sha, transaction):
    """Publish a complete tree at the receiver boundary; preserve all collisions.

    Interrupted copies remain in the receiver's explicitly owned transaction
    directory, never acknowledged and never silently overwritten on retry.
    """
    require(receiver_binding(receiver["root"], receiver["prefix"]) == receiver, "receiver binding changed")
    safe_path(destination)
    require(destination.startswith(receiver["prefix"] + "/"), "destination lies outside the durable receiver policy")
    parent, _, name = destination.rpartition("/")
    staged = parent + "/delivery-" + transaction
    total, entries, seen = 0, 0, set()
    with Workspace(receiver["root"]) as workspace:
        with workspace.directory(parent, create=True) as parent_fd:
            require(not any(item.casefold() == name.casefold() for item in os.listdir(parent_fd)), "authored receiver collision")
            os.mkdir(staged.rsplit("/", 1)[1], 0o700, dir_fd=parent_fd)
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            for item in archive:
                entries += 1
                require(entries <= 5000 and item.isfile() and item.name not in seen and 0 <= item.size <= MAX_FILE,
                        "unsupported/duplicate/oversize transfer entry")
                safe_path(item.name)
                total += item.size
                require(total <= artifacts.MAX_PRODUCT_BYTES + 1024 * 1024, "transfer tree exceeds bound")
                data = archive.extractfile(item).read(item.size + 1)
                require(len(data) == item.size, "truncated transfer")
                workspace.write_new(staged + "/" + item.name, data)
                seen.add(item.name)
        # tar padding is bounded too; a sender cannot append an unlimited stream.
        require(len(stream.read(10241)) <= 10240, "oversize transfer padding")
        artifacts.check_diagram_bundle(workspace.root, path=staged + "/bundle.json", sha256=bundle_sha)
        require(receiver_binding(receiver["root"], receiver["prefix"]) == receiver, "receiver changed during delivery")
        workspace.recheck()
        with workspace.directory(parent) as parent_fd:
            rename_new(parent_fd, staged.rsplit("/", 1)[1], parent_fd, name)
    return verify_directory(receiver, destination, bundle_sha)


def verify_directory(receiver, destination, bundle_sha):
    require(receiver_binding(receiver["root"], receiver["prefix"]) == receiver, "receiver binding is unavailable or changed")
    require(safe_path(destination).startswith(receiver["prefix"] + "/"), "receiver destination outside policy")
    checked = artifacts.check_diagram_bundle(receiver["root"], path=destination + "/bundle.json", sha256=bundle_sha)
    # The profile's domain evidence is portable, not dependent on its location.
    evidence = {"profile": "diavisuals-leaf-v1", "bundle_sha256": bundle_sha, "files": checked["files"], "domain_checked": True}
    return {"domain_check_sha256": digest(json_bytes(evidence)), "evidence": evidence}
