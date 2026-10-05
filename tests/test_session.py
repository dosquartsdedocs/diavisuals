from __future__ import annotations

import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

if os.environ.get("DIAVISUALS_INSTALLED") != "1":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from diavisuals import __version__, registry, session  # noqa: E402
from diavisuals.runtime import RuntimeSelection  # noqa: E402

IMAGE = "sha256:" + "a" * 64
CID = "b" * 64
DAEMON = "test-daemon"


class SessionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)

    def instance(self):
        with mock.patch.object(registry, "source_checkout", return_value=None):
            return session.ServerSession(self.root, RuntimeSelection(IMAGE))

    def test_live_identity_is_stable_and_does_not_read_consumer_content(self):
        (self.root / "private.txt").write_text("not identity data")
        with mock.patch.object(registry, "renderer_status", return_value={"ok": True, "image_id": IMAGE}), mock.patch.object(
            registry, "renderer_daemon_identity", return_value={"ok": True, "id": DAEMON},
        ), mock.patch.object(registry, "project_check", side_effect=AssertionError("must not scan consumer")):
            instance = self.instance()
            before = instance.identity()
            after = instance.identity()
        self.assertEqual(before, after)
        self.assertEqual(before["scope"], "live-serving-process")
        self.assertEqual(before["instance"]["pid"], os.getpid())
        self.assertEqual(before["loaded"]["version"], __version__)
        self.assertEqual(before["binding"]["path"], str(self.root))
        self.assertTrue(before["pinned_runtime_ready"], before)
        self.assertNotIn("not identity data", json.dumps(before))
        self.assertEqual({path.name for path in self.root.iterdir()}, {"private.txt"})
        self.assertLess(len(json.dumps(before)), 16384)

    def test_loaded_code_revision_is_independent_of_hash_seed(self):
        fingerprints = []
        for seed in ("1", "2"):
            fingerprints.append(subprocess.check_output(
                [sys.executable, "-c", "from diavisuals.session import loaded_code_fingerprint; print(loaded_code_fingerprint())"],
                env={**os.environ, "PYTHONHASHSEED": seed}, text=True,
            ).strip())
        self.assertEqual(fingerprints[0], fingerprints[1])

    def test_disk_and_metadata_changes_do_not_relabel_loaded_code(self):
        metadata = {"state": "observed", "version": __version__, "sha256": "original", "root": "/metadata"}
        with mock.patch.object(session, "distribution_snapshot", side_effect=lambda: dict(metadata)), mock.patch.object(
            registry, "renderer_status", return_value={"ok": True, "image_id": IMAGE},
        ), mock.patch.object(registry, "renderer_daemon_identity", return_value={"ok": True, "id": DAEMON}):
            instance = self.instance()
            copied = self.root / "package"
            copied.mkdir()
            for path in instance.package_root.glob("*.py"):
                shutil.copyfile(path, copied / path.name)
            instance.package_root = copied
            before = instance.identity()
            metadata.update(version="99.99.99", sha256="changed")
            (copied / "__init__.py").write_text('__version__ = "99.99.99"\n')
            after = instance.identity()
            self.assertEqual(before["loaded"], after["loaded"])
            self.assertEqual(before["instance"], after["instance"])
            self.assertTrue(after["current_disk"]["drift"])
            self.assertFalse(after["pinned_runtime_ready"])
            with self.assertRaisesRegex(ValueError, "restart"):
                with instance.operation("render"):
                    self.fail("must not start work after drift")

    def test_release_refuses_busy_wrong_instance_and_unknown_jobs(self):
        instance = self.instance()
        identity = instance.owner["instance_id"]
        self.assertFalse(instance.release("wrong")["ok"])
        with instance.operation("render"):
            self.assertEqual(instance.lifecycle()["state"], "busy")
            self.assertFalse(instance.release(identity)["ok"])
            with self.assertRaisesRegex(ValueError, "busy"):
                with instance.operation("another"):
                    self.fail("must not queue unbounded operations")
        instance.job_started("unverified", IMAGE, DAEMON)
        self.assertEqual(instance.lifecycle()["state"], "unknown")
        self.assertFalse(instance.release(identity)["ok"])
        instance.job_finished("unverified", {"ok": True})
        drained = instance.release(identity)
        self.assertTrue(drained["ok"])
        self.assertFalse(drained["process_release_verified"])
        with self.assertRaisesRegex(ValueError, "draining"):
            with instance.operation("render"):
                self.fail("must not accept work after drain")

    def test_source_observation_is_bounded_and_never_follows_links(self):
        (self.root / "module.py").write_text("pass\n")
        self.assertEqual(session.source_snapshot(self.root)["state"], "observed")
        (self.root / "private").write_text("private")
        (self.root / "linked.py").symlink_to(self.root / "private")
        self.assertEqual(session.source_snapshot(self.root)["state"], "unavailable")
        (self.root / "linked.py").unlink()
        with (self.root / "module.py").open("wb") as output:
            output.truncate(session.MAX_CODE_BYTES + 1)
        self.assertEqual(session.source_snapshot(self.root)["state"], "unavailable")

    def test_pid_namespace_and_reused_pid_cannot_authorize_live_owner_cleanup(self):
        owner = session.process_owner()
        self.assertEqual(session.owner_state(owner), "alive")
        other_namespace = {**owner, "pid_namespace": "pid:[0]"}
        self.assertEqual(session.owner_state(other_namespace), "unknown")
        other_boot = {**owner, "boot_id": "another-boot"}
        self.assertEqual(session.owner_state(other_boot), "unknown")
        reused = {**owner, "start_ticks": "0"}
        self.assertEqual(session.owner_state(reused), "dead")
        self.assertEqual(session.owner_state({**owner, "pid": -1}), "unknown")

    def test_mcp_render_preparation_never_falls_back_to_build(self):
        with self.instance().operation("render"), mock.patch.object(registry, "renderer_status", return_value={"ok": False}), mock.patch.object(
            registry, "_build_renderer_image", side_effect=AssertionError("must not build"),
        ):
            self.assertFalse(registry.ensure_renderer_image(runtime=RuntimeSelection())["ok"])


class OwnedContainerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.owner = session.process_owner()
        self.labels = {**session.owner_labels(), "io.context.mcp-factory": "diavisuals",
                       registry.RENDERER_WORKSPACE_LABEL: registry.renderer_workspace_id(self.root),
                       session.DAEMON_LABEL: DAEMON, session.IMAGE_LABEL: IMAGE, session.JOB_LABEL: "diavisuals-owned"}
        self.info = {"Id": CID, "Name": "/diavisuals-owned", "Image": IMAGE, "Labels": self.labels, "Running": True}

    def test_container_observation_must_match_the_exact_requested_id(self):
        info = {**self.info, "Id": "c" * 64}
        with mock.patch.object(registry, "run", return_value={"returncode": 0, "stdout": json.dumps(info), "stderr": ""}):
            observed = registry.inspect_renderer_container(CID)
        self.assertFalse(observed["ok"])
        self.assertEqual(observed["state"], "unknown")

    def test_removal_uses_exact_id_and_requires_observed_absence(self):
        for absent in (True, False):
            with self.subTest(absent=absent), mock.patch.object(registry, "renderer_daemon_identity", return_value={"ok": True, "id": DAEMON}), mock.patch.object(
                registry, "inspect_renderer_container", side_effect=[{"ok": True, "absent": False, "info": self.info}, {"ok": True, "absent": absent}],
            ), mock.patch.object(registry, "run", return_value={"returncode": 0}) as run:
                result = registry._remove_renderer_container("diavisuals-owned", expected_labels=self.labels)
                self.assertEqual(result["ok"], absent)
                self.assertEqual(run.call_args.args[0], ["docker", "container", "rm", "--force", CID])

    def test_unknown_foreign_or_wrong_daemon_ownership_never_removes(self):
        for kind in ("unknown", "name", "instance", "image", "daemon"):
            with self.subTest(kind=kind):
                info = copy.deepcopy(self.info)
                if kind == "name":
                    info["Name"] = "/another-name"
                if kind == "instance":
                    info["Labels"][session.INSTANCE_LABEL] = "another-instance"
                if kind == "image":
                    info["Image"] = "sha256:" + "c" * 64
                with mock.patch.object(registry, "renderer_daemon_identity", return_value={"ok": True, "id": "other" if kind == "daemon" else DAEMON}), mock.patch.object(
                    registry, "inspect_renderer_container", return_value={"ok": True, "absent": False, "info": info},
                ), mock.patch.object(registry, "run", side_effect=AssertionError("no removal")):
                    result = registry._remove_renderer_container("diavisuals-owned", expected_labels=None if kind == "unknown" else self.labels)
                    self.assertFalse(result["ok"])

    def test_recovery_refuses_alive_unknown_and_cross_consumer_jobs(self):
        for state in ("alive", "unknown", "dead-foreign"):
            with self.subTest(state=state):
                info = copy.deepcopy(self.info)
                if state == "dead-foreign":
                    info["Labels"][registry.RENDERER_WORKSPACE_LABEL] = "another-consumer"
                with mock.patch.object(registry, "owner_state", return_value="dead" if state == "dead-foreign" else state), mock.patch.object(
                    registry, "renderer_daemon_identity", return_value={"ok": True, "id": DAEMON},
                ), mock.patch.object(registry, "run", return_value={"returncode": 0, "stdout": CID, "stderr": ""}) as run, mock.patch.object(
                    registry, "inspect_renderer_container", return_value={"ok": True, "absent": False, "info": info},
                ):
                    result = registry.session_containers(self.root, owner=self.owner, daemon_id=DAEMON, release_ids=[CID])
                    self.assertFalse(result["ok"])
                    self.assertFalse(any("rm" in call.args[0] for call in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
