from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from diavisuals.registry import (
    check_styles,
    compatibility_status,
    factory_manifest,
    json_dumps,
    release_status,
    render_diagram,
    render_diagram_text,
    style_audit,
    style_inventory,
    submodule_plan,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class RegistryTest(unittest.TestCase):
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
        status = compatibility_status("mermaid-11.4.2-plantuml-1.2026.1")
        self.assertTrue(status["ok"], status)
        self.assertEqual(status["values"]["MERMAID_CLI_VERSION"], "11.4.2")
        self.assertEqual(status["values"]["PLANTUML_VERSION"], "1.2026.1")
        self.assertIn("kanban", status["values"]["MERMAID_TYPES"])

        path_status = compatibility_status("compat/mermaid-11.4.2-plantuml-1.2026.1.env")
        self.assertTrue(path_status["ok"], path_status)
        self.assertEqual(path_status["requested"], "mermaid-11.4.2-plantuml-1.2026.1")

    def test_factory_manifest_and_submodule_plan(self) -> None:
        manifest = factory_manifest()
        self.assertTrue(manifest["ok"], manifest)
        self.assertEqual(manifest["name"], "diavisuals")
        self.assertIn("style_inventory", manifest["mcp"]["tools"])
        self.assertIn("style_audit", manifest["mcp"]["tools"])
        self.assertIn("render_diagram", manifest["mcp"]["tools"])
        self.assertIn("render_diagram_text", manifest["mcp"]["tools"])
        self.assertEqual(manifest["workspace_rule"]["consumer_root"], ".")
        self.assertIn(".cache/diavisuals", manifest["workspace_rule"]["generated_paths"])

        plan = submodule_plan("/tmp/project", path="docs/slides/resources/diavisuals")
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(plan["release"], "v0.1.2")
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
        self.assertIn("/diavisuals/tools/style-diagram-source.sh", result["command"][-1])
        self.assertIn("styles/mermaid/benizar-mermaid.json", result["command"][-1])

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
        self.assertIn("/diavisuals/tools/style-diagram-source.sh plantuml benizar-plantuml", result["command"][-1])

    def test_render_diagram_text_dry_run_writes_inline_source_and_artifact_metadata(self) -> None:
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
        self.assertIn("/diavisuals/tools/style-diagram-source.sh", result["command"][-1])

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

            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "diavisuals.cli", "--project", str(REPO_ROOT), "mcp", "serve"],
                env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    resources = await session.list_resources()
                    resource_uris = {str(resource.uri) for resource in resources.resources}
                    self.assertIn("diavisuals://styles", resource_uris)
                    self.assertIn("diavisuals://style-audit", resource_uris)
                    self.assertIn("diavisuals://factory-manifest", resource_uris)

                    tools = await session.list_tools()
                    tool_names = {tool.name for tool in tools.tools}
                    self.assertIn("style_inventory", tool_names)
                    self.assertIn("style_audit", tool_names)
                    self.assertIn("submodule_plan", tool_names)
                    self.assertIn("render_diagram_text", tool_names)

                    result = await session.call_tool("style_inventory", {})
                    text = "\n".join(getattr(item, "text", "") for item in result.content)
                    self.assertIn("benizar", text)

                    audit = await session.call_tool("style_audit", {})
                    audit_text = "\n".join(getattr(item, "text", "") for item in audit.content)
                    self.assertIn("vendored-package-assets", audit_text)

        asyncio.run(run_smoke())


if __name__ == "__main__":
    unittest.main()
