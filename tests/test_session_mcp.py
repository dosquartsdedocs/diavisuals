from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pathlib
import sys
import tempfile
import unittest

if os.environ.get("DIAVISUALS_INSTALLED") != "1":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from diavisuals import __version__  # noqa: E402
from diavisuals.session import owner_state  # noqa: E402


def tool_payload(result):
    value = result.structuredContent
    return value if "ok" in value else value["result"]


@contextlib.asynccontextmanager
async def connect(python, root, *, environment=None, source=False):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {key: value for key, value in os.environ.items() if key not in {
        "PYTHONPATH", "DIAVISUALS_DIR", "DIAVISUALS_RUNTIME_IMAGE", "DIAVISUALS_RUNTIME_EXPECTED_ID",
    }}
    if source:
        env["PYTHONPATH"] = str(pathlib.Path(__file__).resolve().parents[1] / "src")
    env.update(MCP_CONSUMER_WORKSPACE=str(root))
    env.update(environment or {})
    params = StdioServerParameters(command=str(pathlib.Path(python).parent / "diavisuals"), args=["mcp", "serve"], env=env, cwd=str(root))
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


async def call(session, name, args=None):
    result = await session.call_tool(name, args or {})
    if result.isError:
        raise AssertionError(result)
    return tool_payload(result)


@unittest.skipUnless(os.environ.get("DIAVISUALS_MCP_SMOKE") == "1", "set DIAVISUALS_MCP_SMOKE=1")
class SessionMCPTest(unittest.TestCase):
    def test_live_pair_same_version_reconnect_drain_and_independent_consumer(self):
        async def exercise(base):
            roots = [base / "first", base / "second"]
            for root in roots:
                root.mkdir()
                (root / "private.txt").write_text("do not read")
            source = os.environ.get("DIAVISUALS_INSTALLED") != "1"
            async with connect(sys.executable, roots[1], source=source) as other:
                other_before = await call(other, "server_identity")
                async with connect(sys.executable, roots[0], source=source) as first:
                    before = await call(first, "server_identity")
                    resource = await first.read_resource("diavisuals://server/identity")
                    resource_value = json.loads(resource.contents[0].text)
                    self.assertEqual(before["instance"], resource_value["instance"])
                    self.assertEqual(before["loaded"], resource_value["loaded"])
                    self.assertEqual(before["loaded"]["version"], __version__)
                    self.assertEqual(before["binding"]["path"], str(roots[0]))
                    self.assertNotEqual(before["instance"]["instance_id"], other_before["instance"]["instance_id"])
                    self.assertEqual(owner_state(before["instance"]), "alive")
                    wrong = await first.call_tool("release_session", {"expected_instance_id": other_before["instance"]["instance_id"]})
                    self.assertTrue(wrong.isError)
                    drained = await call(first, "release_session", {"expected_instance_id": before["instance"]["instance_id"]})
                    self.assertEqual(drained["state"], "draining")
                    self.assertFalse(drained["process_release_verified"])
                    rejected = await first.call_tool("render_diagram_text", {"diagram_text": "flowchart LR\n A-->B", "dry_run": True})
                    self.assertTrue(rejected.isError)
                self.assertEqual(owner_state(before["instance"]), "dead")
                self.assertEqual((await call(other, "server_identity"))["instance"], other_before["instance"])
                async with connect(sys.executable, roots[0], source=source) as reconnected:
                    after = await call(reconnected, "server_identity")
                    self.assertNotEqual(after["instance"]["instance_id"], before["instance"]["instance_id"])
                    self.assertEqual(after["loaded"], before["loaded"])
                self.assertEqual(owner_state(after["instance"]), "dead")
                self.assertEqual((await call(other, "server_identity"))["instance"], other_before["instance"])
            self.assertEqual(owner_state(other_before["instance"]), "dead")
            for root in roots:
                self.assertEqual({path.name for path in root.iterdir()}, {"private.txt"})

        with tempfile.TemporaryDirectory(prefix="diavisuals-identity-mcp-") as temporary:
            asyncio.run(exercise(pathlib.Path(temporary)))

    def test_absent_selection_is_live_identity_not_a_new_cli_or_preparation(self):
        async def exercise(root):
            async with connect(sys.executable, root, source=os.environ.get("DIAVISUALS_INSTALLED") != "1",
                               environment={"DIAVISUALS_RUNTIME_IMAGE": "sha256:" + "0" * 64}) as server:
                identity = await call(server, "server_identity")
                self.assertTrue(identity["ok"])
                self.assertFalse(identity["pinned_runtime_ready"])
                self.assertFalse(identity["renderer"]["ok"])
                self.assertEqual(identity["renderer"]["selection"]["expected_image_id"], "sha256:" + "0" * 64)
                result = await server.call_tool("render_diagram_text", {"diagram_text": "flowchart LR\n A-->B"})
                self.assertTrue(result.isError)
                self.assertEqual((await call(server, "server_identity"))["instance"], identity["instance"])
            self.assertEqual(list(root.iterdir()), [])

        with tempfile.TemporaryDirectory(prefix="diavisuals-identity-missing-") as temporary:
            asyncio.run(exercise(pathlib.Path(temporary)))


if __name__ == "__main__":
    unittest.main()
