from __future__ import annotations

import asyncio
import copy
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from unittest import mock

if os.environ.get("DIAVISUALS_INSTALLED") != "1":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from diavisuals import artifacts  # noqa: E402
from diavisuals import job_storage as storage  # noqa: E402
from tests.job_storage_reference import pinned_reference  # noqa: E402


@unittest.skipUnless(os.environ.get("DIAVISUALS_W1_DOCKER") == "1", "set DIAVISUALS_W1_DOCKER=1")
class StorageDockerTests(unittest.TestCase):
    def setUp(self):
        # Keep external ledgers on failure, so no sole-copy job loses recovery.
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="diavisuals-w1-", dir="/tmp/opencode" if pathlib.Path("/tmp/opencode").is_dir() else None))
        self.consumer = self.root / "consumer"
        self.consumer.mkdir()
        info = storage.Registry.create(self.root / "registry", self.consumer)
        self.manager = storage.Registry(info["admin_grant"])
        self.jobs = []
        self.receiver_parent = pathlib.Path(__file__).resolve().parents[1] / ".w1-receivers"
        self.receiver_parent.mkdir(exist_ok=True)
        self.receiver = self.receiver_parent / self.root.name
        self.receiver.mkdir()
        self.wire = []
        context = pinned_reference()
        self.reference, _ = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        original_binding = storage.Registry.binding

        def observed_binding(manager, job, lease, readonly):
            value = original_binding(manager, job, lease, readonly)
            self.record_wire(value)
            return value

        patcher = mock.patch.object(storage.Registry, "binding", observed_binding)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.report_or_clean)

    def record_wire(self, value):
        if self.reference:
            self.reference.validate(value)
        self.wire.append(copy.deepcopy(value))

    def report_or_clean(self):
        with self.manager.locked() as state:
            if os.environ.get("DIAVISUALS_W1_EVIDENCE"):
                destination = pathlib.Path(os.environ["DIAVISUALS_W1_EVIDENCE"]) / self._testMethodName
                destination.mkdir(parents=True, exist_ok=False)
                receipts = {"profile": "diavisuals-private-directory-v1", "version": storage.__version__, "reference": storage.REFERENCE,
                            "provider_sha256": self.manager.descriptor_sha, "producer": artifacts._producer_snapshot()[0],
                            "runtime": state["runtime"], "states": [self.manager.state_view(state, job) for job in state["jobs"].values()],
                            "retentions": [item["retention"] for job in state["jobs"].values() for item in job["products"] if "retention" in item],
                            "capacity": [job.get("capacity") for job in state["jobs"].values()], "wire": self.wire, "test": self._testMethodName}
                (destination / "receipt.json").write_bytes(storage.json_bytes(receipts))
                if any(self.receiver.iterdir()):
                    shutil.copytree(self.receiver, destination / "receiver")
            if all(job["phase"] == "released" for job in state["jobs"].values()):
                shutil.rmtree(self.root)
                shutil.rmtree(self.receiver)
            else:
                print(f"W1 recovery ledger retained: {self.root / 'registry/admin.json'}", file=sys.stderr)

    def allocate(self):
        allocated = self.manager.allocate(self.consumer)
        self.jobs.append(allocated["job_id"])
        return allocated["job_id"], storage.Registry(allocated["grant"], self.consumer)

    def control(self, client, operation):
        state = client.status()
        request = {"kind": "gacontext.job-storage-request", "schema_version": 1, "operation": operation,
                   **{key: state[key] for key in ("registry_id", "job_id")}}
        if operation != "status":
            request.update(expected_revision=state["revision"], expected_epoch=state["epoch"])
        result = client.control(request)
        self.record_wire(result)
        return result

    def retire(self, job_id):
        plan = self.manager.plan_release(job_id)
        return self.manager.release(plan["plan_sha256"], plan["plan"]["expected_revision"], plan["plan"]["expected_epoch"], job_id)

    def discard_synthetic(self, job_id):
        # Explicit test-author decision, scoped to the exact measured synthetic tree.
        with self.manager.locked() as state:
            job = self.manager.job(state, job_id)
            self.manager.refresh(state, job)
        observed = self.manager.status(job_id)
        self.manager.discard(observed["protected_inventory"]["tree_sha256"], observed["revision"], observed["epoch"],
                             "test-author discard of this exact synthetic fixture", confirm=True, job_id=job_id)
        return self.retire(job_id)

    def test_real_render_seal_pending_scratch_retirement_reopen_and_exact_cleanup(self):
        job_id, client = self.allocate()
        before = set(self.consumer.iterdir())
        for engine, output_format, source in ((engine, output_format, source) for engine, source in (
            ("mermaid", "flowchart LR\n A[Retained] --> B[Verified]\n"), ("plantuml", "@startuml\nAlice -> Bob : retained\n@enduml\n"))
            for output_format in ("svg", "png", "pdf")):
            state = client.status()
            result = client.render(state["revision"], state["epoch"], diagram_text=source, engine=engine, output_format=output_format)
            self.assertTrue(result["ok"], result)
            sealed = self.control(client, "seal")
            self.assertFalse(sealed["holds"], sealed)
            same = self.control(client, "seal")
            self.assertEqual(same["revision"], sealed["revision"])
        self.assertEqual(set(self.consumer.iterdir()), before)
        self.assertEqual(len(sealed["products"]), 6)
        closed = self.control(client, "quiesce")
        self.assertEqual(closed["phase"], "closed")
        retired = self.retire(job_id)
        self.assertEqual({item["role"]: item["state"] for item in retired["volumes"]}, {"scratch": "absent", "retained": "verified"})
        old = next(item["id"] for item in retired["volumes"] if item["role"] == "scratch")
        reopened = self.manager.reopen(retired["revision"], retired["epoch"], job_id)
        self.assertNotEqual(next(item["id"] for item in reopened["volumes"] if item["role"] == "scratch"), old)
        self.assertGreater(reopened["epoch"], retired["epoch"])
        self.control(client, "quiesce")
        final = self.discard_synthetic(job_id)
        self.assertEqual(final["phase"], "released")
        self.assertTrue(all(item["state"] == "absent" for item in final["volumes"]))

    def test_directory_retention_after_scratch_removal_tamper_and_relocation(self):
        job_id, client = self.allocate()
        original = b'<svg xmlns="http://www.w3.org/2000/svg"><text x="1" y="20">Original</text></svg>'
        (self.consumer / "original.svg").write_bytes(original)
        (self.consumer / "edited.svg").write_bytes(original.replace(b"Original", b"Reviewed"))
        state = client.status()
        rendered = client.render(state["revision"], state["epoch"], diagram_text="flowchart LR\n A-->B\n", original_path="original.svg", edited_paths=["edited.svg"])
        self.assertTrue(rendered["ok"], rendered)
        state = self.control(client, "seal")
        product = state["products"][0]
        self.control(client, "quiesce")
        self.retire(job_id)
        policy = self.manager.register_receiver(self.receiver, "diagrams")
        # A receiver collision cannot acknowledge a product or replace author data.
        (self.receiver / "diagrams").mkdir()
        (self.receiver / "diagrams/selected").write_bytes(b"author collision")
        state = client.status()
        with self.assertRaises(ValueError):
            self.manager.deliver(product["id"], policy["receiver_binding_id"], "diagrams/selected", state["revision"], state["epoch"], job_id)
        self.assertEqual((self.receiver / "diagrams/selected").read_bytes(), b"author collision")
        self.assertEqual(client.status()["products"][0]["disposition"], "pending")
        state = client.status()
        receive = storage.job_io.receive_directory
        with mock.patch.object(storage.job_io, "receive_directory", side_effect=lambda stream, *args: receive(io.BytesIO(stream.read(1024)), *args)):
            with self.assertRaises((ValueError, EOFError, tarfile.TarError)):
                self.manager.deliver(product["id"], policy["receiver_binding_id"], "diagrams/partial", state["revision"], state["epoch"], job_id)
        self.assertEqual(client.status()["products"][0]["disposition"], "pending")
        self.assertFalse((self.receiver / "diagrams/partial").exists())
        state = client.status()
        entered, resume, result = threading.Event(), threading.Event(), {}

        def suspended(stream, *args):
            entered.set()
            self.assertTrue(resume.wait(30))
            return receive(stream, *args)

        def deliver():
            try:
                result["value"] = self.manager.deliver(product["id"], policy["receiver_binding_id"], "diagrams/complete", state["revision"], state["epoch"], job_id)
            except BaseException as error:
                result["error"] = error

        with mock.patch.object(storage.job_io, "receive_directory", side_effect=suspended):
            thread = threading.Thread(target=deliver)
            thread.start()
            try:
                self.assertTrue(entered.wait(30))
                plan = self.manager.plan_release(job_id)
                self.assertFalse(plan["plan"]["all_releasable"])
                with self.assertRaises(storage.StorageError):
                    self.manager.release(plan["plan_sha256"], plan["plan"]["expected_revision"], plan["plan"]["expected_epoch"], job_id)
            finally:
                resume.set()
                thread.join(timeout=40)
        self.assertFalse(thread.is_alive())
        if "error" in result:
            raise result["error"]
        delivered = result["value"]
        self.record_wire(delivered["retention"])
        output = self.receiver / "diagrams/complete/payload/outputs/generated.svg"
        before = output.read_bytes()
        output.write_bytes(before + b"tampered")
        plan = self.manager.plan_release(job_id)
        self.assertFalse(plan["plan"]["all_releasable"])
        self.assertEqual(next(item["action"] for item in plan["plan"]["volumes"] if item["role"] == "retained"), "blocked")
        output.write_bytes(before)
        (self.receiver / "diagrams/complete").rename(self.receiver / "diagrams/unavailable")
        self.assertFalse(self.manager.plan_release(job_id)["plan"]["all_releasable"])
        (self.receiver / "diagrams/unavailable").rename(self.receiver / "diagrams/complete")
        plan = self.manager.plan_release(job_id)
        output.write_bytes(before + b"changed after plan")
        with self.assertRaises(storage.StorageError):
            self.manager.release(plan["plan_sha256"], plan["plan"]["expected_revision"], plan["plan"]["expected_epoch"], job_id)
        self.assertEqual(next(item["state"] for item in client.status()["volumes"] if item["role"] == "retained"), "verified")
        output.write_bytes(before)
        final = self.retire(job_id)
        self.assertEqual(final["phase"], "released")
        relocated = self.receiver / "relocated"
        (self.receiver / "diagrams").rename(relocated)
        with mock.patch.object(storage.core, "run", side_effect=AssertionError("retained check launched a runtime")):
            self.assertTrue(artifacts.check_diagram_bundle(self.receiver, path="relocated/complete/bundle.json", sha256=product["bundle_sha256"])["ok"])
        self.assertIn(b"Reviewed", (relocated / "complete/payload/outputs/edited-1.svg").read_bytes())
        self.record_wire(final)

    def test_status_is_readonly_and_two_actual_clients_preserve_their_interests(self):
        job_id, client = self.allocate()
        source = ("import sys,json; from diavisuals.job_storage import Registry; "
                  "m=Registry(sys.argv[1],sys.argv[2]); lease=m.client_attach(); print(json.dumps(lease),flush=True); "
                  "sys.stdin.readline(); print(json.dumps(m.client_detach(lease['lease_id'])),flush=True)")
        processes = [subprocess.Popen([sys.executable, "-c", source, str(self.manager.root / (job_id + ".grant.json")), str(self.consumer)],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        try:
            interests = [json.loads(process.stdout.readline()) for process in processes]
            self.assertNotEqual(interests[0]["lease_id"], interests[1]["lease_id"])
            before = (self.manager.root / "ledger.json").read_bytes()
            with mock.patch.object(client, "worker", side_effect=AssertionError("status mutated Docker")):
                self.control(client, "status")
            self.assertEqual((self.manager.root / "ledger.json").read_bytes(), before)
            processes[0].stdin.write("detach\n")
            processes[0].stdin.flush()
            first = json.loads(processes[0].stdout.readline())
            self.assertEqual(first["phase"], "open")
            self.assertTrue(any(item["state"] == "active" for item in first["leases"]))
            processes[1].stdin.write("detach\n")
            processes[1].stdin.flush()
            last = json.loads(processes[1].stdout.readline())
            self.assertEqual(last["phase"], "released")
            self.assertTrue(all(item["state"] == "absent" for item in last["volumes"]))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.wait(timeout=40)
                for stream in (process.stdin, process.stdout, process.stderr):
                    stream.close()

    def test_real_controller_crash_keeps_sources_until_scoped_recovery_and_discard(self):
        job_id, client = self.allocate()
        source = ("import sys; from diavisuals.job_storage import Registry; "
                  "m=Registry(sys.argv[1],sys.argv[2]); s=m.status(); "
                  "m.render(s['revision'],s['epoch'],diagram_text='flowchart LR\\n'+'\\n'.join(f'A{i}-->A{i+1}' for i in range(200)))")
        process = subprocess.Popen([sys.executable, "-c", source, str(self.manager.root / (job_id + ".grant.json")), str(self.consumer)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline, found = time.monotonic() + 60, False
            while time.monotonic() < deadline and process.poll() is None:
                with self.manager.locked() as state:
                    job = self.manager.job(state, job_id)
                    found = any(item["worker"] and item["worker"]["operation"] == "render" and item["worker"]["id"] for item in job["leases"])
                if found:
                    break
                time.sleep(0.05)
            self.assertTrue(found, "real render worker was not observed")
            busy = self.control(client, "quiesce")
            self.assertEqual(busy["phase"], "draining")
            self.assertEqual(busy["activity"], "busy")
            process.kill()
            process.wait(timeout=10)
            self.assertEqual(client.status()["activity"], "unknown")
            result = self.manager.recover(job_id)
            self.assertTrue(result["recovered_leases"])
            self.assertEqual(result["state"]["phase"], "closed")
            self.assertTrue(result["state"]["holds"])
            pending = self.retire(job_id)
            self.assertEqual(next(item["state"] for item in pending["volumes"] if item["role"] == "retained"), "verified")
            self.assertEqual(self.discard_synthetic(job_id)["phase"], "released")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            process.stdout.close()
            process.stderr.close()

    def test_two_consumers_budget_and_foreign_stopped_attachment(self):
        first, client = self.allocate()
        other = self.root / "other-consumer"
        other.mkdir()
        allocated = self.manager.allocate(other)
        second = allocated["job_id"]
        other_client = storage.Registry(allocated["grant"], other)
        with self.assertRaises(storage.StorageError):
            storage.Registry(allocated["grant"], self.consumer).status()
        with self.assertRaises(storage.StorageError):
            client.control({"kind": "gacontext.job-storage-request", "schema_version": 1, "operation": "status",
                            "registry_id": client.grant["registry_id"], "job_id": second})
        with self.assertRaises(storage.StorageError):
            self.manager.allocate(self.consumer)
        self.control(client, "quiesce")
        state = client.status()
        volume = next(item for item in state["volumes"] if item["role"] == "scratch")
        foreign = storage.core.run(["docker", "create", "--pull=never", "--network", "none", "--read-only", "--mount",
                                   f"type=volume,source={volume['name']},target=/work/scratch,readonly,volume-nocopy",
                                   self.manager_runtime(), "true"])["stdout"].strip()
        try:
            blocked = self.manager.plan_release(first)
            self.assertFalse(blocked["plan"]["all_releasable"])
            self.assertTrue(storage.core.inspect_renderer_container(foreign)["ok"])
            self.assertEqual(other_client.status()["phase"], "open")
        finally:
            # Exact synthetic stopped container created above, no force/prefix cleanup.
            storage.core.run(["docker", "container", "rm", foreign])
        self.assertEqual(self.retire(first)["phase"], "released")
        self.control(other_client, "quiesce")
        self.assertEqual(self.retire(second)["phase"], "released")

    def manager_runtime(self):
        with self.manager.locked() as state:
            return state["image_id"]

    def test_installed_native_mcp_identity_cas_render_and_last_toggle(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        job_id, client = self.allocate()
        params = StdioServerParameters(command=sys.executable, args=["-m", "diavisuals.cli", "mcp", "serve"], env={
            **os.environ, "MCP_CONSUMER_WORKSPACE": str(self.consumer), storage.CONTEXT_ENV: str(self.manager.root / (job_id + ".grant.json"))})

        def payload(result):
            self.assertFalse(result.isError, result)
            value = result.structuredContent
            return value.get("result", value)

        async def exercise():
            async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as session:
                await session.initialize()
                identity = payload(await session.call_tool("server_identity", {}))
                self.assertEqual(identity["job_storage"]["job_root"], "/work")
                self.assertEqual(identity["binding"]["path"], str(self.consumer))
                tools = {item.name for item in (await session.list_tools()).tools}
                self.assertTrue({"job_storage", "render_job_diagram"} <= tools)
                request = {"kind": "gacontext.job-storage-request", "schema_version": 1, "operation": "status",
                           "registry_id": client.grant["registry_id"], "job_id": job_id}
                state = payload(await session.call_tool("job_storage", {"request": request}))
                invalid = await session.call_tool("job_storage", {"request": {**request, "expected_epoch": state["epoch"]}})
                self.assertTrue(invalid.isError)
                legacy = await session.call_tool("render_diagram_text", {"diagram_text": "flowchart LR\nA-->B"})
                self.assertTrue(legacy.isError)
                result = payload(await session.call_tool("render_job_diagram", {"diagram_text": "flowchart LR\nA-->B",
                                 "expected_revision": state["revision"], "expected_epoch": state["epoch"]}))
                self.assertTrue(result["ok"])
                state = payload(await session.call_tool("job_storage", {"request": request}))
                sealed = payload(await session.call_tool("job_storage", {"request": {**request, "operation": "seal",
                                 "expected_revision": state["revision"], "expected_epoch": state["epoch"]}}))
                self.assertEqual(len(sealed["products"]), 1)
                released = payload(await session.call_tool("release_session", {"expected_instance_id": identity["instance"]["instance_id"]}))
                self.assertEqual(released["state"], "draining")
                self.assertFalse(released["process_release_verified"])
                self.assertEqual(next(item["state"] for item in released["job_storage"]["volumes"] if item["role"] == "scratch"), "absent")
            return identity

        identity = asyncio.run(exercise())
        self.assertEqual(storage.owner_state(identity["instance"]), "dead")
        self.assertEqual(self.discard_synthetic(job_id)["phase"], "released")

    def test_real_pressure_and_group_toggle_keep_unsealed_sources(self):
        first, client = self.allocate()
        second, other = self.allocate()
        actual = client.worker

        def pressured(state, job, request, **kwargs):
            request = copy.deepcopy(request)
            if request["op"] == "render":
                # Fault injection: raise the minimum after real admission/input
                # copy. The real worker observes its actual filesystem and cancels.
                request["limits"]["min_free_bytes"] = 1024 ** 4
            return actual(state, job, request, **kwargs)

        state = client.status()
        with mock.patch.object(client, "worker", side_effect=pressured):
            result = client.render(state["revision"], state["epoch"], diagram_text="flowchart LR\nA-->B")
        self.assertFalse(result["ok"])
        self.assertTrue(result["result"]["evidence"]["pressure"])
        self.assertTrue(client.status()["holds"])
        # Harder daemon-space admission observes real capacity and refuses before
        # another volume can be allocated; no operator disk filling is attempted.
        with self.manager.locked() as state:
            job = self.manager.job(state, second)
            original = job["limits"]["min_free_bytes"]
            job["limits"]["min_free_bytes"] = 1024 ** 4
            self.manager.save(state, job)
        state = other.status()
        with self.assertRaises(storage.StorageError):
            other.render(state["revision"], state["epoch"], diagram_text="flowchart LR\nA-->B")
        with self.manager.locked() as state:
            job = self.manager.job(state, second)
            self.assertFalse(job["operations"])
            job["limits"]["min_free_bytes"] = original
            self.manager.save(state, job)
        group = self.manager.toggle_group([first, second])
        self.assertTrue(group["ok"], group)
        self.assertEqual([item["state"]["phase"] for item in group["outcomes"]], ["closed", "released"])
        self.assertEqual(self.discard_synthetic(first)["phase"], "released")

    def test_interrupted_exact_removal_stale_plan_and_changed_daemon(self):
        job_id, client = self.allocate()
        state = self.control(client, "quiesce")
        plan = self.manager.plan_release(job_id)
        with mock.patch.object(storage.core, "renderer_daemon_identity", return_value={"ok": True, "id": "different-daemon"}):
            with self.assertRaises(storage.StorageError):
                self.manager.release(plan["plan_sha256"], plan["plan"]["expected_revision"], plan["plan"]["expected_epoch"], job_id)
        with self.assertRaises(storage.StorageError):
            self.manager.release(plan["plan_sha256"], state["revision"], state["epoch"], job_id)
        actual = storage.core.run
        interrupted = False

        def interrupt(command, **kwargs):
            nonlocal interrupted
            result = actual(command, **kwargs)
            if command[:3] == ["docker", "volume", "rm"] and not interrupted:
                interrupted = True
                raise RuntimeError("injected controller interruption after physical exact removal")
            return result

        with mock.patch.object(storage.core, "run", side_effect=interrupt), self.assertRaises(RuntimeError):
            self.manager.release(plan["plan_sha256"], plan["plan"]["expected_revision"], plan["plan"]["expected_epoch"], job_id)
        self.assertTrue(interrupted)
        observed = client.status()
        self.assertEqual(observed["phase"], "releasing")
        self.assertEqual(next(item["state"] for item in observed["volumes"] if item["role"] == "scratch"), "absent")
        self.assertEqual(self.retire(job_id)["phase"], "released")

    def alter_volume_fixture(self, volume, relative, data):
        command = ["docker", "run", "--rm", "--pull=never", "--network", "none", "--read-only", "--user", "0:0", "--label", "io.context.mcp-factory=diavisuals-w1-fault-fixture",
                   "--mount", f"type=volume,source={volume['name']},target=/work,volume-nocopy", "--entrypoint", "python3", self.manager_runtime(), "-c",
                   "import pathlib,sys; pathlib.Path('/work',sys.argv[1]).write_bytes(bytes.fromhex(sys.argv[2]))", relative, data.hex()]
        result = storage.core.run(command, timeout=30)
        self.assertEqual(result["returncode"], 0, result)

    def test_marker_mismatch_and_hidden_retained_content_are_not_scratch(self):
        job_id, client = self.allocate()
        with self.manager.locked() as state:
            job = self.manager.job(state, job_id)
            retained = copy.deepcopy(next(item for item in job["volumes"] if item["role"] == "retained"))
            marker = storage.json_bytes(self.manager.marker(job, retained))
        self.alter_volume_fixture(retained, storage.MARKER, b"corrupt marker")
        plan = self.manager.plan_release(job_id)
        self.assertFalse(plan["plan"]["all_releasable"])
        self.assertEqual(next(item["state"] for item in plan["state"]["volumes"] if item["role"] == "retained"), "unknown")
        self.alter_volume_fixture(retained, storage.MARKER, marker)
        self.alter_volume_fixture(retained, "scratch/hidden-source", b"synthetic authored bytes below nested mount")
        state = self.control(client, "quiesce")
        self.assertIn("unknown-content", {item["reason"] for item in state["holds"]})
        partial = self.retire(job_id)
        self.assertEqual(next(item["state"] for item in partial["volumes"] if item["role"] == "scratch"), "absent")
        self.assertEqual(next(item["state"] for item in partial["volumes"] if item["role"] == "retained"), "verified")
        self.assertEqual(self.discard_synthetic(job_id)["phase"], "released")

    def test_same_name_scratch_replacement_is_not_adopted(self):
        job_id, client = self.allocate()
        with self.manager.locked() as state:
            job = self.manager.job(state, job_id)
            scratch = copy.deepcopy(next(item for item in job["volumes"] if item["role"] == "scratch"))
        # Deliberate external fault against this empty synthetic incarnation.
        self.assertEqual(storage.core.run(["docker", "volume", "rm", scratch["name"]])["returncode"], 0)
        created = storage.core.run(["docker", "volume", "create", "--driver", "local",
                                  *[part for key, value in scratch["labels"].items() for part in ("--label", f"{key}={value}")], scratch["name"]])
        self.assertEqual(created["returncode"], 0)
        try:
            self.assertEqual(self.manager.volume_inspect(scratch)["state"], "unknown")
            state = client.status()
            with self.assertRaises(storage.StorageError):
                client.render(state["revision"], state["epoch"], diagram_text="flowchart LR\nA-->B")
            self.assertEqual(next(item["state"] for item in client.status()["volumes"] if item["role"] == "scratch"), "unknown")
        finally:
            # Retire only the deliberate empty replacement created by this test.
            self.assertEqual(storage.core.run(["docker", "volume", "rm", scratch["name"]])["returncode"], 0)
        self.control(client, "quiesce")
        self.assertEqual(self.retire(job_id)["phase"], "released")


if __name__ == "__main__":
    unittest.main()
