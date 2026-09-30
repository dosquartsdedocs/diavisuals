from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

if os.environ.get("DIAVISUALS_INSTALLED") != "1":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from diavisuals import artifacts, cli, registry  # noqa: E402
from diavisuals.handoff_fs import digest, json_bytes  # noqa: E402
from diavisuals.runtime import RuntimeSelection, runtime_selection  # noqa: E402
from tests.test_artifacts import SVG, mount  # noqa: E402

A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64
DIGEST = "example.invalid/renderer@sha256:" + "c" * 64


class RuntimeSelectionTest(unittest.TestCase):
    def setUp(self):
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop("DIAVISUALS_RUNTIME_IMAGE", None)
        os.environ.pop("DIAVISUALS_RUNTIME_EXPECTED_ID", None)
        temporary = tempfile.TemporaryDirectory(prefix="diavisuals-selection-")
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)

    def inspected(self, identity=A, digests=None, returncode=0):
        return {"returncode": returncode, "stdout": json.dumps({"Id": identity, "RepoDigests": digests or []}), "stderr": ""}

    def test_arguments_are_atomic_and_validate_pins(self):
        invalid = [
            (None, A), ("", None), (" ", None), ("sha256:aaa", None), (A, B),
            ("alias:test", None), ("-bad", A), ("repo@sha256:short", None), ("repo@sha512:" + "a" * 64, A),
            ("repo:test", ""), ("repo:test", "sha256:" + "A" * 64), ("repo;echo", A),
        ]
        for ref, expected in invalid:
            with self.subTest(ref=ref, expected=expected), self.assertRaises(ValueError):
                RuntimeSelection(ref, expected)
        self.assertEqual(RuntimeSelection(A).expected_image_id, A)
        self.assertTrue(RuntimeSelection(DIGEST).explicit)
        with mock.patch.dict(os.environ, {"DIAVISUALS_RUNTIME_IMAGE": "alias:test", "DIAVISUALS_RUNTIME_EXPECTED_ID": A}):
            self.assertEqual(runtime_selection(), RuntimeSelection("alias:test", A))
            self.assertEqual(runtime_selection(B), RuntimeSelection(B))
            with self.assertRaises(ValueError):
                runtime_selection("other:test")
        with mock.patch.dict(os.environ, {"DIAVISUALS_RUNTIME_IMAGE": ""}):
            with self.assertRaises(ValueError):
                runtime_selection()

    def test_explicit_resolution_is_inspect_only_and_checks_expected_identity(self):
        cases = [
            (RuntimeSelection(A), self.inspected(), True),
            (RuntimeSelection("alias:test", A), self.inspected(), True),
            (RuntimeSelection(DIGEST, A), self.inspected(digests=[DIGEST]), True),
            (RuntimeSelection(DIGEST), self.inspected(digests=[DIGEST]), True),
            (RuntimeSelection(B), self.inspected(), False),
            (RuntimeSelection("alias:test", B), self.inspected(), False),
            (RuntimeSelection(DIGEST), self.inspected(), False),
            (RuntimeSelection(DIGEST), self.inspected(digests=DIGEST), False),
            (RuntimeSelection(DIGEST), self.inspected(digests={DIGEST: True}), False),
            (RuntimeSelection(A), self.inspected(returncode=1), False),
            (RuntimeSelection(A), {"returncode": 0, "stdout": "[]", "stderr": ""}, False),
        ]
        with mock.patch.object(registry, "_build_renderer_image", side_effect=AssertionError("must not build")):
            for selected, inspected, expected in cases:
                for callback in (registry.renderer_status, registry.ensure_renderer_image, registry.build_renderer_image):
                    with self.subTest(selected=selected, callback=callback.__name__), mock.patch.object(registry, "run", return_value=inspected) as run:
                        result = callback(runtime=selected)
                        self.assertEqual(result["ok"], expected, result)
                        self.assertFalse(result["built"])
                        run.assert_called_once()
                        self.assertEqual(run.call_args.args[0], ["docker", "image", "inspect", "--format", '{"Id":{{json .Id}},"RepoDigests":{{json .RepoDigests}}}', selected.image_ref])
                        if expected:
                            self.assertEqual(result["runtime"]["image_id"], A)
                            self.assertEqual(result["runtime"]["requested_ref"], selected.image_ref)

    def test_default_preparation_still_builds_an_absent_profile_alias(self):
        with mock.patch.object(registry, "_inspect_renderer_image", side_effect=[{"image_id": None}, {"image_id": A}]), mock.patch.object(
            registry, "_build_renderer_image", return_value={"ok": True},
        ) as build:
            result = registry.ensure_renderer_image(runtime=RuntimeSelection())
        self.assertTrue(result["ok"])
        self.assertTrue(result["built"])
        self.assertEqual(result["runtime"]["mode"], "profile")
        self.assertEqual(build.call_args.args[0]["image"], "diavisuals/render:v0.3.0")

    def test_missing_selection_fails_before_output_cache_or_export_state(self):
        source = self.root / "diagram.mmd"
        source.write_text("flowchart LR\n A-->B\n")
        output = self.root / "diagram.svg"
        output.write_bytes(SVG)
        with mock.patch.object(registry, "run", return_value=self.inspected(returncode=1)), mock.patch.object(
            registry, "_build_renderer_image", side_effect=AssertionError("must not build"),
        ):
            for dry_run in (False, True):
                for result in (
                    registry.render_diagram(self.root, input_path="diagram.mmd", output_path="diagram.svg", runtime=RuntimeSelection(A), dry_run=dry_run),
                    registry.render_diagram_text(self.root, diagram_text="flowchart LR\n A-->B", runtime=RuntimeSelection(A), dry_run=dry_run),
                    artifacts.export_diagram_bundle(self.root, input_path="diagram.mmd", runtime=RuntimeSelection(A), dry_run=dry_run),
                ):
                    self.assertFalse(result["ok"], result)
        self.assertEqual(output.read_bytes(), SVG)
        self.assertEqual({path.name for path in self.root.iterdir()}, {"diagram.mmd", "diagram.svg"})

    def fake_render(self, command, **kwargs):
        self.assertIn(command[command.index("bash") - 1], (A, B))
        self.assertIn("--pull=never", command)
        (mount(command, "/output") / "artifact.svg").write_bytes(SVG)
        return {"returncode": 0, "cleanup": {"ok": True}}

    def inspect_command(self, command, **kwargs):
        if command[:3] == ["docker", "image", "inspect"]:
            if command[-1] in (A, B):
                return self.inspected(identity=command[-1])
            return {"returncode": 0, "stdout": A, "stderr": ""}
        return {"returncode": 1, "stdout": "", "stderr": "not a Git checkout"}

    def test_cache_and_freshness_follow_image_resource_and_content_changes(self):
        source = self.root / "assets/diagram.mmd"
        source.parent.mkdir()
        source.write_text("flowchart LR\n A-->B\n")
        with mock.patch.object(registry, "run", side_effect=self.inspect_command), mock.patch.object(registry, "_run_renderer", side_effect=self.fake_render):
            first = registry.render_diagram_text(self.root, diagram_text=source.read_text(), runtime=RuntimeSelection(A))
            second = registry.render_diagram_text(self.root, diagram_text=source.read_text(), runtime=RuntimeSelection(B))
            again = registry.render_diagram_text(self.root, diagram_text=source.read_text(), runtime=RuntimeSelection(A))
            self.assertTrue(first["ok"] and second["ok"] and again["ok"])
            self.assertNotEqual(first["output"], second["output"])
            self.assertEqual(first["output"], again["output"])
            rendered = registry.render_diagram(self.root, input_path="assets/diagram.mmd", output_path="assets/diagram.mmd.svg", runtime=RuntimeSelection(A))
            self.assertTrue(rendered["ok"], rendered)
            self.assertTrue(registry.project_check(self.root, runtime=RuntimeSelection(A))["ok"])
            changed = registry.project_check(self.root, runtime=RuntimeSelection(B))
            self.assertFalse(changed["ok"])
            self.assertIn("different effective runtime", changed["issues"][0])
            self.assertFalse((self.root / registry.PROJECT_RECEIPT_PATH).exists())
            # Returning to default mode refreshes an already-managed output.
            self.assertTrue(registry.render_diagram(self.root, input_path="assets/diagram.mmd", output_path="assets/diagram.mmd.svg", runtime=RuntimeSelection())["ok"])
            self.assertTrue(registry.project_check(self.root)["ok"])
            record = json.loads((self.root / rendered["provenance"]).read_bytes())
            self.assertEqual(record["runtime"]["mode"], "profile")
            edited = self.root / "assets/diagram.mmd.edited.svg"
            edited.write_bytes(SVG.replace(b"Original", b"Author"))
            self.assertTrue(registry.project_check(self.root, runtime=RuntimeSelection(A))["ok"])
            (self.root / "assets/diagram.mmd.svg").write_bytes(SVG.replace(b"Original", b"Changed"))
            self.assertFalse(registry.project_check(self.root, runtime=RuntimeSelection(A))["ok"])
            (self.root / "assets/diagram.mmd.svg").write_bytes(SVG)
            self.assertTrue(registry.project_check(self.root, runtime=RuntimeSelection(A))["ok"])
            # A modified profile is a different resource identity, not an image override.
            custom = self.root / "custom-assets"
            for directory in ("styles", "compat", "tools", "docker"):
                shutil.copytree(registry.repo_dir() / directory, custom / directory)
            profile = custom / "compat" / f"{registry.DEFAULT_COMPATIBILITY}.env"
            profile.write_bytes(profile.read_bytes() + b"\n# different resource identity\n")
            with mock.patch.dict(os.environ, {"DIAVISUALS_DIR": str(custom)}):
                changed_resource = registry.render_diagram_text(self.root, diagram_text=source.read_text(), runtime=RuntimeSelection(A))
                self.assertTrue(changed_resource["ok"], changed_resource)
                self.assertNotEqual(first["output"], changed_resource["output"])
                self.assertNotEqual(first["runtime"]["profile_sha256"], changed_resource["runtime"]["profile_sha256"])
                stale_resources = registry.project_check(self.root, runtime=RuntimeSelection(A))
                self.assertFalse(stale_resources["ok"])
                self.assertIn("different profile or resource identity", stale_resources["issues"][0])

    def test_unmanaged_outputs_require_provenance_only_for_explicit_selection(self):
        source = self.root / "assets/diagram.mmd"
        source.parent.mkdir()
        source.write_text("flowchart LR\n A-->B\n")
        pathlib.Path(str(source) + ".svg").write_bytes(SVG)
        self.assertTrue(registry.project_check(self.root)["ok"])
        with mock.patch.object(registry, "run", side_effect=self.inspect_command):
            result = registry.project_check(self.root, runtime=RuntimeSelection(A))
        self.assertFalse(result["ok"])
        self.assertIn("missing render provenance", result["issues"][0])

    def test_bundle_retains_unmodified_profile_and_checks_runtime_selection(self):
        profile_path = registry.repo_dir() / "compat" / f"{registry.DEFAULT_COMPATIBILITY}.env"
        original_profile = profile_path.read_bytes()
        self.assertEqual(digest(original_profile), "3d4e0ec5d3d646e68e14a9c549c338d11feb34b29d11e95b75b9f8c5fd2739ef")
        with mock.patch.object(registry, "run", side_effect=self.inspect_command), mock.patch.object(registry, "_run_renderer", side_effect=self.fake_render):
            result = artifacts.export_diagram_bundle(self.root, diagram_text="flowchart LR\n A-->B", runtime=RuntimeSelection(B))
        self.assertTrue(result["ok"], result)
        manifest = self.root / result["bundle"]["path"]
        selection_path = manifest.parent / "payload/runtime-selection.json"
        selection = json.loads(selection_path.read_bytes())
        self.assertEqual(selection["image_id"], B)
        self.assertEqual(selection["expected_image_id"], B)
        self.assertEqual((manifest.parent / "payload/resources" / profile_path.name).read_bytes(), original_profile)
        self.assertEqual(profile_path.read_bytes(), original_profile)
        self.assertTrue(artifacts.check_diagram_bundle(self.root, **result["bundle"])["ok"])
        selection["expected_image_id"] = A
        selection_path.write_bytes(json_bytes(selection))
        document = json.loads(manifest.read_bytes())
        item = next(item for item in document["files"] if item["role"] == "runtime-selection")
        item.update(sha256=digest(selection_path.read_bytes()), bytes=selection_path.stat().st_size)
        manifest.write_bytes(json_bytes(document))
        with self.assertRaisesRegex(ValueError, "do not match|expected identity"):
            artifacts.check_diagram_bundle(self.root, path=result["bundle"]["path"], sha256=digest(manifest.read_bytes()))

    def test_cli_and_registration_propagate_the_same_selection(self):
        with mock.patch.object(registry, "run", return_value=self.inspected()), mock.patch.object(cli, "print_payload") as output:
            self.assertEqual(cli.main(["--runtime-image", A, "ensure-renderer"]), 0)
            self.assertEqual(output.call_args.args[0]["runtime"]["image_id"], A)
        with mock.patch("diavisuals.mcp_server.run_server") as serve:
            self.assertEqual(cli.main(["--project", str(self.root), "--runtime-image", B, "mcp", "serve"]), 0)
            serve.assert_called_once_with(self.root, runtime=RuntimeSelection(B))
        config = registry.client_config(str(self.root), runtime=RuntimeSelection(B))
        self.assertEqual(config["mcpServers"]["diavisuals"]["env"]["DIAVISUALS_RUNTIME_EXPECTED_ID"], B)

    def test_default_dry_run_needs_no_daemon_but_explicit_dry_run_checks_identity(self):
        with mock.patch.object(registry, "run", side_effect=AssertionError("default dry run must be offline")):
            result = registry.render_diagram_text(self.root, diagram_text="flowchart LR\n A-->B", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["runtime"]["image_id"])
        with mock.patch.object(registry, "run", return_value=self.inspected(identity=B)):
            result = registry.render_diagram_text(self.root, diagram_text="flowchart LR\n A-->B", dry_run=True, runtime=RuntimeSelection(A))
        self.assertFalse(result["ok"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_provenance_publication_failure_preserves_an_existing_output(self):
        (self.root / "source.mmd").write_text("flowchart LR\n A-->B\n")
        output = self.root / "source.mmd.svg"
        original = SVG.replace(b"Original", b"Keep existing")
        output.write_bytes(original)
        with mock.patch.object(registry, "run", side_effect=self.inspect_command), mock.patch.object(
            registry, "_run_renderer", side_effect=self.fake_render,
        ), mock.patch.object(registry, "_atomic_write_confined", side_effect=OSError("provenance unavailable")):
            result = registry.render_diagram(self.root, input_path="source.mmd", output_path=output.name, runtime=RuntimeSelection(A))
        self.assertFalse(result["ok"])
        self.assertEqual(output.read_bytes(), original)

    def test_malformed_cli_selection_invalidates_old_receipt_without_docker(self):
        receipt = self.root / registry.PROJECT_RECEIPT_PATH
        receipt.parent.mkdir(parents=True)
        for arguments in (["--runtime-image", "alias:no-expected-id"], ["--runtime-expected-id", A]):
            receipt.write_text('{"ok":true}\n')
            with mock.patch.object(registry, "run", side_effect=AssertionError("must not call Docker")), contextlib.redirect_stderr(io.StringIO()) as error:
                code = cli.main(["--project", str(self.root), *arguments, "project-check"])
            self.assertEqual(code, 1)
            self.assertFalse(json.loads(error.getvalue())["ok"])
            self.assertFalse(receipt.exists())

    def test_inline_provenance_matches_exact_project_source_bytes(self):
        source = self.root / "assets/inline.mmd"
        source.parent.mkdir()
        source.write_text("flowchart LR\n A-->B\n")
        with mock.patch.object(registry, "run", side_effect=self.inspect_command), mock.patch.object(registry, "_run_renderer", side_effect=self.fake_render):
            result = registry.render_diagram_text(self.root, diagram_text=source.read_text(), output_path="assets/inline.mmd.svg", runtime=RuntimeSelection(A))
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["render_provenance"]["source_kind"], "inline")
            self.assertTrue(registry.project_check(self.root, runtime=RuntimeSelection(A))["ok"])
            source.write_text("flowchart LR\n A-->C\n")
            os.utime(source, ns=(1, 1))
            self.assertFalse(registry.project_check(self.root, runtime=RuntimeSelection(A))["ok"])


if __name__ == "__main__":
    unittest.main()
