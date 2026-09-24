from __future__ import annotations

import asyncio
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

if os.environ.get("DIAVISUALS_INSTALLED") != "1":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from diavisuals import artifacts, registry  # noqa: E402
from tests.handoff_reference import REFERENCE, pinned_reference  # noqa: E402


@unittest.skipUnless(os.environ.get("DIAVISUALS_DOCKER_SMOKE") == "1", "set DIAVISUALS_DOCKER_SMOKE=1")
class ArtifactRuntimeTest(unittest.TestCase):
    def test_real_engine_file_inline_formats_variants_and_relocation(self):
        with tempfile.TemporaryDirectory(prefix="diavisuals-real-bundles-") as temporary:
            base = pathlib.Path(temporary)
            root = base / "producer job à"
            root.mkdir()
            receiver = base / "receiver"
            results = []
            for engine, suffix, source in (
                ("mermaid", "mmd", "flowchart LR\n A[Producer] --> B[Consumer]\n"),
                ("plantuml", "puml", "@startuml\nAlice -> Bob : Producer\n@enduml\n"),
            ):
                path = root / f"source.{suffix}"
                path.write_text(source)
                original = registry.render_diagram(root, input_path=path.name, output_path=f"{engine}.svg")
                self.assertTrue(original["ok"], original)
                edited_path = root / f"{engine}.edited.svg"
                edited_path.write_bytes((root / f"{engine}.svg").read_bytes().replace(b"Producer", b"Reviewed"))
                for mode, output_format in (("file", "svg"), ("inline", "svg"), ("inline", "png"), ("file", "pdf")):
                    with self.subTest(engine=engine, mode=mode, output_format=output_format):
                        options = {"input_path": path.name} if mode == "file" else {"diagram_text": source}
                        result = artifacts.export_diagram_bundle(
                            root, **options, bundle_id=f"{engine}-{mode}-{output_format}", output_format=output_format,
                            original_path=f"{engine}.svg", edited_paths=[edited_path.name],
                        )
                        self.assertTrue(result["ok"], result)
                        self.assertTrue(artifacts.check_diagram_bundle(root, **result["bundle"])["ok"])
                        results.append(result)
                        bundle = root / result["bundle"]["path"]
                        shutil.copytree(bundle.parent, receiver / bundle.parent.name)
                        # Inspect a real pin: the exact image executed, not its mutable tag.
                        image = result["producer"]["runtimes"][0]["revision"]
                        inspected = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image], capture_output=True, text=True, check=True)
                        self.assertEqual(inspected.stdout.strip(), image)
            shutil.rmtree(root)
            relocated = base / "relocated final consumer"
            receiver.rename(relocated)
            for result in results:
                name = pathlib.PurePosixPath(result["bundle"]["path"]).parent.name
                bundle = {"path": f"{name}/bundle.json", "sha256": result["bundle"]["sha256"]}
                self.assertTrue(artifacts.check_diagram_bundle(relocated, **bundle)["ok"])
                request = json.loads((relocated / name / "payload/request.json").read_bytes())
                self.assertTrue((relocated / name / request["source"]).is_file())
                self.assertIn(b"Reviewed", (relocated / name / request["edits"][0]).read_bytes())
                if name.endswith("file-svg"):
                    # Replay retained resources only, after original job retirement.
                    # As in production, the consumer is never mounted into Docker.
                    with tempfile.TemporaryDirectory(prefix="diavisuals-retained-replay-") as replay:
                        private = pathlib.Path(replay)
                        shutil.copytree(relocated / name / "payload/render", private / "bundle")
                        for entry in (private / "bundle").rglob("*"):
                            entry.chmod(0o555 if entry.is_dir() or entry.suffix == ".sh" else 0o444)
                        (private / "bundle").chmod(0o555)
                        (private / "result").mkdir(mode=0o733)
                        container = registry.renderer_container_name(relocated)
                        command = registry.build_renderer_command(
                            root=relocated, renderer={"image": request["renderer"]}, engine=request["engine"],
                            style_name=request["style"], output_format="svg", bundle=private / "bundle",
                            result=private / "result", cidfile=private / "container.cid", container_name=container,
                        )
                        rendered = registry._run_renderer(command, container_name=container, cwd=relocated)
                        self.assertEqual(rendered["returncode"], 0, rendered)
                        self.assertTrue(rendered["cleanup"]["ok"], rendered)
                        artifacts._svg_check((private / "result/artifact.svg").read_bytes())
            if REFERENCE:
                with pinned_reference() as (_, check):
                    for result in results:
                        name = pathlib.PurePosixPath(result["bundle"]["path"]).parent.name
                        self.assertTrue(check(str(relocated), "bundle", f"{name}/bundle.json", result["bundle"]["sha256"])["ok"])


@unittest.skipUnless(os.environ.get("DIAVISUALS_MCP_SMOKE") == "1", "set DIAVISUALS_MCP_SMOKE=1")
class ArtifactMCPTest(unittest.TestCase):
    def test_real_protocol_schema_binding_opt_in_and_typed_errors(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def exercise(root):
            params = StdioServerParameters(command=sys.executable, args=["-m", "diavisuals.cli", "mcp", "serve"],
                                           env={**os.environ, "MCP_CONSUMER_WORKSPACE": str(root)})
            async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                await session.initialize()
                tools = {item.name: item for item in (await session.list_tools()).tools}
                for name in ("initialize_artifact_export", "export_diagram_bundle", "check_diagram_bundle", "recover_diagram_bundle"):
                    self.assertIn(name, tools)
                    self.assertNotIn("project_root", tools[name].inputSchema.get("properties", {}))
                dry = await session.call_tool("export_diagram_bundle", {"diagram_text": "flowchart LR\n A-->B", "dry_run": True})
                self.assertFalse(dry.isError)
                self.assertFalse((root / ".diavisuals").exists())
                initialized = await session.call_tool("initialize_artifact_export", {})
                self.assertFalse(initialized.isError)
                self.assertTrue((root / artifacts.STAGING_ROOT).is_dir())
                invalid = await session.call_tool("export_diagram_bundle", {"input_path": "../escape.mmd"})
                self.assertTrue(invalid.isError)
                self.assertFalse(invalid.structuredContent["ok"])
                if os.environ.get("DIAVISUALS_DOCKER_SMOKE") == "1":
                    exported = await session.call_tool("export_diagram_bundle", {"diagram_text": "@startuml\nAlice -> Bob\n@enduml\n"})
                    self.assertFalse(exported.isError, exported)
                    payload = exported.structuredContent
                    payload = payload.get("result", payload)
                    checked = await session.call_tool("check_diagram_bundle", payload["bundle"])
                    self.assertFalse(checked.isError, checked)

        with tempfile.TemporaryDirectory(prefix="diavisuals-mcp-bundle-") as temporary:
            asyncio.run(exercise(pathlib.Path(temporary)))


if __name__ == "__main__":
    unittest.main()
