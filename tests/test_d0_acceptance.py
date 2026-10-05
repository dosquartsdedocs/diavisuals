"""Real native D0 acceptance. No Docker/alias wrapper and no relabelled releases."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile

if os.environ.get("DIAVISUALS_INSTALLED") != "1":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from diavisuals import __version__, registry  # noqa: E402
from diavisuals.session import distribution_snapshot, owner_state, source_snapshot  # noqa: E402
from tests.test_session_mcp import call, connect  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGE = "sha256:5a6887b372a0e1c386a7b54981d11ae1910215baeb6a12dfd0706b3e85ef0846"
OLD_WHEEL_SHA = "f52e20f20f1fb3a2418f07adb8d6a68a5567d0c321fb7c0ccc0f4db04917b96b"
SOURCE = "flowchart LR\n A[Prepared code] --> B[Retained authorship]\n"
LONG_SOURCE = "flowchart TB\n" + "\n".join(f"N{n} --> N{n + 1}" for n in range(400))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_snapshot(root):
    files = [{"path": path.relative_to(root).as_posix(), "sha256": digest(path)} for path in sorted(root.rglob("*"))
             if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"]
    return {"sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(), "files": len(files)}


@unittest.skipUnless(os.environ.get("DIAVISUALS_DOCKER_SMOKE") == "1", "set DIAVISUALS_DOCKER_SMOKE=1")
class D0AcceptanceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="diavisuals-d0-")
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name)
        self.records = {"version": __version__, "checks": {}, "observations": [], "docker_executable": shutil.which("docker")}
        self.assertTrue(self.records["docker_executable"])
        with pathlib.Path(self.records["docker_executable"]).open("rb") as binary:
            self.assertEqual(binary.read(4), b"\x7fELF", "real Linux Docker binary required, not a test wrapper")
        self.assertEqual(self.docker("image", "inspect", "--format", "{{.Id}}", "diavisuals/render:v0.3.0"), IMAGE)
        self.before_sources = source_snapshot(pathlib.Path(registry.__file__).parent)
        self.before_package = package_snapshot(pathlib.Path(registry.__file__).parent)
        self.before_metadata = distribution_snapshot()
        self.addCleanup(self.retain)
        self.old_wheel = None

    def docker(self, *args):
        return subprocess.check_output([self.records["docker_executable"], *args], text=True, timeout=30).strip()

    def consumer(self, name):
        root = self.base / name
        root.mkdir()
        (root / "authored.edited.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>Author owned</text></svg>\n')
        (root / "foreign-registration.json").write_text('{"foreign":{"command":"preserve","env":{"TOKEN":"synthetic-secret"}}}\n')
        return root

    def guard(self, root, *, old=False):
        directory = self.base / ("guard-" + uuid.uuid4().hex)
        directory.mkdir()
        shutil.copyfile(ROOT / "tests/d0_sitecustomize.py", directory / "sitecustomize.py")
        marker = directory / "allow-consumer"
        configuration = {"engine_checkout": str(ROOT), "package_root": str(pathlib.Path(registry.__file__).parent),
                         "consumer": str(root), "allow_consumer": str(marker), "log": str(directory / "audit.jsonl"),
                         "strict_rm": not old, "development": os.environ.get("DIAVISUALS_INSTALLED") != "1" and not old}
        if old:
            configuration["package_root"] = str(self.old_package)
        path = directory / "guard.json"
        path.write_text(json.dumps(configuration))
        return {"PYTHONPATH": str(directory), "DIAVISUALS_TEST_GUARD": str(path),
                "DIAVISUALS_RUNTIME_IMAGE": IMAGE, "DOCKER_HOST": "unix:///var/run/docker.sock", "DOCKER_CONTEXT": "default"}, marker

    def retain(self):
        self.assertEqual(source_snapshot(pathlib.Path(registry.__file__).parent), self.before_sources)
        self.assertEqual(package_snapshot(pathlib.Path(registry.__file__).parent), self.before_package)
        self.assertEqual(distribution_snapshot(), self.before_metadata)
        self.assertEqual(self.docker("image", "inspect", "--format", "{{.Id}}", "diavisuals/render:v0.3.0"), IMAGE)
        if self.old_wheel:
            self.verify_old_installation()
            self.records["checks"]["old_prepared_bytes_unchanged"] = True
        self.records["checks"]["current_prepared_sources_metadata_unchanged"] = True
        self.records["prepared_package"] = self.before_package
        for log in self.base.glob("guard-*/audit.jsonl"):
            events = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertFalse([event for event in events if event["event"].startswith("denied-")], events)
        destination = os.environ.get("DIAVISUALS_D0_EVIDENCE")
        if destination:
            target = pathlib.Path(destination) / (self._testMethodName + "-" + uuid.uuid4().hex)
            shutil.copytree(self.base, target / "payload")
            (target / "evidence.json").write_text(json.dumps(self.records, indent=2, sort_keys=True) + "\n")
            print(f"D0 evidence: {target}")

    def verify_old_installation(self):
        self.assertEqual(digest(pathlib.Path(self.old_wheel)), OLD_WHEEL_SHA)
        with zipfile.ZipFile(self.old_wheel) as wheel:
            for name in wheel.namelist():
                if (name.startswith("diavisuals/") or name.endswith(".dist-info/METADATA")) and not name.endswith("/"):
                    self.assertEqual((self.old_package.parent / name).read_bytes(), wheel.read(name), name)

    async def wait_worker(self, server, task):
        for _ in range(100):
            state = await call(server, "server_identity")
            jobs = state["lifecycle"]["jobs"]
            if jobs and jobs[0]["container_id"]:
                return state
            if task.done():
                self.fail(f"render finished before busy observation: {task.result()}")
            await asyncio.sleep(0.02)
        self.fail("owned worker did not become observable")

    def test_offline_busy_detach_crash_exact_orphan_release_and_reactivation(self):
        async def exercise():
            first_root, worker_root = self.consumer("first"), self.consumer("worker")
            guard_a, marker_a = self.guard(first_root)
            guard_b, marker_b = self.guard(worker_root)
            async with connect(sys.executable, worker_root, environment=guard_b) as worker:
                worker_identity = await call(worker, "server_identity")
                self.assertTrue(worker_identity["pinned_runtime_ready"], worker_identity)
                marker_b.touch()
                async with connect(sys.executable, first_root, environment=guard_a) as first:
                    first_identity = await call(first, "server_identity")
                    marker_a.touch()
                    task = asyncio.create_task(call(worker, "render_diagram_text", {"diagram_text": LONG_SOURCE, "include_data": False}))
                    busy = await self.wait_worker(worker, task)
                    rejected = await worker.call_tool("release_session", {"expected_instance_id": busy["instance"]["instance_id"]})
                    self.assertTrue(rejected.isError)
                    live_release = registry.session_containers(worker_root, owner=busy["instance"], daemon_id=busy["docker_daemon"]["id"],
                                                               release_ids=[busy["lifecycle"]["jobs"][0]["container_id"]])
                    self.assertFalse(live_release["ok"])
                    self.assertEqual(live_release["owner_state"], "alive")
                    await call(first, "release_session", {"expected_instance_id": first_identity["instance"]["instance_id"]})
                self.assertEqual(owner_state(first_identity["instance"]), "dead")
                rendered = await task
                self.assertEqual(rendered["result"]["ownership"]["instance_id"], busy["instance"]["instance_id"])
                self.assertEqual((await call(worker, "server_identity"))["instance"], worker_identity["instance"])
                self.assertTrue(rendered["result"]["cleanup"]["ok"])
                self.records["observations"].extend([first_identity, busy, rendered["result"]["ownership"]])
                await call(worker, "release_session", {"expected_instance_id": worker_identity["instance"]["instance_id"]})
            self.assertEqual(owner_state(worker_identity["instance"]), "dead")
            stopped = registry.session_containers(worker_root, owner=worker_identity["instance"], daemon_id=worker_identity["docker_daemon"]["id"])
            self.assertTrue(stopped["resources_released"], stopped)
            self.records["checks"]["independent_busy_detach_and_last_release"] = stopped

            # A paused, exact owned worker makes the crash gate deterministic;
            # it is real renderer execution, not a replacement/synthetic engine.
            crash_root = self.consumer("crash")
            guard, marker = self.guard(crash_root)
            cid = None
            try:
                async with connect(sys.executable, crash_root, environment=guard) as crashing:
                    identity = await call(crashing, "server_identity")
                    marker.touch()
                    task = asyncio.create_task(call(crashing, "render_diagram_text", {"diagram_text": LONG_SOURCE, "include_data": False}))
                    busy = await self.wait_worker(crashing, task)
                    cid = busy["lifecycle"]["jobs"][0]["container_id"]
                    self.docker("pause", cid)
                    os.kill(busy["instance"]["pid"], signal.SIGKILL)
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(task, timeout=10)
                self.assertEqual(owner_state(busy["instance"]), "dead")
                wrong_namespace = {**busy["instance"], "pid_namespace": "pid:[0]"}
                refused = registry.session_containers(crash_root, owner=wrong_namespace, daemon_id=busy["docker_daemon"]["id"], release_ids=[cid])
                self.assertFalse(refused["ok"])
                foreign = registry.session_containers(first_root, owner=busy["instance"], daemon_id=busy["docker_daemon"]["id"], release_ids=[cid])
                self.assertFalse(foreign["ok"])
                released = registry.session_containers(crash_root, owner=busy["instance"], daemon_id=busy["docker_daemon"]["id"], release_ids=[cid])
                self.assertTrue(released["ok"] and released["resources_released"], released)
                self.records["checks"]["crash_recovery"] = {"identity": busy, "refused_wrong_namespace": refused, "released": released}
                cid = None
            finally:
                if cid:
                    self.docker("container", "rm", "--force", cid)
            guard, marker = self.guard(crash_root)
            async with connect(sys.executable, crash_root, environment=guard) as reactivated:
                current = await call(reactivated, "server_identity")
                self.assertNotEqual(current["instance"]["instance_id"], identity["instance"]["instance_id"])
                marker.touch()
                self.assertTrue((await call(reactivated, "render_diagram_text", {"diagram_text": SOURCE, "include_data": False}))["ok"])
                self.records["checks"]["reactivated"] = current

        asyncio.run(exercise())

    def test_actual_0_5_0_coexistence_reconnect_rollback_and_disk_drift(self):
        old_python = os.environ.get("DIAVISUALS_PREVIOUS_PYTHON")
        old_wheel = os.environ.get("DIAVISUALS_PREVIOUS_WHEEL")
        if not old_python or not old_wheel:
            self.skipTest("provide verified published 0.5.0 wheel and independent installed interpreter for the two-release gate")
        self.assertEqual(digest(pathlib.Path(old_wheel)), OLD_WHEEL_SHA)
        old_info = json.loads(subprocess.check_output([old_python, "-c", "import json,pathlib,diavisuals; from diavisuals import registry; print(json.dumps({'version':diavisuals.__version__,'package':str(pathlib.Path(diavisuals.__file__).parent),'checkout':str(registry.source_checkout())}))"], text=True))
        self.assertEqual(old_info["version"], "0.5.0")
        self.assertEqual(old_info["checkout"], "None")
        self.old_package = pathlib.Path(old_info["package"])
        self.old_wheel = old_wheel
        self.verify_old_installation()

        async def exercise():
            root, other_root = self.consumer("activation"), self.consumer("unaffected")
            authored = {path.name: digest(path) for path in root.iterdir()}
            guard_other, marker_other = self.guard(other_root)
            stages = []
            async with connect(sys.executable, other_root, environment=guard_other) as other:
                other_before = await call(other, "server_identity")
                marker_other.touch()
                for index, (python, version) in enumerate(((old_python, "0.5.0"), (sys.executable, __version__), (old_python, "0.5.0"))):
                    old = version == "0.5.0"
                    guard, marker = self.guard(root, old=old)
                    async with connect(python, root, environment=guard) as active:
                        tools = {item.name for item in (await active.list_tools()).tools}
                        if old:
                            self.assertNotIn("server_identity", tools)
                            identity = {"partial": True, "version": (await call(active, "factory_manifest"))["version"],
                                        "missing": "published 0.5.0 has no live loaded-package/instance identity"}
                        else:
                            identity = await call(active, "server_identity")
                            self.assertEqual(identity["loaded"]["version"], version)
                        marker.touch()
                        rendered = await call(active, "render_diagram_text", {"diagram_text": SOURCE, "output_path": "original.svg", "include_data": False})
                        self.assertTrue(rendered["ok"])
                        bundle = await call(active, "export_diagram_bundle", {"diagram_text": SOURCE, "bundle_id": f"stage-{index}",
                                                                             "original_path": "original.svg", "edited_paths": ["authored.edited.svg"]})
                        self.assertEqual(bundle["producer"]["version"], version)
                        await call(active, "check_diagram_bundle", bundle["bundle"])
                        stages.append({"version": version, "identity": identity, "svg_sha256": digest(root / "original.svg"), "bundle": bundle["bundle"]})
                    self.assertEqual((await call(other, "server_identity"))["instance"], other_before["instance"])
                    self.assertEqual({name: digest(root / name) for name in authored}, authored)
                self.assertEqual(len({stage["svg_sha256"] for stage in stages}), 1)
                self.records["checks"]["actual_version_A_B_A"] = stages
                self.records["checks"]["two_complete_D0_identity_releases"] = {"passed": False, "blocker": "0.5.0 is a real legacy release but lacks native live identity; no shim or relabelled copy substitutes for it"}

            # Atomic replacement avoids modifying uv's hardlinked shared cache.
            if os.environ.get("DIAVISUALS_INSTALLED") != "1":
                self.records["checks"]["metadata_drift"] = {"deferred": "real metadata mutation is confined to the isolated non-editable install gates"}
                return
            metadata = pathlib.Path(distribution_snapshot()["root"]) / "METADATA"
            original = metadata.read_bytes()
            original_stat = metadata.stat()
            guard, marker = self.guard(root)
            async with connect(sys.executable, root, environment=guard) as running:
                before = await call(running, "server_identity")
                changed = metadata.with_name("METADATA.d0-test-" + uuid.uuid4().hex)
                try:
                    with changed.open("xb") as output:
                        output.write(original.replace(f"Version: {__version__}\n".encode(), b"Version: 99.99.99\n"))
                    changed.chmod(original_stat.st_mode & 0o777)
                    os.replace(changed, metadata)
                    after = await call(running, "server_identity")
                    self.assertEqual(before["instance"], after["instance"])
                    self.assertEqual(before["loaded"], after["loaded"])
                    self.assertTrue(after["current_disk"]["drift"])
                    self.assertFalse(after["pinned_runtime_ready"])
                    self.records["checks"]["metadata_drift"] = {"before": before, "after": after}
                finally:
                    with changed.open("xb") as output:
                        output.write(original)
                    changed.chmod(original_stat.st_mode & 0o777)
                    os.replace(changed, metadata)
                    os.utime(metadata, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
                self.assertFalse((await call(running, "server_identity"))["current_disk"]["drift"])

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
