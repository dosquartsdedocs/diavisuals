from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

if os.environ.get("DIAVISUALS_INSTALLED") != "1":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from diavisuals import artifacts, cli, registry  # noqa: E402
from diavisuals.handoff_fs import Workspace, digest, json_bytes, parse_json, safe_path  # noqa: E402
from tests.handoff_reference import FIXTURES, REFERENCE, pinned_reference  # noqa: E402

SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><text>Original</text></svg>\n'
EDITED = SVG.replace(b"Original", b"Reviewed")
SOURCES = {"mermaid": b"flowchart LR\r\n A --> B  \r\n\n", "plantuml": b"@startuml\r\nAlice -> Bob\r\n@enduml  \r\n\n"}
IMAGE = "sha256:" + "a" * 64


def mount(command: list[str], target: str) -> pathlib.Path:
    for index, value in enumerate(command):
        if value == "--mount":
            options = dict(field.split("=", 1) for field in next(csv.reader([command[index + 1]])) if "=" in field)
            if options.get("target") == target:
                return pathlib.Path(options["source"])
    raise AssertionError(target)


class ArtifactTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="diavisuals-artifact-test-")
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name)
        self.root = self.base / "consumer amb espais à"
        self.root.mkdir()
        self.commands = []
        self.image = mock.patch.object(registry, "ensure_renderer_image", return_value={"ok": True, "image_id": IMAGE})
        self.runner = mock.patch.object(registry, "_run_renderer", side_effect=self.render)
        self.image.start()
        self.runner.start()
        self.addCleanup(self.image.stop)
        self.addCleanup(self.runner.stop)

    def render(self, command, **kwargs):
        self.commands.append(command)
        self.assertEqual(command[command.index("--network") + 1], "none")
        self.assertNotIn(str(self.root), " ".join(command))
        self.assertIn(IMAGE, command)
        self.assertTrue(mount(command, "/diavisuals").is_dir())
        (mount(command, "/output") / "artifact.svg").write_bytes(SVG)
        return {"returncode": 0, "cleanup": {"ok": True}}

    def export(self, **kwargs):
        options = {"diagram_text": SOURCES["mermaid"].decode(), "bundle_id": "figure"}
        options.update(kwargs)
        if options.get("input_path") is not None:
            options.pop("diagram_text")
        result = artifacts.export_diagram_bundle(self.root, **options)
        self.assertTrue(result["ok"], result)
        return result

    def document(self, result):
        path = self.root / result["bundle"]["path"]
        return path, json.loads(path.read_bytes())

    def rewrite(self, path, document):
        data = json_bytes(document)
        path.write_bytes(data)
        return digest(data)

    def test_file_inline_both_engines_exact_sources_and_resources(self):
        if os.environ.get("DIAVISUALS_INSTALLED") == "1":
            self.assertIsNone(registry.source_checkout(), "installed parity must not load the source checkout")
        for engine, source in SOURCES.items():
            suffix = "mmd" if engine == "mermaid" else "puml"
            for inline in (True, False):
                with self.subTest(engine=engine, inline=inline):
                    name = f"{engine}-{'inline' if inline else 'file'}"
                    (self.root / f"font à.{suffix}").write_bytes(source)
                    options = {"diagram_text": source.decode()} if inline else {"input_path": f"font à.{suffix}"}
                    result = self.export(bundle_id=name, **options)
                    path, doc = self.document(result)
                    self.assertTrue(artifacts.check_diagram_bundle(self.root, **result["bundle"])["ok"])
                    self.assertEqual((path.parent / f"payload/render/input/source.{suffix}").read_bytes(), source)
                    request = json.loads((path.parent / "payload/request.json").read_bytes())
                    self.assertTrue(request["resources"])
                    for resource in request["resources"]:
                        self.assertTrue((path.parent / resource).is_file())
                    self.assertEqual(doc["producer"]["runtimes"][0]["revision"], IMAGE)
                    self.assertTrue(doc["producer"]["revision"].startswith("sha256:"))
                    self.assertNotIn(str(self.root), path.read_text())
                    self.assertFalse((self.root / ".cache").exists())

    def test_variants_preserve_selected_original_and_native_receipt(self):
        (self.root / "old.svg").write_bytes(SVG)
        (self.root / "old.edited.svg").write_bytes(EDITED)
        receipt = self.root / registry.PROJECT_RECEIPT_PATH
        receipt.parent.mkdir(parents=True)
        receipt.write_bytes(b'{"opaque":"native receipt"}\n')
        result = self.export(original_path="old.svg", edited_paths=["old.edited.svg"])
        path, doc = self.document(result)
        files = {item["id"]: item for item in doc["files"]}
        self.assertEqual(files["edited-1"]["variant_of"], "original")
        self.assertEqual(files["edited-1"]["ownership"], "author")
        self.assertEqual((path.parent / files["original"]["path"]).read_bytes(), SVG)
        self.assertEqual((path.parent / files["edited-1"]["path"]).read_bytes(), EDITED)
        self.assertEqual(receipt.read_bytes(), b'{"opaque":"native receipt"}\n')
        self.assertEqual((self.root / "old.edited.svg").read_bytes(), EDITED)
        self.assertNotIn("native-receipt", [item["role"] for item in doc["files"]])

    def test_collision_including_empty_destination_never_overwrites(self):
        result = self.export()
        path, _ = self.document(result)
        before = path.read_bytes()
        for name in ("figure", "empty", "alias"):
            if name == "empty":
                (path.parent.parent / name).mkdir()
            if name == "alias":
                (path.parent.parent / "Alias").mkdir()
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "already exists|case-aliased"):
                artifacts.export_diagram_bundle(self.root, diagram_text=SOURCES["mermaid"].decode(), bundle_id=name)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self.commands), 1)

    def test_failure_retains_sources_and_sealed_publication_can_recover(self):
        with mock.patch.object(artifacts, "rename_new", side_effect=OSError("interrupted publication")):
            failed = artifacts.export_diagram_bundle(self.root, diagram_text=SOURCES["mermaid"].decode(), bundle_id="figure")
        self.assertFalse(failed["ok"])
        recovery = failed["recovery"]
        before = (self.root / recovery["path"]).read_bytes()
        self.assertTrue(artifacts.check_diagram_bundle(self.root, path=recovery["path"], sha256=recovery["sha256"])["ok"])
        result = artifacts.recover_diagram_bundle(self.root, path=recovery["path"], sha256=recovery["sha256"], bundle_id="figure")
        self.assertTrue(result["ok"])
        self.assertEqual((self.root / result["bundle"]["path"]).read_bytes(), before)
        repeated = artifacts.recover_diagram_bundle(self.root, path=recovery["path"], sha256=recovery["sha256"], bundle_id="figure")
        self.assertTrue(repeated["already_published"])

    def test_post_rename_interruption_keeps_complete_destination(self):
        rename = artifacts.rename_new

        def interrupted(*args):
            rename(*args)
            raise OSError("fsync/acknowledgement failed")

        with mock.patch.object(artifacts, "rename_new", side_effect=interrupted):
            failed = artifacts.export_diagram_bundle(self.root, diagram_text=SOURCES["mermaid"].decode(), bundle_id="figure")
        self.assertFalse(failed["ok"])
        recovery = failed["recovery"]
        self.assertTrue(artifacts.recover_diagram_bundle(self.root, path=recovery["path"], sha256=recovery["sha256"], bundle_id="figure")["ok"])

    def test_renderer_failure_keeps_partial_inline_job(self):
        with mock.patch.object(registry, "_run_renderer", return_value={"returncode": 1, "cleanup": {"ok": True}}):
            result = artifacts.export_diagram_bundle(self.root, diagram_text=SOURCES["mermaid"].decode())
        self.assertFalse(result["ok"])
        self.assertIsNone(result["recovery"]["sha256"])
        source = self.root / result["recovery"]["path"]
        self.assertEqual((source.parent / "payload/render/input/source.mmd").read_bytes(), SOURCES["mermaid"])
        self.assertFalse(source.exists())
        self.assertFalse((self.root / result["recovery"]["destination"]).exists())

    def test_down_preserves_bundle_and_unacknowledged_recovery(self):
        result = self.export()
        with mock.patch.object(artifacts, "rename_new", side_effect=OSError("publication failed")):
            failed = artifacts.export_diagram_bundle(self.root, diagram_text=SOURCES["plantuml"].decode())
        bundle = self.root / result["bundle"]["path"]
        recovery = self.root / failed["recovery"]["path"]
        before = (bundle.read_bytes(), recovery.read_bytes())
        with mock.patch.object(registry.shutil, "which", return_value=None):
            self.assertTrue(registry.down_factory(self.root)["ok"])
        self.assertEqual((bundle.read_bytes(), recovery.read_bytes()), before)

    def test_bad_runtime_or_failed_teardown_cannot_seal(self):
        for image, rendered in (("mutable:tag", {"returncode": 0, "cleanup": {"ok": True}}),
                                (IMAGE, {"returncode": 0, "cleanup": {"ok": False}})):
            with self.subTest(image=image), mock.patch.object(registry, "ensure_renderer_image", return_value={"ok": True, "image_id": image}), mock.patch.object(registry, "_run_renderer", return_value=rendered):
                result = artifacts.export_diagram_bundle(self.root, diagram_text=SOURCES["mermaid"].decode())
            self.assertFalse(result["ok"])
            self.assertIsNone(result["recovery"]["sha256"])

    def test_concurrent_source_edit_and_staged_resource_mutation_are_rejected(self):
        source = self.root / "figure.mmd"
        source.write_bytes(SOURCES["mermaid"])

        def changed(command, **kwargs):
            result = self.render(command, **kwargs)
            source.write_bytes(b"flowchart LR\n X --> Y\n")
            return result

        with mock.patch.object(registry, "_run_renderer", side_effect=changed):
            result = artifacts.export_diagram_bundle(self.root, input_path="figure.mmd")
        self.assertFalse(result["ok"])
        self.assertIn("changed", result["error"])
        self.assertEqual(source.read_bytes(), b"flowchart LR\n X --> Y\n")

        def changed_resource(command, **kwargs):
            result = self.render(command, **kwargs)
            resource = mount(command, "/diavisuals") / "styles/mermaid/benizar-mermaid.json"
            resource.chmod(0o600)
            resource.write_bytes(b"{}")
            return result

        with mock.patch.object(registry, "_run_renderer", side_effect=changed_resource):
            result = artifacts.export_diagram_bundle(self.root, diagram_text=SOURCES["mermaid"].decode())
        self.assertFalse(result["ok"])
        self.assertIn("resource changed", result["error"])

    def test_parallel_exports_serialize_without_replacing(self):
        def export():
            try:
                return artifacts.export_diagram_bundle(self.root, diagram_text=SOURCES["mermaid"].decode(), bundle_id="same")
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: export(), range(2)))
        self.assertEqual(sum(result["ok"] for result in results), 1, results)
        self.assertEqual(len(self.commands), 1)

    def test_unsupported_dependencies_fail_before_render(self):
        cases = [
            "@startuml\n!include other.puml\n@enduml", "@startuml\n!include <stdlib>\n@enduml",
            "@startuml\nAlice -> Bob : %getenv('SECRET')\n@enduml", "@startuml\n<img:../logo.png>\n@enduml",
            "flowchart LR\n A@{ img: 'logo.png' }", "flowchart LR\n A[<img src='logo.png'>]",
            '%%{init: {"themeCSS": "@import other.css"}}%%\nflowchart LR\n A-->B',
            "flowchart LR\n click A 'https://example.invalid'", "---\nconfig: {}\n---\nflowchart LR\n A-->B",
        ]
        for source in cases:
            with self.subTest(source=source), self.assertRaises(ValueError):
                artifacts.export_diagram_bundle(self.root, diagram_text=source, engine="plantuml" if "@startuml" in source else "mermaid")
        self.assertEqual(self.commands, [])
        self.assertFalse((self.root / ".diavisuals").exists())

    def test_files_inside_sealed_bundles_cannot_lose_upstream_provenance(self):
        result = self.export()
        base = pathlib.PurePosixPath(result["bundle"]["path"]).parent
        source = str(base / "payload/render/input/source.mmd")
        with self.assertRaisesRegex(ValueError, "unsupported composite input"):
            artifacts.export_diagram_bundle(self.root, input_path=source)
        (self.root / "reviewed.svg").write_bytes(EDITED)
        with self.assertRaisesRegex(ValueError, "unsupported composite input"):
            artifacts.export_diagram_bundle(self.root, diagram_text=SOURCES["mermaid"].decode(),
                                            original_path=str(base / "payload/outputs/generated.svg"), edited_paths=["reviewed.svg"])
        self.assertEqual(len(self.commands), 1)

    def test_svg_external_missing_and_obfuscated_references_are_rejected(self):
        artifacts._svg_check(b"<?plantuml 1.2026.1?>" + SVG + b"<?plantuml-src SGVsbG8=?>")
        with self.assertRaisesRegex(ValueError, "processing instructions"):
            artifacts._svg_check(b'<?xml-stylesheet href="external.css"?>' + SVG)
        for text in (
            '<image href="missing.png"/>', '<image href="https://example.invalid/a.png"/>',
            '<use href="#missing"/>', '<style>@import "x.css";</style>',
            '<style>.a {fill: u\\72l(external.svg)}</style>', '<script>alert(1)</script>',
            '<path style="fill:url(#missing)"/>', '<g xml:base="file:///tmp/"/>',
        ):
            (self.root / "old.svg").write_bytes(SVG)
            (self.root / "edit.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg">{text}</svg>')
            with self.subTest(text=text), self.assertRaises(ValueError):
                artifacts.export_diagram_bundle(self.root, diagram_text=SOURCES["mermaid"].decode(), original_path="old.svg", edited_paths=["edit.svg"])

    def test_links_special_files_and_workspace_ancestors_are_rejected(self):
        outside = self.base / "outside.mmd"
        outside.write_bytes(SOURCES["mermaid"])
        for kind in ("symlink", "hardlink", "fifo"):
            path = self.root / f"{kind}.mmd"
            if kind == "symlink":
                path.symlink_to(outside)
            elif kind == "hardlink":
                os.link(outside, path)
            else:
                os.mkfifo(path)
            with self.subTest(kind=kind), self.assertRaises((ValueError, OSError)):
                artifacts.export_diagram_bundle(self.root, input_path=path.name)
        alias = self.base / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            artifacts.export_diagram_bundle(alias, diagram_text=SOURCES["mermaid"].decode())
        self.assertEqual(outside.read_bytes(), SOURCES["mermaid"])

    def test_portable_paths_and_case_aliases_are_rejected(self):
        for path in ("../a", "/a", "a//b", "a/./b", "a\\b", "a%20b", "a:b", "CON.txt", ".git/a", "a. ", "a\x00b", "e\u0301", "a/*", "~home"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                safe_path(path)
        (self.root / "Inputs").mkdir()
        (self.root / "inputs").mkdir()
        (self.root / "inputs/a.mmd").write_bytes(SOURCES["mermaid"])
        with self.assertRaisesRegex(ValueError, "case-aliased"):
            artifacts.export_diagram_bundle(self.root, input_path="inputs/a.mmd")

    def test_publication_race_preserves_concurrent_destination(self):
        real = artifacts.rename_new

        def racing(source_fd, source, target_fd, target):
            os.mkdir(target, dir_fd=target_fd)
            (self.root / artifacts.EXPORT_ROOT / target / "author.txt").write_text("concurrent author work")
            real(source_fd, source, target_fd, target)

        with mock.patch.object(artifacts, "rename_new", side_effect=racing):
            result = artifacts.export_diagram_bundle(self.root, diagram_text=SOURCES["mermaid"].decode(), bundle_id="figure")
        self.assertFalse(result["ok"])
        self.assertEqual((self.root / artifacts.EXPORT_ROOT / "figure/author.txt").read_text(), "concurrent author work")
        self.assertTrue((self.root / result["recovery"]["path"]).exists())

    def test_consumer_staging_ancestor_swap_never_writes_outside(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "sentinel").write_text("preserve")

        def swapped(command, **kwargs):
            result = self.render(command, **kwargs)
            original = self.root / artifacts.EXPORT_ROOT
            original.rename(original.with_name("retained-recovery"))
            original.symlink_to(outside, target_is_directory=True)
            return result

        with mock.patch.object(registry, "_run_renderer", side_effect=swapped):
            result = artifacts.export_diagram_bundle(self.root, diagram_text=SOURCES["mermaid"].decode())
        self.assertFalse(result["ok"])
        self.assertEqual([path.name for path in outside.iterdir()], ["sentinel"])
        self.assertEqual((outside / "sentinel").read_text(), "preserve")

    def test_package_change_requires_restart_and_linked_style_is_rejected(self):
        with mock.patch.object(artifacts, "_STARTUP_SOURCES", {}):
            result = artifacts.export_diagram_bundle(self.root, diagram_text=SOURCES["mermaid"].decode())
        self.assertFalse(result["ok"])
        self.assertIn("restart", result["error"])
        assets = self.base / "assets"
        for name in ("styles", "tools", "compat", "docker"):
            shutil.copytree(registry.repo_dir() / name, assets / name)
        style = assets / "styles/mermaid/benizar-mermaid.json"
        style.rename(style.with_name("real.json"))
        style.symlink_to("real.json")
        with mock.patch.object(registry, "repo_dir", return_value=assets):
            result = artifacts.export_diagram_bundle(self.root, diagram_text=SOURCES["mermaid"].decode())
        self.assertFalse(result["ok"])
        self.assertEqual(self.commands, [])

    def test_json_duplicate_keys_nonfinite_and_limits(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}',
                    b'{"a":' + b'[' * 34 + b'0' + b']' * 34 + b'}', b'{}' + b' ' * (1024 * 1024)):
            with self.subTest(raw=raw[:60]), self.assertRaises(ValueError):
                parse_json(raw)

    def test_initialization_detects_concurrent_ignore_edits(self):
        ignore = self.root / artifacts.EXPORT_ROOT / ".gitignore"
        ignore.parent.mkdir(parents=True)
        ignore.write_text("custom\n")
        write_new = Workspace.write_new

        def edit(workspace, path, data, **kwargs):
            write_new(workspace, path, data, **kwargs)
            if "/ignore-" in path:
                ignore.write_text("concurrent author change\n")

        with mock.patch.object(Workspace, "write_new", edit), self.assertRaisesRegex(ValueError, "changed"):
            artifacts.initialize_artifact_export(self.root)
        self.assertEqual(ignore.read_text(), "concurrent author change\n")
        self.assertTrue(list((self.root / artifacts.STAGING_ROOT).glob("ignore-*")))

    def test_malformed_missing_tampered_and_undeclared_bundles(self):
        result = self.export()
        original_path, original = self.document(result)
        for label in ("unknown", "version", "float", "runtime", "duplicate", "variant", "hash", "missing", "extra", "empty", "hardlink", "symlink", "size", "request", "dependency"):
            with self.subTest(label=label):
                target = self.root / f"mutated-{label}"
                shutil.copytree(original_path.parent, target)
                path = target / "bundle.json"
                doc = json.loads(path.read_bytes())
                sha = result["bundle"]["sha256"]
                if label == "unknown":
                    doc["unreviewed"] = True
                elif label == "version":
                    doc["schema_version"] = True
                elif label == "float":
                    doc["schema_version"] = 1.0
                elif label == "runtime":
                    doc["producer"]["runtimes"][0]["revision"] = "v0.3.0"
                elif label == "duplicate":
                    doc["files"].append(doc["files"][0])
                elif label == "variant":
                    doc["files"][0]["variant_of"] = "source"
                elif label == "hash":
                    (target / doc["files"][0]["path"]).write_bytes(b"tampered")
                elif label == "missing":
                    (target / doc["files"][0]["path"]).unlink()
                elif label == "extra":
                    (target / "undeclared.txt").write_text("extra")
                elif label == "empty":
                    (target / "undeclared-directory").mkdir()
                elif label in {"hardlink", "symlink"}:
                    output = target / doc["files"][0]["path"]
                    output.unlink()
                    if label == "hardlink":
                        os.link(original_path.parent / doc["files"][0]["path"], output)
                    else:
                        output.symlink_to(original_path.parent / doc["files"][0]["path"])
                elif label == "size":
                    doc["files"][0]["bytes"] = True
                elif label == "request":
                    doc["request"] = "source"
                else:
                    doc["dependencies"] = [{"id": "unsupported", "sha256": "a" * 64}]
                sha = self.rewrite(path, doc)
                with self.assertRaises((ValueError, OSError)):
                    artifacts.check_diagram_bundle(self.root, path=f"mutated-{label}/bundle.json", sha256=sha)
                shutil.rmtree(target)

    def test_retained_resource_and_svg_references_are_checked_even_with_new_hashes(self):
        result = self.export()
        path, doc = self.document(result)
        resource = next(item for item in doc["files"] if item["path"].endswith("style-diagram-source.sh"))
        (path.parent / resource["path"]).unlink()
        doc["files"].remove(resource)
        request_item = next(item for item in doc["files"] if item["role"] == "request")
        request_file = path.parent / request_item["path"]
        request = json.loads(request_file.read_bytes())
        request["resources"].remove(resource["path"])
        request_file.write_bytes(json_bytes(request))
        request_item.update(sha256=digest(request_file.read_bytes()), bytes=request_file.stat().st_size)
        sha = self.rewrite(path, doc)
        with self.assertRaisesRegex(ValueError, "incomplete render resource"):
            artifacts.check_diagram_bundle(self.root, path=result["bundle"]["path"], sha256=sha)

    def test_initializer_preserves_custom_ignore_and_is_effective_in_git(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        ignore = self.root / artifacts.EXPORT_ROOT / ".gitignore"
        ignore.parent.mkdir(parents=True)
        ignore.write_bytes(b"# custom\ncustom.tmp\n")
        for _ in range(2):
            self.assertTrue(artifacts.initialize_artifact_export(self.root)["ok"])
        self.assertEqual(ignore.read_bytes(), b"# custom\ncustom.tmp\n/.staging/\n")
        result = self.export()
        ignored = subprocess.run(["git", "-C", str(self.root), "check-ignore", "--quiet", "--", artifacts.STAGING_ROOT + "/x"], check=False)
        self.assertEqual(ignored.returncode, 0)
        retained = subprocess.run(["git", "-C", str(self.root), "check-ignore", "--quiet", "--", result["bundle"]["path"]], check=False)
        self.assertEqual(retained.returncode, 1)

    def test_initializer_rejects_tracked_recovery_and_ignore_links(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        recovery = self.root / artifacts.STAGING_ROOT / "valuable"
        recovery.parent.mkdir(parents=True)
        recovery.write_text("retained")
        subprocess.run(["git", "-C", str(self.root), "add", "--", artifacts.STAGING_ROOT], check=True)
        with self.assertRaisesRegex(ValueError, "tracked"):
            artifacts.initialize_artifact_export(self.root)
        self.assertEqual(recovery.read_text(), "retained")
        outside = self.base / "custom-ignore"
        outside.write_text("keep")
        other = self.base / "another"
        (other / artifacts.EXPORT_ROOT).mkdir(parents=True)
        (other / artifacts.EXPORT_ROOT / ".gitignore").symlink_to(outside)
        with self.assertRaises(OSError):
            artifacts.initialize_artifact_export(other)
        self.assertEqual(outside.read_text(), "keep")

    def test_dry_run_and_cli_do_not_initialize(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(["--project", str(self.root), "export-diagram-bundle", "--text", SOURCES["mermaid"].decode(), "--dry-run"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())["dry_run"])
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.commands, [])

    def test_bounded_reads_detect_concurrent_unlink_and_ancestor_substitution(self):
        (self.root / "source.mmd").write_bytes(SOURCES["mermaid"])
        with Workspace(self.root) as workspace:
            workspace.read("source.mmd")
            original = self.root / "source.mmd"
            original.rename(self.root / "old.mmd")
            original.write_bytes(SOURCES["mermaid"])
            with self.assertRaisesRegex(ValueError, "changed"):
                workspace.recheck()
        with Workspace(self.root) as workspace:
            displaced = self.base / "displaced"
            self.root.rename(displaced)
            self.root.symlink_to(displaced, target_is_directory=True)
            with self.assertRaises(OSError):
                workspace.recheck()
            self.root.unlink()
            displaced.rename(self.root)

    def test_cli_export_and_check_share_the_mcp_api(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(["--project", str(self.root), "export-diagram-bundle", "--text", SOURCES["plantuml"].decode()])
        self.assertEqual(code, 0, output.getvalue())
        result = json.loads(output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["--project", str(self.root), "check-diagram-bundle", result["bundle"]["path"], "--sha256", result["bundle"]["sha256"]])
        self.assertEqual(code, 0)

    def test_cli_stdin_retains_utf8_bytes_without_newline_translation(self):
        stream = io.TextIOWrapper(io.BytesIO(SOURCES["mermaid"]), encoding="utf-8", newline=None)
        output = io.StringIO()
        with mock.patch.object(sys, "stdin", stream), contextlib.redirect_stdout(output):
            code = cli.main(["--project", str(self.root), "export-diagram-bundle", "--stdin"])
        self.assertEqual(code, 0, output.getvalue())
        manifest = self.root / json.loads(output.getvalue())["bundle"]["path"]
        self.assertEqual((manifest.parent / "payload/render/input/source.mmd").read_bytes(), SOURCES["mermaid"])

    @unittest.skipUnless(REFERENCE, "set DIAVISUALS_HANDOFF_REFERENCE to the pinned contract repository")
    def test_pinned_reference_and_relocation_without_producer_job(self):
        with pinned_reference() as (reference, check):
            for kind, sha in (("figure", "d7b298c857f748fb113bd09826239966e32aa301d0df5a3f341f313b167ea784"),
                              ("deck", "ab602be252e02571f4f61b6fdce35c331049d5acdc7592dda5c5ad40c68aca00")):
                self.assertTrue(check(str(reference), "bundle", f"{FIXTURES}/{kind}/bundle.json", sha)["ok"])
            results = [self.export(diagram_text=source.decode(), bundle_id=engine) for engine, source in SOURCES.items()]
            consumer = self.base / "final consumer"
            for result in results:
                self.assertTrue(check(str(self.root), "bundle", **{"path": result["bundle"]["path"], "expected": result["bundle"]["sha256"]})["ok"])
                source = self.root / result["bundle"]["path"]
                shutil.copytree(source.parent, consumer / source.parent.name)
            shutil.rmtree(self.root)
            relocated = self.base / "relocated consumer à"
            consumer.rename(relocated)
            for result in results:
                name = pathlib.PurePosixPath(result["bundle"]["path"]).parent.name
                bundle = {"path": f"{name}/bundle.json", "sha256": result["bundle"]["sha256"]}
                self.assertTrue(artifacts.check_diagram_bundle(relocated, **bundle)["ok"])
                self.assertTrue(check(str(relocated), "bundle", bundle["path"], bundle["sha256"])["ok"])

    @unittest.skipUnless(REFERENCE, "set DIAVISUALS_HANDOFF_REFERENCE to the pinned contract repository")
    def test_pinned_reference_adversarial_suite(self):
        with pinned_reference() as (reference, _):
            completed = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_mcp_artifact_handoff.py"],
                                       cwd=reference, capture_output=True, text=True, check=False, timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertRegex(completed.stderr, r"Ran [1-9][0-9]* tests")


if __name__ == "__main__":
    unittest.main()
