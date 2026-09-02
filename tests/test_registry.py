from __future__ import annotations

import asyncio
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import diavisuals.registry as registry
from diavisuals import mcp_server
from diavisuals.cli import build_parser
from diavisuals.cli import main as cli_main
from diavisuals.registry import (
    build_renderer_image,
    check_styles,
    client_config,
    compatibility_status,
    diagram_artifact_payload,
    factory_check,
    factory_manifest,
    json_dumps,
    project_check,
    release_status,
    render_diagram,
    render_diagram_text,
    style_audit,
    style_inventory,
    submodule_plan,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_IMAGE_ID = "sha256:" + "1" * 64


def docker_mount_source(command: list[str], target: str) -> Path:
    for index, value in enumerate(command):
        if value != "--mount":
            continue
        fields = next(csv.reader([command[index + 1]]))
        options = dict(field.split("=", 1) for field in fields if "=" in field)
        if options.get("target") == target:
            return Path(options["source"])
    raise AssertionError(f"mount target not found: {target}")


class RegistryTest(unittest.TestCase):
    def test_mermaid_style_uses_print_safe_svg_text(self) -> None:
        config = json.loads((REPO_ROOT / "styles/mermaid/benizar-mermaid.json").read_text(encoding="utf-8"))

        self.assertIs(config["htmlLabels"], False)
        self.assertIs(config["flowchart"]["htmlLabels"], False)
        self.assertEqual(config["handDrawnSeed"], 42)
        self.assertIs(config["deterministicIds"], True)

    def test_mermaid_svg_normalizer_preserves_inter_tspan_spaces(self) -> None:
        script = REPO_ROOT / "tools/normalize-mermaid-svg.py"
        with tempfile.TemporaryDirectory() as tmp:
            svg = Path(tmp) / "diagram.svg"
            svg.write_text(
                "<svg><text><tspan>First</tspan><tspan> word</tspan>"
                "<tspan>\u00a0again</tspan></text></svg>",
                encoding="utf-8",
            )

            completed = subprocess.run([sys.executable, str(script), str(svg)], check=False)
            repeated = subprocess.run([sys.executable, str(script), str(svg)], check=False)
            normalized = svg.read_text(encoding="utf-8")

            self.assertEqual(completed.returncode, 0)
            self.assertEqual(repeated.returncode, 0)
            self.assertIn('<tspan xml:space="preserve"> word</tspan>', normalized)
            self.assertIn('<tspan xml:space="preserve"> again</tspan>', normalized)
            self.assertNotIn("\u00a0", normalized)

    def test_style_inventory_and_check(self) -> None:
        inventory = style_inventory()
        self.assertTrue(inventory["ok"], inventory)
        families = {item["family"]: item for item in inventory["families"]}
        self.assertIn("benizar", families)
        self.assertTrue(families["benizar"]["mermaid"]["base_exists"])
        self.assertTrue(families["benizar"]["plantuml"]["base_exists"])
        self.assertGreaterEqual(len(families["benizar"]["mermaid"]["overrides"]), 10)
        self.assertGreaterEqual(len(families["benizar"]["plantuml"]["overrides"]), 10)

        check = check_styles()
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["issues"], [])

    def test_style_audit_checks_tokens_and_rendered_gallery(self) -> None:
        audit = style_audit()
        self.assertTrue(audit["ok"], audit)
        self.assertEqual(audit["contract"]["source"], "vendored-package-assets")
        self.assertEqual(audit["contract"]["styles"]["mermaid"], "benizar-mermaid")
        self.assertEqual(audit["contract"]["styles"]["plantuml"], "benizar-plantuml")
        self.assertGreaterEqual(audit["tokens"]["hex_color_count"], 20)
        self.assertEqual(audit["gallery"]["engines"]["mermaid"]["rendered"], 15)
        self.assertEqual(audit["gallery"]["engines"]["plantuml"]["rendered"], 15)
        self.assertEqual(audit["gallery"]["missing_outputs"], [])

    def test_compatibility_status(self) -> None:
        status = compatibility_status("mermaid-11.16.0-plantuml-1.2026.1")
        self.assertTrue(status["ok"], status)
        self.assertEqual(status["values"]["MERMAID_CLI_VERSION"], "11.16.0")
        self.assertEqual(status["values"]["PUPPETEER_VERSION"], "25.9.0")
        self.assertEqual(status["values"]["PLANTUML_VERSION"], "1.2026.1")
        self.assertEqual(status["status"], "supported-renderer")
        self.assertTrue(status["renderable"])
        self.assertNotIn("DIAVISUALS_RENDER_BUILD_NETWORK", status["values"])
        self.assertEqual(status["values"]["DIAVISUALS_RENDER_IMAGE"], "diavisuals/render:v0.3.0")
        self.assertEqual(
            status["values"]["PLANTUML_SHA256"],
            "89c116168a2a0f7cf5292e11617ba22abd743f891914f1fec5bc9c7d257b3092",
        )
        self.assertIn("kanban", status["values"]["MERMAID_TYPES"])

        path_status = compatibility_status("compat/mermaid-11.16.0-plantuml-1.2026.1.env")
        self.assertTrue(path_status["ok"], path_status)
        self.assertEqual(path_status["requested"], "mermaid-11.16.0-plantuml-1.2026.1")

        legacy = compatibility_status("mermaid-11.4.2-plantuml-1.2026.1")
        self.assertTrue(legacy["ok"], legacy)
        self.assertEqual(legacy["status"], "legacy-record-only")
        self.assertFalse(legacy["renderable"])
        self.assertFalse(registry.renderer_profile("mermaid-11.4.2-plantuml-1.2026.1")["ok"])

    def test_build_renderer_dry_run_uses_checksum_without_host_network(self) -> None:
        result = build_renderer_image("mermaid-11.16.0-plantuml-1.2026.1", dry_run=True)
        self.assertTrue(result["ok"], result)
        command = result["command"]
        self.assertNotIn("--network", command)
        self.assertIn(
            "PLANTUML_SHA256=89c116168a2a0f7cf5292e11617ba22abd743f891914f1fec5bc9c7d257b3092",
            command,
        )

    def test_renderer_lock_name_scopes_docker_endpoint_context_and_image(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"DOCKER_CONTEXT": "", "DOCKER_HOST": "unix:///daemon-one.sock", "XDG_CACHE_HOME": "/tmp/cache-one"},
        ):
            first = registry._renderer_lock_name("diavisuals/render:test")
        with mock.patch.dict(
            os.environ,
            {"DOCKER_CONTEXT": "", "DOCKER_HOST": "unix:///daemon-one.sock", "XDG_CACHE_HOME": "/tmp/cache-two"},
        ):
            same_daemon = registry._renderer_lock_name("diavisuals/render:test")
            other_image = registry._renderer_lock_name("diavisuals/render:other")
        with mock.patch.dict(os.environ, {"DOCKER_CONTEXT": "remote", "DOCKER_HOST": "unix:///daemon-one.sock"}):
            other_context = registry._renderer_lock_name("diavisuals/render:test")

        self.assertEqual(first, same_daemon)
        self.assertNotEqual(first, other_image)
        self.assertNotEqual(first, other_context)

    def test_renderer_build_lock_does_not_mask_body_oserror(self) -> None:
        with self.assertRaisesRegex(OSError, "renderer body failed"):
            with registry._renderer_build_lock("diavisuals/render:test-body-error"):
                raise OSError("renderer body failed")

    def test_factory_manifest_and_submodule_plan(self) -> None:
        manifest = factory_manifest()
        self.assertTrue(manifest["ok"], manifest)
        self.assertEqual(manifest["name"], "diavisuals")
        self.assertIn("style_inventory", manifest["mcp"]["required_tools"])
        self.assertIn("style_audit", manifest["mcp"]["required_tools"])
        self.assertIn("project_check", manifest["mcp"]["required_tools"])
        self.assertIn("render_diagram", manifest["mcp"]["required_tools"])
        self.assertIn("render_diagram_text", manifest["mcp"]["required_tools"])
        self.assertEqual(manifest["commands"]["build"], ["make", "mcp-build"])
        self.assertEqual(manifest["commands"]["check"], ["make", "mcp-check"])
        self.assertEqual(manifest["commands"]["smoke"], ["make", "mcp-smoke"])
        self.assertEqual(manifest["commands"]["init"][-2:], ["init", "${workspaceFolder}"])
        self.assertEqual(manifest["commands"]["down"][-2:], ["down", "${workspaceFolder}"])
        self.assertEqual(manifest["commands"]["serve"][-2:], ["serve", "${workspaceFolder}"])
        self.assertEqual(
            manifest["transport"]["command"],
            ["make", "--no-print-directory", "-C", "${factoryRoot}", "mcp-stdio"],
        )
        self.assertEqual(
            manifest["transport"]["env"],
            {"MCP_CONSUMER_WORKSPACE": "${workspaceFolder}"},
        )
        self.assertEqual(manifest["commands"]["project_check"][-2:], ["project-check", "${workspaceFolder}"])
        self.assertNotIn("client_config", manifest["commands"])
        self.assertEqual(manifest["workspace_rule"]["binding"], "consumer")
        self.assertEqual(manifest["workspace_rule"]["consumer_root"], ".")
        self.assertIn(".cache/diavisuals", manifest["workspace_rule"]["generated_paths"])
        self.assertEqual(manifest["contracts"]["container_consumer_mount"], "none")
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        for variable in ("CURDIR", "INPUT", "OUTPUT", "OUT_DIR", "COMPAT_PROFILE"):
            self.assertNotIn(f"$({variable})", makefile)
        self.assertTrue(factory_check(REPO_ROOT)["ok"], factory_check(REPO_ROOT))

        package_static = registry.yaml.safe_load((REPO_ROOT / "mcp-factory-package.yml").read_text(encoding="utf-8"))
        with mock.patch.object(registry, "source_checkout", return_value=None):
            package_manifest = factory_manifest()
        for key in (
            "schema_version",
            "name",
            "kind",
            "version",
            "description",
            "repository",
            "workspace_rule",
            "runtime",
            "transport",
            "commands",
            "discovery",
            "release",
            "contracts",
            "mcp",
        ):
            self.assertEqual(package_static[key], package_manifest[key], key)
        self.assertEqual(package_manifest["commands"]["build"], ["diavisuals", "ensure-renderer"])
        self.assertEqual(package_manifest["commands"]["check"], ["diavisuals", "lifecycle-check"])
        self.assertEqual(package_manifest["commands"]["smoke"], ["diavisuals", "mcp-smoke"])
        self.assertIn("${workspaceFolder}", package_manifest["commands"]["init"])
        self.assertIn("${workspaceFolder}", package_manifest["commands"]["down"])
        self.assertEqual(package_manifest["commands"]["project_check"][-1], "project-check")
        self.assertNotIn("client_config", package_manifest["commands"])
        package_serialized = json.dumps(package_static)
        for checkout_only in ("${factoryRoot}", "scripts/factory-launcher", '"make"'):
            self.assertNotIn(checkout_only, package_serialized)

        plan = submodule_plan("/tmp/project", path="docs/slides/resources/diavisuals")
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(plan["release"], "v0.3.1")
        self.assertEqual(plan["commands"][0][1:3], ["submodule", "add"])

    def test_cli_json(self) -> None:
        for command in ["style-inventory", "style-audit"]:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "diavisuals.cli",
                    command,
                ],
                cwd=REPO_ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertTrue(payload["ok"])

    def test_release_status_reports_missing_tag_until_released(self) -> None:
        status = release_status("v0.1.2")
        self.assertIn("ok", status)
        self.assertIn("current_head", status)
        self.assertIn("current_matches_release", status)

    def test_json_dumps_is_stable(self) -> None:
        self.assertEqual(json_dumps({"b": 1, "a": 2}).splitlines()[1].strip(), '"a": 2,')

    def test_render_diagram_dry_run_uses_docker_renderer_and_styles(self) -> None:
        source = REPO_ROOT / "examples" / "benizar" / "mermaid" / "flowchart.mmd"
        result = render_diagram(
            REPO_ROOT,
            input_path=str(source.relative_to(REPO_ROOT)),
            output_path="dist/test-render/flowchart.svg",
            dry_run=True,
        )
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["engine"], "mermaid")
        self.assertEqual(result["style"], "benizar-mermaid")
        self.assertEqual(result["command"][0], "docker")
        self.assertEqual(
            result["command"][result["command"].index("--label") + 1],
            "io.context.mcp-factory=diavisuals",
        )
        self.assertIn("/diavisuals/tools/render-one.sh", result["command"])
        self.assertEqual(result["command"][-3:], ["mermaid", "benizar-mermaid", "svg"])
        self.assertIn("PLANTUML_SECURITY_PROFILE=SANDBOX", result["command"])
        self.assertEqual(result["command"][result["command"].index("--network") + 1], "none")
        self.assertIn("--read-only", result["command"])
        self.assertEqual(result["command"][result["command"].index("--cap-drop") + 1], "ALL")
        self.assertIn("no-new-privileges=true", result["command"])
        self.assertNotIn("/workspace", " ".join(result["command"]))
        self.assertNotIn(str(REPO_ROOT), " ".join(result["command"]))

    def test_render_diagram_infers_and_validates_output_format(self) -> None:
        source = REPO_ROOT / "examples" / "benizar" / "mermaid" / "flowchart.mmd"
        inferred = render_diagram(
            REPO_ROOT,
            input_path=str(source.relative_to(REPO_ROOT)),
            output_path="dist/test-render/flowchart.pdf",
            dry_run=True,
        )

        self.assertEqual(inferred["command"][-1], "pdf")
        with self.assertRaisesRegex(ValueError, "does not match"):
            render_diagram(
                REPO_ROOT,
                input_path=str(source.relative_to(REPO_ROOT)),
                output_path="dist/test-render/flowchart.pdf",
                output_format="svg",
                dry_run=True,
            )
        with self.assertRaisesRegex(ValueError, "must be lowercase"):
            render_diagram(
                REPO_ROOT,
                input_path=str(source.relative_to(REPO_ROOT)),
                output_path="dist/test-render/flowchart.SVG",
                dry_run=True,
            )
        with self.assertRaisesRegex(ValueError, "must end with"):
            render_diagram(
                REPO_ROOT,
                input_path=str(source.relative_to(REPO_ROOT)),
                output_path="dist/test-render/flowchart",
                dry_run=True,
            )

    def test_render_diagram_uses_private_staging_for_equal_output_names(self) -> None:
        source = REPO_ROOT / "examples" / "benizar" / "mermaid" / "flowchart.mmd"
        first = render_diagram(
            REPO_ROOT,
            input_path=str(source.relative_to(REPO_ROOT)),
            output_path="dist/first/chart.svg",
            dry_run=True,
        )
        second = render_diagram(
            REPO_ROOT,
            input_path=str(source.relative_to(REPO_ROOT)),
            output_path="dist/second/chart.svg",
            dry_run=True,
        )

        self.assertEqual(first["staging"], "private")
        self.assertEqual(second["staging"], "private")
        self.assertNotEqual(
            first["command"][first["command"].index("--name") + 1],
            second["command"][second["command"].index("--name") + 1],
        )

    def test_render_diagram_dry_run_accepts_explicit_style(self) -> None:
        source = REPO_ROOT / "examples" / "benizar" / "plantuml" / "sequence.puml"
        result = render_diagram(
            REPO_ROOT,
            input_path=str(source.relative_to(REPO_ROOT)),
            output_path="dist/test-render/sequence.svg",
            style="benizar",
            dry_run=True,
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["engine"], "plantuml")
        self.assertEqual(result["style_requested"], "benizar")
        self.assertEqual(result["style"], "benizar-plantuml")
        self.assertEqual(result["command"][-3:], ["plantuml", "benizar-plantuml", "svg"])

    def test_render_mermaid_pdf_fits_the_chart(self) -> None:
        source = REPO_ROOT / "examples" / "benizar" / "mermaid" / "flowchart.mmd"
        render_diagram(
            REPO_ROOT,
            input_path=str(source.relative_to(REPO_ROOT)),
            output_path="dist/test-render/flowchart.pdf",
            output_format="pdf",
            dry_run=True,
        )

        script = (REPO_ROOT / "tools" / "render-one.sh").read_text(encoding="utf-8")
        self.assertIn("command+=(--pdfFit)", script)
        self.assertIn("normalize-mermaid-svg.py", script)

    def test_gallery_renderer_uses_factory_container_label(self) -> None:
        script = (REPO_ROOT / "tools" / "render-gallery-docker.sh").read_text(encoding="utf-8")
        examples = (REPO_ROOT / "tools" / "render-examples.sh").read_text(encoding="utf-8")
        publisher = (REPO_ROOT / "tools" / "publish-gallery.py").read_text(encoding="utf-8")
        self.assertIn("--label io.context.mcp-factory=diavisuals", script)
        self.assertIn("--network none", script)
        self.assertIn("--read-only", script)
        self.assertIn("--cap-drop ALL", script)
        self.assertIn("target=/workspace,readonly", script)
        self.assertIn("source=${workspace},target=/workspace,readonly", script)
        self.assertNotIn("source=${repo_root},target=/workspace,readonly", script)
        self.assertIn("timeout --signal=TERM --kill-after=10s", script)
        self.assertIn("publish-gallery.py", script)
        self.assertIn("gallery output must not be a symlink", publisher)
        self.assertIn("requires libc renameat2", publisher)
        self.assertIn("no Mermaid examples found for family", examples)
        self.assertIn("no PlantUML examples found for family", examples)

    def test_gallery_publisher_reports_missing_renameat2(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "publish_gallery",
            REPO_ROOT / "tools/publish-gallery.py",
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        publisher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publisher)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = root / "result"
            repository = root / "repository"
            result.mkdir()
            (result / "manifest.csv").write_text("manifest\n", encoding="utf-8")
            (repository / "docs/gallery/benizar/test-profile").mkdir(parents=True)

            with mock.patch.object(publisher.ctypes, "CDLL", return_value=object()), self.assertRaisesRegex(
                OSError, "requires libc renameat2"
            ):
                publisher.publish_gallery(result, repository, "benizar", "test-profile")

    def test_gallery_publisher_validates_hidden_entries_and_preserves_current_gallery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository = root / "repository"
            result = root / "result"
            (repository / "docs/gallery").mkdir(parents=True)
            (result / "mermaid").mkdir(parents=True)
            (result / "readme").mkdir()
            (result / "mermaid/flowchart.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
            (result / "readme/flowchart.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (result / "manifest.csv").write_text(
                "engine,type,status,output\n"
                "mermaid,flowchart,rendered,docs/gallery/benizar/test-profile/mermaid/flowchart.svg\n",
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(REPO_ROOT / "tools/publish-gallery.py"),
                str(result),
                str(repository),
                "benizar",
                "test-profile",
            ]

            published = subprocess.run(command, text=True, capture_output=True, check=False)
            target = repository / "docs/gallery/benizar/test-profile"
            self.assertEqual(published.returncode, 0, published.stderr)
            self.assertTrue((target / "mermaid/flowchart.svg").is_file())

            (result / ".hidden").symlink_to(root / "outside")
            rejected = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("must not be a symlink", rejected.stderr)
            self.assertTrue((target / "mermaid/flowchart.svg").is_file())

    def test_client_config_launches_the_installed_python_module(self) -> None:
        config = client_config("/tmp/project")
        server = config["mcpServers"]["diavisuals"]

        self.assertEqual(server["command"], sys.executable)
        self.assertEqual(server["args"], ["-m", "diavisuals.cli", "mcp", "serve"])
        self.assertEqual(server["env"], {"MCP_CONSUMER_WORKSPACE": "/tmp/project"})

    def test_cli_uses_the_literal_consumer_environment_as_its_default_root(self) -> None:
        project = "/tmp/consumer $value $(touch never) `touch never-either`"
        with mock.patch.dict(os.environ, {"MCP_CONSUMER_WORKSPACE": project}):
            args = build_parser().parse_args(["mcp", "serve"])
        self.assertEqual(args.project, project)

    def test_codex_dry_run_registers_the_consumer_environment(self) -> None:
        project = "/tmp/consumer $value $(touch never) `touch never-either`"
        with mock.patch("diavisuals.cli.print_payload") as output:
            result = cli_main(
                [
                    "--project",
                    project,
                    "install-codex-mcp",
                    "--codex-bin",
                    "codex-test",
                    "--dry-run",
                ]
            )
        self.assertEqual(result, 0)
        add = output.call_args.args[0]["add"]
        self.assertIn(f"MCP_CONSUMER_WORKSPACE={project}", add)
        self.assertNotIn("--project", add)

    def test_mcp_consumer_root_is_canonical_before_the_working_directory_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            first = parent / "first"
            second = parent / "second"
            first.mkdir()
            second.mkdir()
            previous = Path.cwd()
            try:
                os.chdir(parent)
                consumer_root = mcp_server._resolve_consumer_root(Path("first"))
                os.chdir(second)
            finally:
                os.chdir(previous)

        self.assertTrue(consumer_root.is_absolute())
        self.assertEqual(consumer_root, first.resolve())

    def test_distinct_consumer_workspaces_publish_state_concurrently_without_crossing(self) -> None:
        with tempfile.TemporaryDirectory() as first_tmp, tempfile.TemporaryDirectory() as second_tmp:
            roots = [Path(first_tmp), Path(second_tmp)]
            names = ["first.mmd", "second.puml"]
            sources = ["flowchart LR\n  A --> B\n", "@startuml\nAlice -> Bob\n@enduml\n"]
            for root, name, content in zip(roots, names, sources, strict=True):
                source = root / "assets/diagrams" / name
                output = Path(str(source) + ".svg")
                source.parent.mkdir(parents=True)
                source.write_text(content, encoding="utf-8")
                output.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>\n", encoding="utf-8")
                os.utime(source, ns=(1_000_000_000, 1_000_000_000))
                os.utime(output, ns=(2_000_000_000, 2_000_000_000))

            def check(root: Path) -> dict[str, object]:
                registry.initialize_project(root)
                return project_check(root)

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(check, roots))

            self.assertTrue(all(result["ok"] for result in results), results)
            receipts = [
                json.loads((root / registry.PROJECT_RECEIPT_PATH).read_text(encoding="utf-8"))
                for root in roots
            ]
            self.assertEqual(receipts[0]["artifacts"][0]["path"], "assets/diagrams/first.mmd.svg")
            self.assertEqual(receipts[1]["artifacts"][0]["path"], "assets/diagrams/second.puml.svg")
            self.assertNotEqual(registry.renderer_workspace_id(roots[0]), registry.renderer_workspace_id(roots[1]))

    def test_initialize_project_is_idempotent_and_does_not_follow_a_raced_cache_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as external_tmp:
            project = Path(tmp)
            external = Path(external_tmp)

            first = registry.initialize_project(project)
            second = registry.initialize_project(project)
            self.assertTrue(first["ok"], first)
            self.assertTrue(second["ok"], second)
            self.assertTrue((project / ".cache/diavisuals").is_dir())

            registry.shutil.rmtree(project / ".cache")
            real_reject = registry.reject_symlink_components

            def race_cache_ancestor(path: Path, root: Path) -> None:
                real_reject(path, root)
                (project / ".cache").symlink_to(external, target_is_directory=True)

            with mock.patch.object(registry, "reject_symlink_components", side_effect=race_cache_ancestor):
                with self.assertRaisesRegex(ValueError, "symlink or unsafe directory"):
                    registry.initialize_project(project)

            self.assertFalse((external / "diavisuals").exists())

    def test_project_check_publishes_exact_unaltraweb_receipt_for_sorted_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            sources = {
                "assets/diagrams/z.mmd": b"flowchart LR\n  A --> B\n",
                "_documentation/diagrams/a.puml": b"@startuml\nAlice -> Bob\n@enduml\n",
            }
            artifacts = {}
            for index, (name, content) in enumerate(sources.items(), start=1):
                source = project / name
                output = Path(str(source) + ".svg")
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(content)
                output_data = f"<svg xmlns='http://www.w3.org/2000/svg' data-index='{index}'/>\n".encode()
                output.write_bytes(output_data)
                os.utime(source, ns=(1_000_000_000, 1_000_000_000))
                os.utime(output, ns=(2_000_000_000, 2_000_000_000))
                artifacts[f"{name}.svg"] = hashlib.sha256(output_data).hexdigest()
            ignored = project / "_pages/ignored.mmd"
            ignored.parent.mkdir()
            ignored.write_text("flowchart LR\n  X --> Y\n", encoding="utf-8")

            result = project_check(project)

            self.assertTrue(result["ok"], result)
            self.assertTrue(result["sources_and_artifacts_read_only"])
            self.assertEqual([item["source"] for item in result["sources"]], sorted(sources))
            receipt = json.loads((project / registry.PROJECT_RECEIPT_PATH).read_text(encoding="utf-8"))
            self.assertEqual(
                set(receipt),
                {"schema_version", "provider", "provider_version", "release", "request_sha256", "ok", "inputs", "artifacts"},
            )
            self.assertEqual(receipt["provider"], "diavisuals")
            self.assertEqual(receipt["provider_version"], registry.__version__)
            self.assertEqual(receipt["release"], registry.DEFAULT_RELEASE)
            self.assertIs(receipt["ok"], True)
            self.assertEqual(receipt["inputs"], [])
            self.assertEqual(
                receipt["artifacts"],
                [{"path": path, "sha256": artifacts[path]} for path in sorted(artifacts)],
            )
            digest = hashlib.sha256(registry.PROJECT_RECEIPT_PREFIX)
            for name in sorted(sources):
                name_bytes = name.encode("utf-8")
                digest.update(len(name_bytes).to_bytes(8, "big"))
                digest.update(name_bytes)
                digest.update(len(sources[name]).to_bytes(8, "big"))
                digest.update(sources[name])
            self.assertEqual(receipt["request_sha256"], digest.hexdigest())

    def test_project_check_removes_receipt_for_missing_or_modified_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source = project / "assets/diagrams/flow.mmd"
            output = Path(str(source) + ".svg")
            source.parent.mkdir(parents=True)
            source.write_text("flowchart LR\n  A --> B\n", encoding="utf-8")

            receipt = project / registry.PROJECT_RECEIPT_PATH
            receipt.parent.mkdir(parents=True)
            receipt.write_text('{"stale":true}\n', encoding="utf-8")
            missing = project_check(project)
            self.assertFalse(missing["ok"])
            self.assertEqual(missing["sources"][0]["state"], "missing")
            self.assertFalse(receipt.exists())

            output.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>\n", encoding="utf-8")
            os.utime(source, ns=(1_000_000_000, 1_000_000_000))
            os.utime(output, ns=(2_000_000_000, 2_000_000_000))
            fresh = project_check(project)
            self.assertTrue(fresh["ok"], fresh)
            self.assertTrue(receipt.is_file())

            source.write_text("flowchart LR\n  A --> C\n", encoding="utf-8")
            os.utime(source, ns=(3_000_000_000, 3_000_000_000))
            modified = project_check(project)
            self.assertFalse(modified["ok"])
            self.assertEqual(modified["sources"][0]["state"], "stale")
            self.assertFalse(receipt.exists())

    def test_project_check_prefers_edited_svg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source = project / "_chapters/flow.mermaid"
            generated = Path(str(source) + ".svg")
            edited = Path(str(source) + ".edited.svg")
            source.parent.mkdir(parents=True)
            source.write_text("flowchart LR\n  A --> B\n", encoding="utf-8")
            generated.write_text("<svg data-version='generated'/>\n", encoding="utf-8")
            edited_data = b"<svg data-version='edited'/>\n"
            edited.write_bytes(edited_data)
            os.utime(source, ns=(1_000_000_000, 1_000_000_000))
            os.utime(generated, ns=(2_000_000_000, 2_000_000_000))
            os.utime(edited, ns=(3_000_000_000, 3_000_000_000))

            result = project_check(project)

            self.assertTrue(result["ok"], result)
            self.assertTrue(result["sources"][0]["edited_override"])
            receipt = json.loads((project / registry.PROJECT_RECEIPT_PATH).read_text(encoding="utf-8"))
            self.assertEqual(
                receipt["artifacts"],
                [{"path": "_chapters/flow.mermaid.edited.svg", "sha256": hashlib.sha256(edited_data).hexdigest()}],
            )

    def test_project_check_rejects_symlinked_output_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as external_tmp:
            project = Path(tmp)
            external = Path(external_tmp) / "outside.svg"
            source = project / "assets/diagrams/flow.puml"
            output = Path(str(source) + ".svg")
            source.parent.mkdir(parents=True)
            source.write_text("@startuml\nAlice -> Bob\n@enduml\n", encoding="utf-8")
            external.write_text("<svg data-outside='preserve'/>\n", encoding="utf-8")
            output.symlink_to(external)

            result = project_check(project)

            self.assertFalse(result["ok"])
            self.assertEqual(result["sources"][0]["state"], "invalid")
            self.assertIn("without following symlinks", result["sources"][0]["error"])
            self.assertEqual(external.read_text(encoding="utf-8"), "<svg data-outside='preserve'/>\n")
            self.assertFalse((project / registry.PROJECT_RECEIPT_PATH).exists())

    def test_project_check_never_follows_receipt_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as external_tmp:
            project = Path(tmp)
            external = Path(external_tmp)
            source = project / "assets/diagrams/flow.uml"
            output = Path(str(source) + ".svg")
            source.parent.mkdir(parents=True)
            source.write_text("@startuml\nAlice -> Bob\n@enduml\n", encoding="utf-8")
            output.write_text("<svg/>\n", encoding="utf-8")
            os.utime(source, ns=(1_000_000_000, 1_000_000_000))
            os.utime(output, ns=(2_000_000_000, 2_000_000_000))
            external_receipt = external / "receipts/diavisuals.json"
            external_receipt.parent.mkdir()
            external_receipt.write_text("outside\n", encoding="utf-8")
            (project / ".unaltraweb").symlink_to(external, target_is_directory=True)

            attacked = project_check(project)

            self.assertFalse(attacked["ok"])
            self.assertIn("receipt publication failed", attacked["issues"][0])
            self.assertEqual(external_receipt.read_text(encoding="utf-8"), "outside\n")
            self.assertEqual(list(external_receipt.parent.iterdir()), [external_receipt])

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as external_tmp:
            project = Path(tmp)
            source = project / "assets/diagrams/missing.mmd"
            source.parent.mkdir(parents=True)
            source.write_text("flowchart LR\n  A --> B\n", encoding="utf-8")
            external_receipt = Path(external_tmp) / "outside.json"
            external_receipt.write_text("outside\n", encoding="utf-8")
            receipt = project / registry.PROJECT_RECEIPT_PATH
            receipt.parent.mkdir(parents=True)
            receipt.symlink_to(external_receipt)

            invalid = project_check(project)

            self.assertFalse(invalid["ok"])
            self.assertFalse(receipt.exists())
            self.assertEqual(external_receipt.read_text(encoding="utf-8"), "outside\n")

    def test_project_check_invalidates_old_receipt_when_atomic_publication_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source = project / "assets/diagrams/flow.mmd"
            output = Path(str(source) + ".svg")
            source.parent.mkdir(parents=True)
            source.write_text("flowchart LR\n  A --> B\n", encoding="utf-8")
            output.write_text("<svg/>\n", encoding="utf-8")
            os.utime(source, ns=(1_000_000_000, 1_000_000_000))
            os.utime(output, ns=(2_000_000_000, 2_000_000_000))
            receipt = project / registry.PROJECT_RECEIPT_PATH
            receipt.parent.mkdir(parents=True)
            receipt.write_text('{"stale":true}\n', encoding="utf-8")

            with mock.patch.object(registry.os, "replace", side_effect=OSError("simulated publication failure")):
                result = project_check(project)

            self.assertFalse(result["ok"])
            self.assertIn("simulated publication failure", result["issues"][0])
            self.assertFalse(receipt.exists())
            self.assertEqual(list(receipt.parent.iterdir()), [])

    def test_down_removes_only_valid_container_ids_for_the_selected_workspace(self) -> None:
        listed = {
            "command": ["docker"],
            "returncode": 0,
            "stdout": f"{'a' * 12}\n{'b' * 64}\n",
            "stderr": "",
        }
        removed = {"command": ["docker"], "returncode": 0, "stdout": "", "stderr": ""}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            registry.shutil, "which", return_value="/usr/bin/docker"
        ), mock.patch.object(registry, "run", side_effect=[listed, removed]) as runner:
            root = Path(tmp).resolve()
            result = registry.down_factory(root)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["containers"], ["a" * 12, "b" * 64])
        workspace_id = registry.renderer_workspace_id(root)
        self.assertEqual(
            runner.call_args_list[0].args[0],
            [
                "/usr/bin/docker",
                "container",
                "ls",
                "--all",
                "--quiet",
                "--filter",
                "label=io.context.mcp-factory=diavisuals",
                "--filter",
                f"label=io.context.mcp-factory.workspace={workspace_id}",
            ],
        )
        self.assertEqual(
            runner.call_args_list[1].args[0],
            ["/usr/bin/docker", "container", "rm", "--force", "a" * 12, "b" * 64],
        )

    def test_down_rejects_invalid_container_ids_without_cleanup(self) -> None:
        listed = {
            "command": ["docker"],
            "returncode": 0,
            "stdout": "not-a-container\n",
            "stderr": "",
        }
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            registry.shutil, "which", return_value="/usr/bin/docker"
        ), mock.patch.object(registry, "run", return_value=listed) as runner:
            result = registry.down_factory(tmp)

        self.assertFalse(result["ok"])
        self.assertIn("invalid container identifier", result["message"])
        self.assertEqual(runner.call_count, 1)

    def test_render_diagram_text_dry_run_does_not_write_inline_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = render_diagram_text(
                tmp,
                diagram_text="flowchart TD\n  A --> B\n",
                output_format="svg",
                dry_run=True,
            )

            project = Path(tmp)
            source = project / result["input_source"]

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["inline"])
        self.assertEqual(result["engine"], "mermaid")
        self.assertEqual(result["style"], "benizar-mermaid")
        self.assertEqual(result["artifact"]["format"], "svg")
        self.assertEqual(result["artifact"]["mime_type"], "image/svg+xml")
        self.assertFalse(result["artifact"]["exists"])
        self.assertTrue(source.name.endswith(".mmd"))
        self.assertFalse(source.exists())
        self.assertFalse((project / ".cache").exists())
        self.assertIn("/diavisuals/tools/render-one.sh", result["command"])

    def test_render_diagram_text_dry_run_detects_plantuml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = render_diagram_text(
                tmp,
                diagram_text="@startuml\nAlice -> Bob: hello\n@enduml\n",
                output_format="png",
                dry_run=True,
            )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["engine"], "plantuml")
        self.assertEqual(result["style"], "benizar-plantuml")
        self.assertEqual(result["artifact"]["format"], "png")
        self.assertEqual(result["artifact"]["mime_type"], "image/png")

    def test_render_diagram_text_dry_run_does_not_follow_symlinked_output_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as external_tmp:
            project = Path(tmp)
            external = Path(external_tmp)
            (project / ".cache").symlink_to(external, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "contains a symlink"):
                render_diagram_text(
                    project,
                    diagram_text="flowchart TD\n  A --> B\n",
                    dry_run=True,
                )

    def test_renderer_command_has_complete_isolation_policy_and_unique_name(self) -> None:
        source = REPO_ROOT / "examples" / "benizar" / "mermaid" / "flowchart.mmd"
        first = render_diagram(
            REPO_ROOT,
            input_path=str(source.relative_to(REPO_ROOT)),
            output_path="dist/test-render/policy.svg",
            dry_run=True,
        )
        second = render_diagram(
            REPO_ROOT,
            input_path=str(source.relative_to(REPO_ROOT)),
            output_path="dist/test-render/policy.svg",
            dry_run=True,
        )
        command = first["command"]

        self.assertEqual(command[command.index("--network") + 1], "none")
        self.assertIn("--read-only", command)
        self.assertEqual(command[command.index("--cap-drop") + 1], "ALL")
        self.assertEqual(command[command.index("--security-opt") + 1], "no-new-privileges=true")
        self.assertEqual(command[command.index("--memory") + 1], registry.RENDERER_MEMORY)
        self.assertEqual(command[command.index("--memory-swap") + 1], registry.RENDERER_MEMORY)
        self.assertEqual(command[command.index("--cpus") + 1], registry.RENDERER_CPUS)
        self.assertEqual(command[command.index("--pids-limit") + 1], registry.RENDERER_PIDS_LIMIT)
        self.assertIn(f"nofile={registry.RENDERER_NOFILE_LIMIT}", command)
        self.assertIn(f"fsize={registry.RENDERER_FSIZE_LIMIT}", command)
        self.assertEqual(command[command.index("--tmpfs") + 1], registry.RENDERER_TMPFS)
        self.assertNotEqual(command[command.index("--user") + 1].split(":", 1)[0], "0")

        labels = [command[index + 1] for index, value in enumerate(command) if value == "--label"]
        self.assertIn("io.context.mcp-factory=diavisuals", labels)
        self.assertTrue(any(label.startswith("io.context.mcp-factory.workspace=") for label in labels))
        self.assertNotEqual(
            command[command.index("--name") + 1],
            second["command"][second["command"].index("--name") + 1],
        )

        mounts = [command[index + 1] for index, value in enumerate(command) if value == "--mount"]
        self.assertEqual(len(mounts), 2)
        self.assertIn("target=/diavisuals,readonly", mounts[0])
        self.assertIn("target=/output", mounts[1])
        self.assertNotIn("readonly", mounts[1])
        self.assertNotIn(str(REPO_ROOT), " ".join(mounts))

    def test_renderer_mounts_csv_encode_commas_and_quotes(self) -> None:
        bundle = Path('/tmp/diavisuals,stage"quoted/bundle')
        result = bundle.parent / "result"
        command = registry.build_renderer_command(
            root=REPO_ROOT,
            renderer={"image": "diavisuals/render:test"},
            engine="mermaid",
            style_name="benizar-mermaid",
            output_format="svg",
            bundle=bundle,
            result=result,
            cidfile=bundle.parent / "container.cid",
            container_name="diavisuals-test",
        )

        self.assertEqual(docker_mount_source(command, "/diavisuals"), bundle)
        self.assertEqual(docker_mount_source(command, "/output"), result)
        mounts = [command[index + 1] for index, value in enumerate(command) if value == "--mount"]
        self.assertTrue(all('""' in mount for mount in mounts))

    def test_renderer_user_never_maps_host_root(self) -> None:
        with mock.patch.object(registry.os, "getuid", return_value=0), mock.patch.object(
            registry.os, "getgid", return_value=0
        ):
            self.assertEqual(registry.renderer_user(), registry.RENDERER_FALLBACK_UID_GID)

    def test_render_stages_minimal_bundle_and_publishes_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source = project / "diagram.mmd"
            source.write_text("flowchart TD\n  A --> B\n", encoding="utf-8")
            linked = project / "linked.svg"
            linked.write_text("<svg><!-- old linked data --></svg>\n", encoding="utf-8")
            output = project / "diagram.svg"
            os.link(linked, output)

            def fake_run(command: list[str], **kwargs: object) -> dict[str, object]:
                bundle = docker_mount_source(command, "/diavisuals")
                result_dir = docker_mount_source(command, "/output")
                files = {path.relative_to(bundle).as_posix() for path in bundle.rglob("*") if path.is_file()}

                self.assertIn("input/source.mmd", files)
                self.assertIn("styles/mermaid/benizar-mermaid.json", files)
                self.assertIn("styles/mermaid/benizar-mermaid/flowchart.mmd", files)
                self.assertIn("tools/render-one.sh", files)
                self.assertIn("tools/style-diagram-source.sh", files)
                self.assertIn("tools/resolve-style-name.sh", files)
                self.assertIn("tools/normalize-mermaid-svg.py", files)
                self.assertFalse(any(path.startswith("docs/") for path in files))
                self.assertFalse(any(path.startswith("examples/") for path in files))
                self.assertFalse(any(path.startswith("tokens/") for path in files))
                self.assertEqual((bundle / "input/source.mmd").read_text(encoding="utf-8"), source.read_text(encoding="utf-8"))
                self.assertNotIn(str(project), " ".join(command))
                self.assertNotIn(str(REPO_ROOT), " ".join(command))
                self.assertIn(TEST_IMAGE_ID, command)
                self.assertNotIn("diavisuals/render:v0.3.0", command)

                (result_dir / "artifact.svg").write_text("<svg><!-- new data --></svg>\n", encoding="utf-8")
                return {
                    "command": command,
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                    "timed_out": False,
                    "cleanup": {"ok": True},
                }

            with mock.patch.object(
                registry, "ensure_renderer_image", return_value={"ok": True, "image_id": TEST_IMAGE_ID}
            ), mock.patch.object(
                registry, "_run_renderer", side_effect=fake_run
            ):
                result = render_diagram(
                    project,
                    input_path="diagram.mmd",
                    output_path="diagram.svg",
                )

            self.assertTrue(result["ok"], result)
            self.assertEqual(output.read_text(encoding="utf-8"), "<svg><!-- new data --></svg>\n")
            self.assertEqual(linked.read_text(encoding="utf-8"), "<svg><!-- old linked data --></svg>\n")
            self.assertEqual(list(project.glob(".diagram.svg.*.tmp")), [])

    def test_render_failure_and_invalid_artifact_leave_existing_output_unchanged(self) -> None:
        cases = [(1, "<svg><!-- unused --></svg>\n"), (0, "not an svg\n")]
        for returncode, staged_data in cases:
            with self.subTest(returncode=returncode, staged_data=staged_data), tempfile.TemporaryDirectory() as tmp:
                project = Path(tmp)
                (project / "diagram.mmd").write_text("flowchart TD\n  A --> B\n", encoding="utf-8")
                output = project / "diagram.svg"
                output.write_text("<svg><!-- existing --></svg>\n", encoding="utf-8")

                def fake_run(command: list[str], **kwargs: object) -> dict[str, object]:
                    result_dir = docker_mount_source(command, "/output")
                    (result_dir / "artifact.svg").write_text(staged_data, encoding="utf-8")
                    return {
                        "command": command,
                        "returncode": returncode,
                        "stdout": "",
                        "stderr": "render failed" if returncode else "",
                        "timed_out": False,
                        "cleanup": {"ok": True},
                    }

                with mock.patch.object(
                    registry, "ensure_renderer_image", return_value={"ok": True, "image_id": TEST_IMAGE_ID}
                ), mock.patch.object(
                    registry, "_run_renderer", side_effect=fake_run
                ):
                    result = render_diagram(project, input_path="diagram.mmd", output_path="diagram.svg")

                self.assertFalse(result["ok"], result)
                self.assertEqual(output.read_text(encoding="utf-8"), "<svg><!-- existing --></svg>\n")
                self.assertEqual(list(project.glob(".diagram.svg.*.tmp")), [])

    def test_render_rejects_symlink_artifact_from_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "diagram.mmd").write_text("flowchart TD\n  A --> B\n", encoding="utf-8")
            secret = project / "secret.svg"
            secret.write_text("<svg><!-- must not publish --></svg>\n", encoding="utf-8")
            output = project / "diagram.svg"
            output.write_text("<svg><!-- existing --></svg>\n", encoding="utf-8")

            def fake_run(command: list[str], **kwargs: object) -> dict[str, object]:
                result_dir = docker_mount_source(command, "/output")
                (result_dir / "artifact.svg").symlink_to(secret)
                return {
                    "command": command,
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                    "timed_out": False,
                    "cleanup": {"ok": True},
                }

            with mock.patch.object(
                registry, "ensure_renderer_image", return_value={"ok": True, "image_id": TEST_IMAGE_ID}
            ), mock.patch.object(
                registry, "_run_renderer", side_effect=fake_run
            ):
                result = render_diagram(project, input_path="diagram.mmd", output_path="diagram.svg")

            self.assertFalse(result["ok"], result)
            self.assertIn("not a regular file", result["artifact_check"]["reason"])
            self.assertEqual(output.read_text(encoding="utf-8"), "<svg><!-- existing --></svg>\n")
            self.assertEqual(secret.read_text(encoding="utf-8"), "<svg><!-- must not publish --></svg>\n")

    def test_render_rejects_traversal_symlinks_equal_paths_and_unsafe_style_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source = project / "diagram.mmd"
            source.write_text("flowchart TD\n  A --> B\n", encoding="utf-8")
            source_link = project / "source-link.mmd"
            source_link.symlink_to(source)
            output_target = project / "target.svg"
            output_target.write_text("<svg/>\n", encoding="utf-8")
            output_link = project / "output.svg"
            output_link.symlink_to(output_target)

            with self.assertRaisesRegex(ValueError, "outside the project root"):
                render_diagram(project, input_path="diagram.mmd", output_path="../outside.svg", dry_run=True)
            with self.assertRaisesRegex(ValueError, "contains a symlink"):
                render_diagram(project, input_path="source-link.mmd", output_path="safe.svg", dry_run=True)
            with self.assertRaisesRegex(ValueError, "contains a symlink"):
                render_diagram(project, input_path="diagram.mmd", output_path="output.svg", dry_run=True)
            with self.assertRaisesRegex(ValueError, "must be different"):
                render_diagram(
                    project,
                    input_path="diagram.mmd",
                    output_path="diagram.mmd",
                    engine="mermaid",
                    output_format="svg",
                    dry_run=True,
                )
            with self.assertRaisesRegex(ValueError, "simple ASCII name"):
                render_diagram(
                    project,
                    input_path="diagram.mmd",
                    output_path="safe.svg",
                    style="../benizar",
                    dry_run=True,
                )

    def test_inline_payload_omits_oversized_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "large.svg"
            with artifact.open("wb") as handle:
                handle.write(b"<svg>")
                handle.truncate(registry.MAX_INLINE_ARTIFACT_BYTES + 1)

            payload = diagram_artifact_payload(artifact, root, "svg", include_data=True)

        self.assertTrue(payload["exists"])
        self.assertFalse(payload["data_included"])
        self.assertNotIn("svg", payload)
        self.assertNotIn("data_base64", payload)

    def test_rendered_artifact_size_limit_rejects_oversized_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "large.pdf"
            with artifact.open("wb") as handle:
                handle.write(b"%PDF-1.7\n")
                handle.truncate(registry.MAX_RENDERED_ARTIFACT_BYTES + 1)

            result = registry.validate_rendered_artifact(artifact, "pdf")

        self.assertFalse(result["ok"])
        self.assertIn("exceeds", result["reason"])

    def test_inline_source_size_limit_is_enforced_before_docker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "diagram source exceeds"):
                render_diagram_text(
                    tmp,
                    diagram_text="flowchart TD\n" + "A-->B\n" * 700000,
                    output_format="svg",
                )

    def test_growing_file_is_bounded_during_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "growing.mmd"
            source.write_bytes(b"x" * (registry.MAX_DIAGRAM_SOURCE_BYTES + 1))
            (root / "stage").mkdir()
            real_metadata = source.stat()
            stale_metadata = os.stat_result(
                (
                    real_metadata.st_mode,
                    real_metadata.st_ino,
                    real_metadata.st_dev,
                    real_metadata.st_nlink,
                    real_metadata.st_uid,
                    real_metadata.st_gid,
                    1,
                    real_metadata.st_atime,
                    real_metadata.st_mtime,
                    real_metadata.st_ctime,
                )
            )

            with mock.patch.object(registry.os, "fstat", return_value=stale_metadata), self.assertRaisesRegex(
                ValueError, "diagram source exceeds"
            ):
                registry.stage_renderer_bundle(
                    root / "stage",
                    source=source,
                    source_root=root,
                    source_data=None,
                    engine="mermaid",
                    style_name="benizar-mermaid",
                    output_format="svg",
                )

    def test_plantuml_stage_contains_only_plantuml_assets_and_common_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stage_root = Path(tmp)
            stage = registry.stage_renderer_bundle(
                stage_root,
                source=stage_root / "unused.puml",
                source_data=b"@startuml\nAlice -> Bob\n@enduml\n",
                engine="plantuml",
                style_name="benizar-plantuml",
                output_format="png",
            )
            files = {
                path.relative_to(stage["bundle"]).as_posix()
                for path in stage["bundle"].rglob("*")
                if path.is_file()
            }

        self.assertIn("input/source.puml", files)
        self.assertIn("styles/plantuml/benizar-plantuml.puml", files)
        self.assertIn("styles/plantuml/benizar-plantuml/sequence.puml", files)
        self.assertIn("tools/render-one.sh", files)
        self.assertNotIn("tools/normalize-mermaid-svg.py", files)
        self.assertFalse(any(path.startswith("styles/mermaid/") for path in files))

    def test_renderer_diagnostics_are_bounded_and_container_is_cleaned_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            registry, "_remove_renderer_container", return_value={"ok": True}
        ) as remove:
            result = registry._run_renderer(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.write('o' * 150000); sys.stderr.write('e' * 150000)",
                ],
                container_name="diavisuals-test-bounded",
                cwd=Path(tmp),
                timeout=10,
            )

        self.assertEqual(result["returncode"], 0)
        self.assertLessEqual(len(result["stdout"].encode("utf-8")), registry.MAX_RENDER_DIAGNOSTIC_BYTES)
        self.assertLessEqual(len(result["stderr"].encode("utf-8")), registry.MAX_RENDER_DIAGNOSTIC_BYTES)
        remove.assert_called_once_with("diavisuals-test-bounded")

    def test_renderer_timeout_kills_client_and_cleans_up_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            registry, "_remove_renderer_container", return_value={"ok": True}
        ) as remove:
            result = registry._run_renderer(
                [sys.executable, "-c", "import time; time.sleep(2)"],
                container_name="diavisuals-test-timeout",
                cwd=Path(tmp),
                timeout=0.05,
            )

        self.assertTrue(result["timed_out"])
        self.assertNotEqual(result["returncode"], 0)
        self.assertIn("timed out", result["stderr"])
        remove.assert_called_once_with("diavisuals-test-timeout")

    def test_renderer_cleanup_failure_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            registry, "_remove_renderer_container", return_value={"ok": False}
        ):
            result = registry._run_renderer(
                [sys.executable, "-c", "pass"],
                container_name="diavisuals-test-cleanup",
                cwd=Path(tmp),
                timeout=10,
            )

        self.assertFalse(result["cleanup"]["ok"])
        self.assertIn("cleanup could not be verified", result["stderr"])

    def test_renderer_assets_pin_base_digest_checksum_and_nonroot_user(self) -> None:
        dockerfile = (REPO_ROOT / "docker/compat-renderer.Dockerfile").read_text(encoding="utf-8")
        self.assertIn(
            "ghcr.io/puppeteer/puppeteer:25.9.0@sha256:5c341215d78353c3416b6c92aae9fac66e8f11c146c3753234980443d6792f8f",
            dockerfile,
        )
        self.assertIn("chrome/linux-152.0.7977.54/chrome-linux64/chrome", dockerfile)
        self.assertIn("89c116168a2a0f7cf5292e11617ba22abd743f891914f1fec5bc9c7d257b3092", dockerfile)
        self.assertIn("sha256sum -c -", dockerfile)
        self.assertIn("USER 65532:65532", dockerfile)
        self.assertIn('chmod 0644 "/output/artifact.${output_format}"', (REPO_ROOT / "tools/render-one.sh").read_text())
        completed = subprocess.run(
            ["bash", "-n", str(REPO_ROOT / "tools/render-one.sh")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_plantuml_renderer_blocks_workspace_includes_when_enabled(self) -> None:
        if os.environ.get("DIAVISUALS_MCP_SMOKE") != "1":
            self.skipTest("set DIAVISUALS_MCP_SMOKE=1 to run the Docker security smoke test")

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "secret.puml").write_text("Alice -> Bob : secret\n", encoding="utf-8")
            existing = project / "existing.svg"
            existing.write_text("<svg><!-- stale marker --></svg>\n", encoding="utf-8")
            result = render_diagram_text(
                project,
                diagram_text="@startuml\n!include /workspace/secret.puml\n@enduml\n",
                engine="plantuml",
                output_path="existing.svg",
                output_format="svg",
                include_data=True,
            )

            self.assertFalse(result["ok"], result)
            self.assertNotEqual(result["result"]["returncode"], 0)
            self.assertFalse(result["artifact"]["exists"])
            self.assertNotIn("svg", result["artifact"])
            self.assertNotIn("data_base64", result["artifact"])
            self.assertEqual(existing.read_text(encoding="utf-8"), "<svg><!-- stale marker --></svg>\n")

    def test_mcp_module_imports_when_dependency_available(self) -> None:
        if importlib.util.find_spec("mcp") is None:
            self.skipTest("mcp optional dependency is not installed")
        import diavisuals.mcp_server  # noqa: F401

    def test_mcp_stdio_smoke_when_enabled(self) -> None:
        if os.environ.get("DIAVISUALS_MCP_SMOKE") != "1":
            self.skipTest("set DIAVISUALS_MCP_SMOKE=1 to run the MCP stdio smoke test")
        if importlib.util.find_spec("mcp") is None:
            self.skipTest("mcp optional dependency is not installed")

        async def run_smoke() -> None:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            with tempfile.TemporaryDirectory() as temporary:
                project = Path(temporary) / "consumer $dollar $(shell printf make-expanded) `printf tick-expanded`"
                project.mkdir()
                factory_root = os.environ.get("DIAVISUALS_MCP_FACTORY_ROOT")
                environment = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
                if factory_root:
                    factory = Path(factory_root).resolve()
                    manifest = registry.yaml.safe_load((factory / "mcp-factory.yml").read_text(encoding="utf-8"))
                    transport = manifest["transport"]

                    def expand(value: object) -> str:
                        return str(value).replace("${factoryRoot}", str(factory)).replace(
                            "${workspaceFolder}", str(project)
                        )

                    transport_command = [expand(value) for value in transport["command"]]
                    command, *arguments = transport_command
                    environment.update(
                        {str(key): expand(value) for key, value in transport.get("env", {}).items()}
                    )
                else:
                    command = sys.executable
                    arguments = ["-m", "diavisuals.cli", "--project", str(project), "mcp", "serve"]
                params = StdioServerParameters(command=command, args=arguments, env=environment)
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        resources = await session.list_resources()
                        resource_uris = {str(resource.uri) for resource in resources.resources}
                        self.assertIn("diavisuals://styles", resource_uris)
                        self.assertIn("diavisuals://style-audit", resource_uris)
                        self.assertIn("diavisuals://project/check", resource_uris)
                        self.assertIn("diavisuals://factory-manifest", resource_uris)

                        tools = await session.list_tools()
                        tool_names = {tool.name for tool in tools.tools}
                        self.assertIn("style_inventory", tool_names)
                        self.assertIn("style_audit", tool_names)
                        self.assertIn("submodule_plan", tool_names)
                        self.assertIn("project_check", tool_names)
                        self.assertIn("render_diagram_text", tool_names)

                        result = await session.call_tool("style_inventory", {})
                        text = "\n".join(getattr(item, "text", "") for item in result.content)
                        self.assertIn("benizar", text)

                        audit = await session.call_tool("style_audit", {})
                        audit_text = "\n".join(getattr(item, "text", "") for item in audit.content)
                        self.assertIn("vendored-package-assets", audit_text)

                        render = await session.call_tool(
                            "render_diagram_text",
                            {
                                "diagram_text": "flowchart TD\n  A --> B\n",
                                "include_data": False,
                                "dry_run": True,
                            },
                        )
                        render_text = "\n".join(getattr(item, "text", "") for item in render.content)
                        render_payload = json.loads(render_text)
                        self.assertEqual(render_payload["project"], str(project))
                        self.assertEqual(render_payload["style"], "benizar-mermaid")
                        self.assertTrue(render_payload["dry_run"])

                        invalid = await session.call_tool(
                            "render_diagram",
                            {
                                "input_path": "../outside.mmd",
                                "output_path": "diagram.svg",
                                "dry_run": True,
                            },
                        )
                        self.assertTrue(invalid.isError)
                        invalid_text = "\n".join(getattr(item, "text", "") for item in invalid.content)
                        self.assertIn("outside the project root", invalid_text)
                        self.assertIsNotNone(invalid.structuredContent)
                        self.assertIs(invalid.structuredContent["ok"], False)
                        self.assertIn("outside the project root", invalid.structuredContent["error"])

        asyncio.run(run_smoke())


if __name__ == "__main__":
    unittest.main()
