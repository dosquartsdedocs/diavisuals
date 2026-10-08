from __future__ import annotations

import contextlib
import copy
import io
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

if os.environ.get("DIAVISUALS_INSTALLED") != "1":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from diavisuals import job_io, job_storage, job_worker  # noqa: E402
from tests.job_storage_reference import pinned_reference  # noqa: E402


class StorageUnitTests(unittest.TestCase):
    def test_requests_do_not_accept_overrides_bool_cas_or_other_jobs(self):
        job = {"registry_id": "a" * 32, "job_id": "b" * 32, "revision": 1, "epoch": 1}
        request = {"kind": "gacontext.job-storage-request", "schema_version": 1, "operation": "status", **{key: job[key] for key in ("registry_id", "job_id")}}
        job_storage.request_check(request, job)
        for patch in ({"schema_version": True}, {"command": "anything"}, {"expected_revision": 1}, {"job_id": "c" * 32}):
            with self.subTest(patch=patch), self.assertRaises(job_storage.StorageError):
                job_storage.request_check({**request, **patch}, job)
        for op in ("quiesce", "seal"):
            mutation = {**request, "operation": op, "expected_revision": 1, "expected_epoch": 1}
            job_storage.request_check(mutation, job)
            for patch in ({"expected_revision": True}, {"expected_epoch": 0}, {"expected_revision": 2}):
                with self.subTest(patch=patch), self.assertRaises(job_storage.StorageError):
                    job_storage.request_check({**mutation, **patch}, job)

    def test_protected_links_are_unknown_scratch_links_are_counted_without_following(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "inputs").mkdir()
            (root / "inputs/link").symlink_to("/etc/passwd")
            (root / "scratch").mkdir()
            (root / "scratch/hidden").write_bytes(b"authored hidden content")
            observed = job_worker.measure(root, protected=True, maximum=20)
            self.assertIn("inputs/link", observed["unknown"])
            self.assertIn("scratch/hidden", observed["unknown"])
            self.assertNotIn("sha256", next(item for item in observed["inventory"] if item["path"] == "inputs/link"))
            observed = job_worker.measure(root, protected=False, maximum=20)
            self.assertFalse(observed["unknown"])
            with self.assertRaises(ValueError):
                job_worker.measure(root, protected=True, maximum=1)

    def test_private_grants_reject_symlinks_hardlinks_nonprivate_and_oversize(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "grant.json"
            source.write_bytes(b'{}')
            with self.assertRaises(ValueError):
                job_storage.private_file(source)
            source.chmod(0o600)
            self.assertEqual(job_storage.private_file(source), {})
            (root / "link").symlink_to(source)
            with self.assertRaises(ValueError):
                job_storage.private_file(root / "link")
            os.link(source, root / "hard")
            with self.assertRaises(ValueError):
                job_storage.private_file(source)

    def test_streaming_refuses_oversize_output_and_timeout(self):
        with self.assertRaisesRegex(ValueError, "exceeds bound"):
            job_io.exchange([sys.executable, "-c", "import sys; sys.stdout.write('x'*100000)"], b"", maximum=10)
        with self.assertRaisesRegex(ValueError, "deadline"):
            job_io.exchange([sys.executable, "-c", "import time; time.sleep(10)"], b"", timeout=0.1)

    def test_receiver_rejects_temporary_disposable_bindings(self):
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ValueError):
            job_io.receiver_binding(temporary, "durable")

    def test_hard_quota_and_widened_limits_fail_before_docker_or_allocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "consumer").mkdir()
            for limits in ({"quota_enforcement": "hard"}, {"max_jobs": 3}, {"max_entries": True}, {"min_free_bytes": 1}):
                with self.subTest(limits=limits), mock.patch.object(job_storage.core, "renderer_status", side_effect=AssertionError("unexpected Docker call")):
                    with self.assertRaises(job_storage.StorageError):
                        job_storage.Registry.create(root / "registry", root / "consumer", limits=limits)
                    self.assertFalse((root / "registry").exists())

    def test_inventory_requires_hash_coverage_and_tracks_empty_unknown_roots(self):
        registry = object.__new__(job_storage.Registry)
        job = {"job_id": "a" * 32, "phase": "closed", "coverage": {}, "measurements": {"retained": {
            "observed_at": job_storage.now(), "tree_sha256": "b" * 64, "unknown": [],
            "inventory": [{"kind": "file", "path": "inputs/source", "sha256": "c" * 64}, {"kind": "directory", "path": "foreign"}]}}}
        protected, holds = registry.inventory(job)
        self.assertEqual(protected["unresolved_entries"], 2)
        self.assertEqual({item["reason"] for item in holds}, {"unsealed-source", "unknown-content"})
        job["coverage"]["inputs/source"] = {"sha256": "c" * 64}
        self.assertEqual(registry.inventory(job)[0]["unresolved_entries"], 1)
        changed = copy.deepcopy(job)
        changed["coverage"]["inputs/source"]["sha256"] = "d" * 64
        self.assertEqual(registry.inventory(changed)[0]["unresolved_entries"], 2)

    def test_archive_input_rejects_undeclared_entries_before_writing(self):
        archive = job_io.input_archive({"inputs/test/source": b"source"})
        with mock.patch.object(sys, "stdin", mock.Mock(buffer=io.BytesIO(archive))), self.assertRaises(ValueError):
            job_worker.unpack_selected({"files": {}, "max_bytes": 100})

    def test_client_interest_does_not_authorize_a_writer_mount(self):
        registry = object.__new__(job_storage.Registry)
        registry.grant = {"role": "client", "job_id": "a" * 32}
        registry.consumer = None
        lease = {"id": "b" * 32, "state": "active", "kind": "client", "epoch": 1, "owner": job_storage.process_owner(), "worker": None}
        job = {"job_id": "a" * 32, "epoch": 1, "leases": [lease]}
        state = {"jobs": {job["job_id"]: job}}
        with mock.patch.object(registry, "locked", return_value=contextlib.nullcontext(state)), self.assertRaisesRegex(job_storage.StorageError, "access kind"):
            registry.worker(state, job, {"op": "render"}, lease=lease)

    def test_published_companion_matches_pinned_independent_validator(self):
        with pinned_reference() as (contract, _):
            contract.validate(job_storage.declaration()[0])


if __name__ == "__main__":
    unittest.main()
