from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from diavisuals.registry import (
    check_styles,
    compatibility_status,
    factory_manifest,
    json_dumps,
    release_status,
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

    def test_compatibility_status(self) -> None:
        status = compatibility_status("mermaid-11.4.2-plantuml-1.2026.1")
        self.assertTrue(status["ok"], status)
        self.assertEqual(status["values"]["MERMAID_CLI_VERSION"], "11.4.2")
        self.assertEqual(status["values"]["PLANTUML_VERSION"], "1.2026.1")
        self.assertIn("kanban", status["values"]["MERMAID_TYPES"])

    def test_factory_manifest_and_submodule_plan(self) -> None:
        manifest = factory_manifest()
        self.assertTrue(manifest["ok"], manifest)
        self.assertEqual(manifest["name"], "diavisuals")
        self.assertIn("style_inventory", manifest["mcp"]["tools"])

        plan = submodule_plan("/tmp/project", path="docs/slides/resources/diavisuals")
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(plan["release"], "v0.1.0")
        self.assertEqual(plan["commands"][0][1:3], ["submodule", "add"])

    def test_cli_json(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "diavisuals.cli",
                "style-inventory",
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
        status = release_status("v0.1.0")
        self.assertIn("ok", status)
        self.assertIn("current_head", status)
        self.assertIn("current_matches_release", status)

    def test_json_dumps_is_stable(self) -> None:
        self.assertEqual(json_dumps({"b": 1, "a": 2}).splitlines()[1].strip(), '"a": 2,')

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
                    self.assertIn("diavisuals://factory-manifest", resource_uris)

                    tools = await session.list_tools()
                    tool_names = {tool.name for tool in tools.tools}
                    self.assertIn("style_inventory", tool_names)
                    self.assertIn("submodule_plan", tool_names)

                    result = await session.call_tool("style_inventory", {})
                    text = "\n".join(getattr(item, "text", "") for item in result.content)
                    self.assertIn("benizar", text)

        asyncio.run(run_smoke())


if __name__ == "__main__":
    unittest.main()
