"""D0 acceptance for two *published* complete identities, independent of HEAD."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile

if os.environ.get("DIAVISUALS_INSTALLED") != "1":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from diavisuals import artifacts  # noqa: E402
from diavisuals.session import owner_state  # noqa: E402
from tests.test_session_mcp import call, connect  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
REQUIREMENTS = "5634ea2e3e42122bb365992dfca9f248feb89dec"
POINTS = (
    {"version": "0.6.0", "env": "DIAVISUALS_D0_06", "wheel_sha256": "d7cc225340c65879e4a9e831d52b8fd13d7da5b7696d7430a88f16ca88035fb6",
     "producer": "sha256:1976ce1616b48ed3b502f05a59f25221b6befc3aeb1580f1f6c9c97aed772dc2",
     "alias": "diavisuals/render:v0.3.0", "image": "sha256:5a6887b372a0e1c386a7b54981d11ae1910215baeb6a12dfd0706b3e85ef0846"},
    {"version": "0.7.0", "env": "DIAVISUALS_D0_07", "wheel_sha256": "8534e9f7584242458919b6d3ba1ff0e2d2f7910259939a841854e0892c62c705",
     "producer": "sha256:f21793e74321c5bbe6b9956381ffba27980104688b19913cc02e23d002bb052d",
     "alias": "diavisuals/render:v0.7.0", "image": "sha256:6eb15796cf394cd53df723e3278800b600dbf526f7d9f79b681ae0858c8f6501"},
)
SOURCE = "flowchart LR\n A[Published source] --> B[Retained result]\n"
LONG_SOURCE = "flowchart TB\n" + "\n".join(f"N{n} --> N{n + 1}" for n in range(400))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(os.environ.get("DIAVISUALS_D0_PUBLISHED") == "1", "set DIAVISUALS_D0_PUBLISHED=1 with both prepared published points")
class PublishedD0Test(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="diavisuals-published-d0-")
        self.addCleanup(self.temporary.cleanup)
        self.base = pathlib.Path(self.temporary.name)
        self.records = {"requirements_revision": REQUIREMENTS, "test_source_sha256": sha(pathlib.Path(__file__)), "points": [], "checks": {}}
        self.points = []
        for expected in POINTS:
            python = os.environ.get(expected["env"] + "_PYTHON")
            wheel = os.environ.get(expected["env"] + "_WHEEL")
            self.assertTrue(python and wheel, f"prepare {expected['env']}_PYTHON and _WHEEL explicitly")
            self.assertEqual(sha(pathlib.Path(wheel)), expected["wheel_sha256"])
            info = json.loads(subprocess.check_output([python, "-c",
                "import json,pathlib,diavisuals; from diavisuals import registry,artifacts,session; p=pathlib.Path(diavisuals.__file__).parent; "
                "print(json.dumps({'version':diavisuals.__version__,'package':str(p),'checkout':str(registry.source_checkout()),"
                "'producer':artifacts._producer_snapshot()[0]['revision'],'sources':session.source_snapshot(p),'metadata':session.distribution_snapshot()}))"],
                text=True, env=self.clean_environment(), timeout=30))
            self.assertEqual(info["checkout"], "None")
            self.assertEqual(info["version"], expected["version"])
            self.assertEqual(info["producer"], expected["producer"])
            point = {**expected, **info, "python": python, "wheel": wheel, "cli": str(pathlib.Path(python).parent / "diavisuals")}
            self.verify_installation(point)
            self.assertEqual(self.docker("image", "inspect", "--format", "{{.Id}}", point["alias"]), point["image"])
            self.points.append(point)
            self.records["points"].append({key: point[key] for key in ("version", "wheel_sha256", "producer", "alias", "image", "sources", "metadata")})
        self.addCleanup(self.retain)

    @staticmethod
    def clean_environment():
        environment = {key: value for key, value in os.environ.items() if key not in {
            "PYTHONPATH", "DIAVISUALS_DIR", "DIAVISUALS_JOB_STORAGE_GRANT", "MCP_JOB_STORAGE_BINDING",
            "DIAVISUALS_RUNTIME_IMAGE", "DIAVISUALS_RUNTIME_EXPECTED_ID",
        }}
        return {**environment, "DOCKER_HOST": "unix:///var/run/docker.sock", "DOCKER_CONTEXT": "default"}

    def docker(self, *args):
        return subprocess.check_output(["docker", *args], env=self.clean_environment(), text=True, timeout=30).strip()

    def verify_installation(self, point):
        with zipfile.ZipFile(point["wheel"]) as wheel:
            for name in wheel.namelist():
                if (name.startswith("diavisuals/") or name.endswith(".dist-info/METADATA")) and not name.endswith("/"):
                    self.assertEqual((pathlib.Path(point["package"]).parent / name).read_bytes(), wheel.read(name), name)

    def consumer(self, name):
        root = self.base / name
        root.mkdir()
        (root / "authored.edited.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>Author owned</text></svg>')
        (root / "foreign-registration.json").write_text('{"foreign":{"command":"preserve","env":{"TOKEN":"synthetic-only"}}}')
        return root

    def guard(self, point, root, image=None):
        guard = self.base / ("guard-" + uuid.uuid4().hex)
        guard.mkdir()
        shutil.copyfile(ROOT / "tests/d0_sitecustomize.py", guard / "sitecustomize.py")
        marker = guard / "allow-consumer"
        config = guard / "guard.json"
        config.write_text(json.dumps({"engine_checkout": str(ROOT), "package_root": point["package"], "consumer": str(root),
                                     "allow_consumer": str(marker), "log": str(guard / "audit.jsonl"), "strict_rm": True, "development": False}))
        return {"PYTHONPATH": str(guard), "DIAVISUALS_TEST_GUARD": str(config), "DIAVISUALS_RUNTIME_IMAGE": image or point["image"],
                "DIAVISUALS_JOB_STORAGE_GRANT": "", "MCP_JOB_STORAGE_BINDING": "",
                "DOCKER_HOST": "unix:///var/run/docker.sock", "DOCKER_CONTEXT": "default"}, marker

    async def identity(self, connection, point, root):
        identity = await call(connection, "server_identity")
        resource = await connection.read_resource("diavisuals://server/identity")
        echoed = json.loads(resource.contents[0].text)
        self.assertEqual(identity["instance"], echoed["instance"])
        self.assertEqual(identity["loaded"], echoed["loaded"])
        self.assertEqual(identity["loaded"]["version"], point["version"])
        self.assertEqual(identity["loaded"]["mode"], "installed")
        self.assertEqual(identity["loaded"]["package_root"], point["package"])
        self.assertEqual(identity["loaded"]["startup_sources"], point["sources"])
        self.assertEqual(identity["loaded"]["startup_distribution"], point["metadata"])
        self.assertEqual(identity["binding"]["path"], str(root))
        self.assertTrue(identity["pinned_runtime_ready"], identity)
        self.assertFalse(identity["current_disk"]["drift"])
        self.assertEqual(identity["renderer"]["observed_image_id"], point["image"])
        self.assertEqual(owner_state(identity["instance"]), "alive")
        return identity

    def released(self, point, root, identity):
        self.assertEqual(owner_state(identity["instance"]), "dead")
        owner = identity["instance"]
        command = [point["cli"], "--project", str(root), "inspect-session", "--instance-id", owner["instance_id"],
                   "--pid", str(owner["pid"]), "--start-ticks", owner["start_ticks"], "--boot-id", owner["boot_id"],
                   "--pid-namespace", owner["pid_namespace"], "--daemon-id", identity["docker_daemon"]["id"]]
        result = subprocess.run(command, env=self.clean_environment(), text=True, capture_output=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        value = json.loads(result.stdout)
        self.assertTrue(value["resources_released"], value)
        return value

    async def wait_worker(self, connection, task):
        for _ in range(150):
            identity = await call(connection, "server_identity")
            jobs = identity["lifecycle"]["jobs"]
            if jobs and jobs[0]["container_id"]:
                return identity
            self.assertFalse(task.done(), "render completed before its busy identity was observed")
            await asyncio.sleep(0.02)
        self.fail("native worker identity unavailable")

    def retain(self):
        try:
            for point in self.points:
                self.verify_installation(point)
                self.assertEqual(self.docker("image", "inspect", "--format", "{{.Id}}", point["alias"]), point["image"])
            for log in self.base.glob("guard-*/audit.jsonl"):
                events = [json.loads(line) for line in log.read_text().splitlines()]
                self.assertFalse([item for item in events if item["event"].startswith("denied-")], events)
            self.records["checks"]["prepared_packages_and_aliases_unchanged"] = True
        finally:
            # Preserve the observations even when a final immutability/guard
            # assertion fails; the unittest result remains the gate verdict.
            evidence = os.environ.get("DIAVISUALS_D0_PUBLISHED_EVIDENCE")
            if evidence:
                destination = pathlib.Path(evidence) / ("published-pair-" + uuid.uuid4().hex)
                shutil.copytree(self.base, destination / "payload")
                (destination / "evidence.json").write_text(json.dumps(self.records, indent=2, sort_keys=True) + "\n")
                print(f"Published D0 evidence: {destination}")

    def test_full_published_identities_reconnect_rollback_and_independent_busy_release(self):
        async def exercise():
            first, second = self.points
            root, other_root = self.consumer("activation"), self.consumer("independent")
            authored = {path.name: sha(path) for path in root.iterdir()}
            environment, allow_other = self.guard(second, other_root)
            stages = []
            async with connect(second["python"], other_root, environment=environment) as other:
                other_identity = await self.identity(other, second, other_root)
                allow_other.touch()
                for index, point in enumerate((first, first, second, first)):
                    environment, allow = self.guard(point, root)
                    async with connect(point["python"], root, environment=environment) as active:
                        before = await self.identity(active, point, root)
                        allow.touch()
                        for engine, source in (("mermaid", SOURCE), ("plantuml", "@startuml\nPublished -> Retained : Ready\n@enduml\n")):
                            rendered = await call(active, "render_diagram_text", {"diagram_text": source, "engine": engine,
                                                  "output_path": f"{engine}.svg", "include_data": False})
                            self.assertEqual(rendered["runtime"]["image_id"], point["image"])
                            artifacts._svg_check((root / f"{engine}.svg").read_bytes())
                        product = await call(active, "export_diagram_bundle", {"diagram_text": SOURCE, "bundle_id": f"stage-{index}",
                                              "original_path": "mermaid.svg", "edited_paths": ["authored.edited.svg"]})
                        self.assertEqual(product["producer"]["version"], point["version"])
                        await call(active, "check_diagram_bundle", product["bundle"])
                        self.assertEqual((await call(active, "server_identity"))["instance"], before["instance"])
                        stages.append({"version": point["version"], "identity": before, "svg_sha256": sha(root / "mermaid.svg"), "bundle": product["bundle"]})
                        for retained in stages:
                            await call(active, "check_diagram_bundle", retained["bundle"])
                        await call(active, "release_session", {"expected_instance_id": before["instance"]["instance_id"]})
                    self.released(point, root, before)
                    self.assertEqual((await call(other, "server_identity"))["instance"], other_identity["instance"])
                    self.assertEqual({name: sha(root / name) for name in authored}, authored)
                self.assertNotEqual(stages[0]["identity"]["instance"]["instance_id"], stages[1]["identity"]["instance"]["instance_id"])
                self.assertEqual(stages[0]["identity"]["loaded"], stages[1]["identity"]["loaded"])
                self.assertEqual(stages[0]["svg_sha256"], stages[3]["svg_sha256"])
                await call(other, "release_session", {"expected_instance_id": other_identity["instance"]["instance_id"]})
            self.released(second, other_root, other_identity)
            self.records["checks"]["coexistence_reconnect_A_B_A"] = stages
            self.records["checks"]["retained_bundles_valid_after_each_transition"] = True

            busy_checks = []
            for point, peer in ((first, second), (second, first)):
                worker_root, peer_root = self.consumer("worker-" + point["version"]), self.consumer("peer-" + point["version"])
                worker_env, worker_allow = self.guard(point, worker_root)
                peer_env, peer_allow = self.guard(peer, peer_root)
                async with connect(point["python"], worker_root, environment=worker_env) as worker:
                    identity = await self.identity(worker, point, worker_root)
                    worker_allow.touch()
                    paused = False
                    try:
                        async with connect(peer["python"], peer_root, environment=peer_env) as other:
                            peer_identity = await self.identity(other, peer, peer_root)
                            peer_allow.touch()
                            task = asyncio.create_task(call(worker, "render_diagram_text", {"diagram_text": LONG_SOURCE, "include_data": False}))
                            busy = await self.wait_worker(worker, task)
                            cid = busy["lifecycle"]["jobs"][0]["container_id"]
                            self.docker("pause", cid)
                            paused = True
                            refused = await worker.call_tool("release_session", {"expected_instance_id": identity["instance"]["instance_id"]})
                            self.assertTrue(refused.is_error)
                            await call(other, "release_session", {"expected_instance_id": peer_identity["instance"]["instance_id"]})
                        self.released(peer, peer_root, peer_identity)
                        self.assertEqual(self.docker("container", "inspect", "--format", "{{.State.Paused}}", cid), "true")
                        self.assertEqual((await call(worker, "server_identity"))["lifecycle"]["state"], "busy")
                    finally:
                        if paused:
                            self.docker("unpause", cid)
                    rendered = await task
                    self.assertTrue(rendered["result"]["cleanup"]["ok"])
                    self.assertEqual((await call(worker, "server_identity"))["instance"], identity["instance"])
                    await call(worker, "release_session", {"expected_instance_id": identity["instance"]["instance_id"]})
                retired = self.released(point, worker_root, identity)
                busy_checks.append({"version": point["version"], "busy": busy, "other_release": peer_identity["instance"], "last_release": retired})

                for selection in ("sha256:" + "0" * 64, peer["alias"]):
                    missing_root = self.consumer("refusal-" + uuid.uuid4().hex)
                    environment, allow = self.guard(point, missing_root, selection)
                    if selection == peer["alias"]:
                        environment["DIAVISUALS_RUNTIME_EXPECTED_ID"] = point["image"]
                    async with connect(point["python"], missing_root, environment=environment) as refused:
                        observed = await call(refused, "server_identity")
                        self.assertEqual(observed["loaded"]["version"], point["version"])
                        self.assertFalse(observed["renderer"]["ok"])
                        allow.touch()
                        response = await refused.call_tool("render_diagram_text", {"diagram_text": SOURCE})
                        self.assertTrue(response.is_error)
                    self.released(point, missing_root, observed)
                    self.assertEqual({path.name for path in missing_root.iterdir()}, {"authored.edited.svg", "foreign-registration.json"})
            self.records["checks"]["mixed_busy_and_last_release"] = busy_checks
            self.records["checks"]["missing_and_wrong_runtime_refused"] = True
            self.records["checks"]["two_complete_published_D0_points"] = [point["version"] for point in self.points]

        asyncio.run(exercise())
