"""Same-daemon acceptance using real Docker, without alias wrappers or retagging."""
from __future__ import annotations

import asyncio
import contextlib
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

if os.environ.get("DIAVISUALS_INSTALLED") != "1":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from diavisuals import __version__, registry  # noqa: E402
from tests.test_artifacts import mount  # noqa: E402


@unittest.skipUnless(os.environ.get("DIAVISUALS_DOCKER_SMOKE") == "1", "set DIAVISUALS_DOCKER_SMOKE=1")
class RuntimeSelectionDockerTest(unittest.TestCase):
    def test_two_selections_cli_mcp_cache_and_bundles(self):
        if os.environ.get("DIAVISUALS_INSTALLED") == "1":
            self.assertIsNone(registry.source_checkout())

        def docker(*args):
            return subprocess.check_output(["docker", *args], text=True, timeout=60).strip()

        profile = registry.renderer_profile()
        profile_path = registry.repo_dir() / "compat" / f"{profile['profile']}.env"
        profile_before = profile_path.read_bytes()
        before = json.loads(docker("image", "inspect", profile["image"]))[0]
        base_image = before["Id"]
        # An unstarted, mount-free container supplies a config-only test fixture.
        # No engine build, pull, active tag mutation or Docker command wrapper.
        name = "diavisuals-selection-fixture-" + uuid.uuid4().hex
        container = docker("create", "--name", name, "--network", "none", "--read-only",
                           "--label", "io.context.mcp-role=selection-fixture", base_image, "/bin/true")
        fixture = None
        try:
            fixture = docker("commit", "--change", f"LABEL io.diavisuals.selection-fixture={name}", container)
            self.assertNotEqual(base_image, fixture)
            fixture_info = json.loads(docker("image", "inspect", fixture))[0]
            self.assertEqual(fixture_info["RootFS"]["Layers"][:len(before["RootFS"]["Layers"])], before["RootFS"]["Layers"])
            self.assertFalse(fixture_info["RepoTags"])
            with tempfile.TemporaryDirectory(prefix="diavisuals-native-selection-") as temporary:
                root = pathlib.Path(temporary) / "consumer à"
                root.mkdir()
                env = {key: value for key, value in os.environ.items() if key not in {
                    "DIAVISUALS_RUNTIME_IMAGE", "DIAVISUALS_RUNTIME_EXPECTED_ID", "DIAVISUALS_DIR", "PYTHONPATH",
                }}
                if os.environ.get("DIAVISUALS_INSTALLED") != "1":
                    env["PYTHONPATH"] = str(pathlib.Path(__file__).resolve().parents[1] / "src")
                records = {"package_version": __version__, "python": sys.version, "base_image": base_image,
                           "fixture_image": fixture, "profile_sha256": hashlib.sha256(profile_before).hexdigest(),
                           "source_checkout": str(registry.source_checkout()) if registry.source_checkout() else None, "calls": []}

                def cli(image, *args, expected=None, ok=True):
                    command = [sys.executable, "-m", "diavisuals.cli", "--project", str(root), "--runtime-image", image]
                    if expected:
                        command.extend(["--runtime-expected-id", expected])
                    result = subprocess.run([*command, *args], cwd=root, env=env, capture_output=True, text=True, timeout=120)
                    self.assertEqual(result.returncode, 0 if ok else 1, result.stderr or result.stdout)
                    payload = json.loads(result.stdout or result.stderr)
                    self.assertEqual(payload["ok"], ok, payload)
                    records["calls"].append({"arguments": [*command, *args], "result": payload})
                    return payload

                for image in (base_image, fixture):
                    for command in ("ensure-renderer", "build-renderer", "renderer-status"):
                        status = cli(image, command)
                        self.assertFalse(status["built"])
                        self.assertEqual(status["runtime"]["image_id"], image)
                    cli(image, "mcp-smoke")

                for missing, expected in (("sha256:" + "0" * 64, None), (profile["image"], fixture)):
                    for command in ("ensure-renderer", "build-renderer"):
                        rejected = cli(missing, command, expected=expected, ok=False)
                        self.assertFalse(rejected["built"])
                    cli(missing, "render-diagram-text", "--text", "flowchart LR\n A-->B", expected=expected, ok=False)
                    cli(missing, "export-diagram-bundle", "--text", "flowchart LR\n A-->B", expected=expected, ok=False)
                self.assertFalse((root / ".cache").exists())
                self.assertFalse((root / ".diavisuals").exists())

                sources = {"mermaid": ("mmd", "flowchart LR\n A[Native selection]-->B[Bundle]\n"),
                           "plantuml": ("puml", "@startuml\nAlice -> Bob : Native selection\n@enduml\n")}
                (root / "assets").mkdir()
                for engine, (suffix, source) in sources.items():
                    (root / "assets" / f"{engine}.{suffix}").write_text(source)
                    outputs = []
                    for image in (base_image, fixture, base_image):
                        result = cli(image, "render-diagram-text", "--text", source, "--no-data")
                        outputs.append(result["output"])
                        self.assertEqual(result["runtime"]["image_id"], image)
                        command = result["command"]
                        self.assertEqual(command[command.index("bash") - 1], image)
                        self.assertIn("--pull=never", command)
                        self.assertEqual(command[command.index("--network") + 1], "none")
                        for target in ("/diavisuals", "/output"):
                            staged = mount(command, target)
                            self.assertFalse(registry.path_within(staged, root))
                            self.assertFalse(registry.path_within(staged, pathlib.Path(__file__).resolve().parents[1]))
                    self.assertNotEqual(outputs[0], outputs[1])
                    self.assertEqual(outputs[0], outputs[2])
                    cli(base_image, "render-diagram", f"assets/{engine}.{suffix}", f"assets/{engine}.{suffix}.svg")
                cli(base_image, "project-check")
                cli(fixture, "project-check", ok=False)
                self.assertFalse((root / registry.PROJECT_RECEIPT_PATH).exists())

                async def exercise_mcp():
                    from mcp import ClientSession, StdioServerParameters
                    from mcp.client.stdio import stdio_client

                    sessions = []
                    async with contextlib.AsyncExitStack() as stack:
                        bad_parameters = StdioServerParameters(command=sys.executable, args=["-m", "diavisuals.cli", "mcp", "serve"],
                                                               cwd=str(root), env={**env, "MCP_CONSUMER_WORKSPACE": str(root),
                                                                                   "DIAVISUALS_RUNTIME_IMAGE": profile["image"],
                                                                                   "DIAVISUALS_RUNTIME_EXPECTED_ID": fixture})
                        bad_read, bad_write = await stack.enter_async_context(stdio_client(bad_parameters))
                        bad_session = await stack.enter_async_context(ClientSession(bad_read, bad_write))
                        await bad_session.initialize()
                        for tool, arguments in (
                            ("renderer_status", {}),
                            ("render_diagram_text", {"diagram_text": sources["mermaid"][1]}),
                            ("export_diagram_bundle", {"diagram_text": sources["mermaid"][1]}),
                        ):
                            rejected = await bad_session.call_tool(tool, arguments)
                            self.assertTrue(rejected.isError, rejected)
                            self.assertFalse(rejected.structuredContent["ok"])
                        self.assertFalse((root / ".diavisuals").exists())
                        for image in (base_image, fixture):
                            parameters = StdioServerParameters(command=sys.executable, args=["-m", "diavisuals.cli", "mcp", "serve"],
                                                               cwd=str(root), env={**env, "MCP_CONSUMER_WORKSPACE": str(root),
                                                                                   "DIAVISUALS_RUNTIME_IMAGE": image})
                            read, write = await stack.enter_async_context(stdio_client(parameters))
                            session = await stack.enter_async_context(ClientSession(read, write))
                            await session.initialize()
                            sessions.append((image, session))
                        for index, (image, session) in enumerate(sessions):
                            async def call(tool, arguments):
                                result = await session.call_tool(tool, arguments)
                                self.assertFalse(result.isError, result)
                                payload = result.structuredContent
                                if "ok" not in payload:
                                    payload = payload.get("result", payload)
                                records["calls"].append({"mcp_image": image, "tool": tool, "result": payload})
                                return payload

                            status = await call("renderer_status", {})
                            self.assertEqual(status["image_id"], image)
                            for engine, (suffix, source) in sources.items():
                                rendered = await call("render_diagram_text", {"diagram_text": source, "include_data": False})
                                self.assertEqual(rendered["runtime"]["image_id"], image)
                                exported = await call("export_diagram_bundle", {"input_path": f"assets/{engine}.{suffix}", "bundle_id": f"selected-{index}-{engine}"})
                                self.assertEqual(exported["producer"]["runtimes"][0]["revision"], image)
                                await call("check_diagram_bundle", exported["bundle"])
                                bundle = root / exported["bundle"]["path"]
                                retained = bundle.parent / "payload/resources" / profile_path.name
                                self.assertEqual(retained.read_bytes(), profile_before)
                                selection = json.loads((bundle.parent / "payload/runtime-selection.json").read_bytes())
                                self.assertEqual(selection["expected_image_id"], image)
                                # Historical bundle integrity is independent of today's selected runtime.
                                other = fixture if image == base_image else base_image
                                cli(other, "check-diagram-bundle", exported["bundle"]["path"], "--sha256", exported["bundle"]["sha256"])

                asyncio.run(exercise_mcp())
                cli(base_image, "project-check")
                receipt = root / registry.PROJECT_RECEIPT_PATH
                records["receipt"] = {"path": registry.PROJECT_RECEIPT_PATH.as_posix(),
                                      "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}
                self.assertEqual(profile_path.read_bytes(), profile_before)
                self.assertEqual(json.loads(docker("image", "inspect", profile["image"]))[0]["Id"], base_image)
                self.assertEqual(json.loads(docker("image", "inspect", base_image))[0]["RepoTags"], before["RepoTags"])
                evidence = os.environ.get("DIAVISUALS_SELECTION_EVIDENCE")
                if evidence:
                    destination = pathlib.Path(evidence) / uuid.uuid4().hex
                    shutil.copytree(root, destination / "consumer")
                    (destination / "evidence.json").write_text(json.dumps(records, indent=2, sort_keys=True) + "\n")
                    print(f"Native selection evidence: {destination}")
        finally:
            docker("container", "rm", container)
            if fixture is not None:
                # Exact untagged test image only; never force/remove a shared alias.
                docker("image", "rm", fixture)


if __name__ == "__main__":
    unittest.main()
