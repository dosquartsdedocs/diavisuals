"""Private-registry W1 worker. Executed as bounded trusted code in the pinned image.

No Docker socket, host checkout, private grant or caller-supplied command reaches
this worker. Only the manager supplies the read-only binding/control file.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import signal
import stat
import subprocess
import sys
import tarfile
import threading
import time

ROOT = pathlib.Path("/work")
SCRATCH = ROOT / "scratch"
MARKER = ".diavisuals-w1-marker.json"
POLICIES = {"inputs", "results", "exports", "recovery", "scratch"}
MAX_FILE = 64 * 1024 * 1024


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe(root, relative):
    parts = relative.split("/")
    if not parts or any(part in {"", ".", ".."} or "\\" in part or "\x00" in part for part in parts) or relative.startswith("/"):
        raise ValueError("unsafe job-relative path")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("job paths must not traverse links")
    return path


def read(path, maximum=MAX_FILE):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
            raise ValueError("invalid bounded job file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise ValueError("job file exceeds bound")
        return data
    finally:
        os.close(fd)


def write_new(path, data, mode=0o444):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def context():
    path = pathlib.Path(os.environ.get("MCP_JOB_STORAGE_BINDING", "/run/gacontext/job-storage.json"))
    value = json.loads(read(path, 65536))
    if value.get("kind") != "gacontext.job-storage-binding" or value.get("job_root") != "/work":
        raise ValueError("storage-binding-mismatch")
    roles = set()
    for mount in value["mounts"]:
        role = mount["role"]
        target = SCRATCH if role == "scratch" else ROOT
        data = read(target / MARKER, 65536)
        if sha(data) != mount["marker_sha256"]:
            raise ValueError("storage-volume-marker-mismatch")
        marker = json.loads(data)
        expected = {key: value[key] for key in ("registry_id", "job_id", "binding_id", "provider", "provider_sha256", "daemon_id")}
        expected.update(volume_id=mount["id"], name=mount["name"], role=role, contract="docker-job-volumes-v1")
        if marker != expected:
            raise ValueError("storage-volume-binding-mismatch")
        roles.add(role)
    if roles != ({"retained", "scratch"} if value["access"] == "read-write" else {"retained"}):
        raise ValueError("storage-binding-mismatch")
    return value


def measure(root, *, protected, maximum, nested_scratch=False, hash_files=True):
    entries, size, inventory, unknown = 0, 0, [], []
    pending = [(root, "")]
    while pending:
        directory, prefix = pending.pop()
        for item in scan(directory):
            relative = f"{prefix}/{item.name}".lstrip("/")
            if relative == MARKER:
                continue
            if nested_scratch and relative == "scratch":
                continue
            entries += 1
            if entries > maximum:
                raise ValueError("storage-entry-budget-exceeded")
            info = item.stat(follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                pending.append((pathlib.Path(item.path), relative))
                inventory.append({"path": relative, "kind": "directory"})
            elif stat.S_ISREG(info.st_mode):
                size += info.st_size
                record = {"path": relative, "kind": "file", "bytes": info.st_size}
                if protected and hash_files:
                    try:
                        record["sha256"] = sha(read(pathlib.Path(item.path)))
                    except (OSError, ValueError):
                        unknown.append(relative)
                inventory.append(record)
            else:
                size += info.st_size
                inventory.append({"path": relative, "kind": "special", "bytes": info.st_size})
                if protected:
                    unknown.append(relative)
            if protected and (relative.split("/")[0] not in POLICIES or relative.startswith("scratch/")):
                unknown.append(relative)
    return {"bytes": size, "entries": entries, "inventory": inventory if protected else [],
            "tree_sha256": sha(json_bytes(sorted(inventory, key=lambda item: item["path"]))), "unknown": unknown,
            "filesystem": filesystem(root)}


def scan(directory):
    with os.scandir(directory) as entries:
        yield from entries


def filesystem(root):
    fs = os.statvfs(root)
    return {"device": os.stat(root).st_dev, "fsid": fs.f_fsid,
            "free_bytes": fs.f_bavail * fs.f_frsize, "total_bytes": fs.f_blocks * fs.f_frsize}


def unpack_selected(request):
    expected = request["files"]
    seen = set()
    total = 0
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as archive:
        for item in archive:
            if not item.isfile() or item.name not in expected or item.name in seen:
                raise ValueError("unsupported or undeclared input entry")
            data = archive.extractfile(item).read(MAX_FILE + 1)
            total += len(data)
            if len(data) != item.size or len(data) > MAX_FILE or total > request["max_bytes"] or sha(data) != expected[item.name]["sha256"]:
                raise ValueError("input snapshot hash/size/budget mismatch")
            write_new(safe(ROOT, item.name), data, 0o555 if expected[item.name].get("executable") else 0o444)
            seen.add(item.name)
    if seen != expected.keys():
        raise ValueError("incomplete input snapshot")
    return {"ok": True, "files": len(seen), "bytes": total}


def run_diagram(request):
    operation = request["operation_id"]
    base = safe(ROOT, f"inputs/{operation}")
    options = json.loads(read(base / "request.json", 65536))
    temp = safe(SCRATCH, operation)
    temp.mkdir()
    for name in ("home", "tmp", "cache"):
        (temp / name).mkdir()
    environment = {**os.environ, "HOME": str(temp / "home"), "TMPDIR": str(temp / "tmp"), "XDG_CACHE_HOME": str(temp / "cache"),
                   "JAVA_TOOL_OPTIONS": f"-Duser.home={temp / 'home'} -Djava.io.tmpdir={temp / 'tmp'} -XX:-UsePerfData",
                   "PLANTUML_SECURITY_PROFILE": "SANDBOX"}
    engine, style, output_format = options["engine"], options["style"], options["output_format"]
    source = base / "source" / ("source.mmd" if engine == "mermaid" else "source.puml")
    styled = temp / source.name
    resources = base / "render"
    subprocess.run(["bash", str(resources / "tools/style-diagram-source.sh"), engine, style, str(source), str(styled)], env=environment, check=True)
    output_root = safe(ROOT, f"results/{operation}")
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / f"generated.{output_format}"
    if engine == "mermaid":
        configuration = temp / "puppeteer.json"
        configuration.write_bytes(json_bytes({"userDataDir": str(temp / "chrome"), "args": ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-crash-reporter", "--disable-crashpad"]}))
        command = ["mmdc", "-i", str(styled), "-o", str(output), "-c", str(resources / f"styles/mermaid/{style}.json"), "-p", str(configuration)]
        if output_format == "pdf":
            command.append("--pdfFit")
    else:
        command = ["plantuml", f"-t{output_format}", "-o", str(output_root), str(styled)]
    logs = [bytearray(), bytearray()]

    def drain(stream, target):
        for chunk in iter(lambda: stream.read(8192), b""):
            target.extend(chunk[:max(0, 65536 - len(target))])
        stream.close()

    process = subprocess.Popen(command, env=environment, cwd=temp, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    threads = [threading.Thread(target=drain, args=(stream, target), daemon=True) for stream, target in zip((process.stdout, process.stderr), logs)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 300
    pressure = None
    limits = request["limits"]
    try:
        while True:
            scratch = measure(SCRATCH, protected=False, maximum=limits["max_entries"])
            retained = measure(ROOT, protected=True, maximum=limits["max_entries"], nested_scratch=True, hash_files=False)
            if (scratch["bytes"] > limits["max_scratch_bytes"] or retained["bytes"] > limits["max_retained_bytes"]
                    or scratch["entries"] + retained["entries"] > limits["max_entries"] or retained["unknown"]
                    or scratch["filesystem"]["free_bytes"] < limits["min_free_bytes"] or time.monotonic() >= deadline):
                raise ValueError("storage-budget-or-deadline-exceeded")
            if process.poll() is not None:
                break
            try:
                process.wait(timeout=limits["monitor_interval_seconds"])
            except subprocess.TimeoutExpired:
                pass
    except (OSError, ValueError) as error:
        pressure = str(error)[:256]
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
    process.wait()
    for thread in threads:
        thread.join(timeout=5)
    if process.returncode == 0 and not pressure:
        if engine == "plantuml":
            (output_root / f"{styled.stem}.{output_format}").rename(output)
        elif output_format == "svg":
            subprocess.run(["python3", str(resources / "tools/normalize-mermaid-svg.py"), str(output)], env=environment, check=True)
    evidence = {"returncode": process.returncode, "pressure": pressure, "stdout": logs[0].decode(errors="replace"), "stderr": logs[1].decode(errors="replace")}
    write_new(safe(ROOT, f"recovery/{operation}.json"), json_bytes(evidence))
    return {"ok": process.returncode == 0 and not pressure, "result": f"results/{operation}/generated.{output_format}", "evidence": evidence}


def native_modules(operation, expected):
    base = safe(ROOT, f"inputs/{operation}/controller")
    seen = set()
    for index, path in enumerate(base.rglob("*")):
        if index >= 512 or path.is_symlink():
            raise ValueError("untrusted retained controller tree")
        if path.is_dir():
            continue
        relative = path.relative_to(base).as_posix()
        if relative not in expected or sha(read(path)) != expected[relative]:
            raise ValueError("retained controller differs from manager snapshot")
        seen.add(relative)
    if seen != expected.keys():
        raise ValueError("incomplete retained controller")
    sys.path.insert(0, str(base))
    from diavisuals import artifacts
    return artifacts


def seal_diagram(request):
    operation, product = request["operation_id"], request["product_id"]
    native = native_modules(operation, request["controller_hashes"])
    base = safe(ROOT, f"inputs/{operation}")
    options = json.loads(read(base / "request.json", 65536))
    destination = safe(ROOT, f"exports/{product}")
    destination.mkdir()
    files = []

    def retain(identity, path, data, kind, role, ownership="producer", **extra):
        if sum(item["bytes"] for item in files) + len(data) > native.MAX_PRODUCT_BYTES:
            raise ValueError("storage-export-incomplete: native product bound exceeded")
        write_new(safe(destination, path), data)
        files.append(native._file_item(identity, path, data, kind, role, ownership, **extra))

    actor, producer = native._producer_snapshot()
    actor["runtimes"] = [{"name": "diavisuals-renderer", "revision": options["image_id"]}]
    for index, (path, data) in enumerate(producer.items()):
        retain(f"producer-{index}", path, data, "evidence", "producer-identity" if path.endswith("identity.json") else "producer-source")
    engine, output_format = options["engine"], options["output_format"]
    suffix = "mmd" if engine == "mermaid" else "puml"
    source_path = f"payload/render/input/source.{suffix}"
    source = read(base / f"source/source.{suffix}")
    native._source_check(source, engine)
    retain("source", source_path, source, "input", "diagram-source", "author")
    resources = []
    for index, path in enumerate(sorted((base / "render").rglob("*"))):
        if path.is_file():
            target = "payload/render/" + path.relative_to(base / "render").as_posix()
            retain(f"resource-{index}", target, read(path), "input", "render-resource")
            resources.append(target)
    profile_path = f"payload/resources/{options['profile']}.env"
    retain("profile", profile_path, read(base / "profile.env"), "input", "render-resource")
    resources.append(profile_path)
    original = "payload/outputs/original.svg" if options["original"] else None
    if original:
        retain("original", original, read(base / "variants/original.svg"), "output", "diagram-original", "author")
    edits = []
    for index, _ in enumerate(options["edits"]):
        path = f"payload/outputs/edited-{index + 1}.svg"
        retain(f"edited-{index + 1}", path, read(base / f"variants/edited-{index + 1}.svg"), "output", "diagram-edited", "author", variant_of="original")
        edits.append(path)
    generated = f"payload/outputs/generated.{output_format}"
    data = read(safe(ROOT, f"results/{operation}/generated.{output_format}"))
    native._output_check(data, output_format)
    retain("generated", generated, data, "output", "diagram-generated")
    retain("runtime-selection", "payload/runtime-selection.json", json_bytes(options["runtime"]), "evidence", "runtime-selection")
    effective = {"profile_version": 1, "engine": engine, "family": options["family"], "style": options["style"], "profile": options["profile"],
                 "output_format": output_format, "source": source_path, "source_origin": options["source_origin"], "resources": resources,
                 "generated": generated, "original": original, "edits": edits,
                 "selection_origin": {"original": options["original"], "edits": options["edits"]},
                 "renderer": options["image_id"], "producer_identity": "payload/producer/identity.json"}
    retain("request", "payload/request.json", json_bytes(effective), "input", "request")
    retain("render-evidence", "payload/render-evidence.json", json_bytes({"renderer": options["image_id"], "returncode": 0,
           "runtime_teardown_verified": request["render_teardown_verified"], "network": "none", "consumer_mount": False,
           "source_sha256": sha(source), "selected_original": original, "selected_edits": edits}), "evidence", "render-evidence")
    # Retain all additional preparation/checker/request/recovery bytes; none can
    # silently become scratch just because the ordinary diagram format omits it.
    for index, path in enumerate(sorted(base.rglob("*"))):
        if path.is_file():
            retain(f"snapshot-{index}", "payload/job-inputs/" + path.relative_to(base).as_posix(), read(path), "input", "job-input-snapshot")
    retain("job-recovery", "payload/job-recovery.json", read(safe(ROOT, f"recovery/{operation}.json")), "evidence", "job-recovery")
    manifest = json_bytes({"schema_version": 1, "kind": "mcp-artifact-bundle", "producer": actor, "request": "request", "files": files, "dependencies": []})
    write_new(destination / "bundle.json", manifest)
    checked = native.check_diagram_bundle(ROOT, path=f"exports/{product}/bundle.json", sha256=sha(manifest))
    coverage = {}
    for item in files:
        path = item["path"]
        if path.startswith("payload/job-inputs/"):
            coverage[f"inputs/{operation}/" + path.removeprefix("payload/job-inputs/")] = item["sha256"]
        elif item["id"] == "generated":
            coverage[f"results/{operation}/generated.{output_format}"] = item["sha256"]
        elif item["id"] == "job-recovery":
            coverage[f"recovery/{operation}.json"] = item["sha256"]
        coverage[f"exports/{product}/" + path] = item["sha256"]
    coverage[f"exports/{product}/bundle.json"] = sha(manifest)
    return {"ok": True, "product_id": product, "bundle_sha256": sha(manifest), "domain": checked, "producer": actor, "coverage": coverage}


def main():
    request = json.loads(sys.stdin.buffer.readline(1024 * 1024))
    operation = request["op"]
    if operation == "capacity":
        result = {"ok": True, "filesystem": filesystem(pathlib.Path("/"))}
    elif operation == "bootstrap":
        # Manager-only creation context, never reachable through job_storage.
        for role, marker in request["markers"].items():
            target = SCRATCH if role == "scratch" else ROOT
            names = ("tmp", "home", "cache") if role == "scratch" else ("inputs", "results", "exports", "recovery", "scratch")
            resume = request.get("resume", False)
            existing = (target / MARKER).exists()
            if existing and (not resume or read(target / MARKER) != json_bytes(marker)):
                raise ValueError("refusing a different/already initialized marker")
            for item in target.iterdir():
                if item.name == MARKER and existing:
                    continue
                if item.name not in names or item.is_symlink() or not item.is_dir() or any(item.iterdir()):
                    raise ValueError("refusing to initialize a nonempty volume")
            os.chown(target, 0, 0)
            if not existing:
                write_new(target / MARKER, json_bytes(marker))
            for name in names:
                path = target / name
                path.mkdir(exist_ok=True)
                if name != "inputs":
                    os.chown(path, 65532, 65532)
            if role == "scratch":
                os.chown(target, 65532, 65532)
        result = {"ok": True}
    elif operation == "observe":
        # Authoritative manager's read-only inspection under its registry fence;
        # this is not a provider writer or receiver transfer grant.
        result = {"ok": True, "measurements": {}}
        for role, expected in request["markers"].items():
            target = SCRATCH if role == "scratch" else ROOT
            actual = read(target / MARKER, 65536)
            if sha(actual) != sha(json_bytes(expected)):
                raise ValueError("storage-volume-marker-mismatch")
            result["measurements"][role] = measure(target, protected=role == "retained", maximum=request["max_entries"])
    else:
        binding = context()
        if operation in {"put", "render", "seal"} and binding["access"] != "read-write":
            raise ValueError("storage-lease-mismatch")
        if operation == "put":
            result = unpack_selected(request)
        elif operation == "render":
            result = run_diagram(request)
        elif operation == "seal":
            result = seal_diagram(request)
        elif operation in {"check", "transfer"}:
            native = native_modules(request["operation_id"], request["controller_hashes"])
            path = f"exports/{request['product_id']}/bundle.json"
            result = native.check_diagram_bundle(ROOT, path=path, sha256=request["bundle_sha256"])
            if operation == "transfer":
                directory = safe(ROOT, f"exports/{request['product_id']}")
                with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
                    for source in sorted(directory.rglob("*")):
                        if source.is_file():
                            data = read(source)
                            info = tarfile.TarInfo(source.relative_to(directory).as_posix())
                            info.size, info.mode = len(data), 0o600
                            archive.addfile(info, io.BytesIO(data))
                return
        else:
            raise ValueError("unsupported storage worker operation")
    sys.stdout.buffer.write(json_bytes(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(str(error)[:1024] + "\n")
        raise SystemExit(1)
