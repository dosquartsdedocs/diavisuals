"""Factory smoke is one useful workflow, not historical/cohort acceptance."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

if os.environ.get("DIAVISUALS_INSTALLED") != "1":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from diavisuals import cli, registry  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLI = pathlib.Path(sys.executable).parent / "diavisuals"
OLD_IMAGE = "sha256:5a6887b372a0e1c386a7b54981d11ae1910215baeb6a12dfd0706b3e85ef0846"


class SmokePlanTest(unittest.TestCase):
    def test_native_render_status_is_not_confused_with_sdk_result_wrapper(self):
        for value, expected in (
            ({"ok": True, "result": {"returncode": 0}}, True),
            ({"result": {"ok": True}}, True),
            ({"ok": False, "result": {"ok": True}}, False),
        ):
            with self.subTest(value=value):
                result = SimpleNamespace(is_error=False, structured_content=value, content=[])
                self.assertEqual(cli._tool_result_ok(result), expected)
                result.is_error = True
                self.assertFalse(cli._tool_result_ok(result))

    def test_default_smoke_is_real_and_make_does_not_prepare_or_run_regressions(self):
        self.assertFalse(cli.build_parser().parse_args(["mcp-smoke"]).protocol_only)
        self.assertTrue(cli.build_parser().parse_args(["mcp-smoke", "--protocol-only"]).protocol_only)
        plan = subprocess.run(["make", "--no-print-directory", "-n", "mcp-smoke"], cwd=ROOT, text=True, capture_output=True, check=True).stdout
        self.assertIn('".venv/bin/diavisuals" mcp-smoke', plan)
        self.assertNotIn("uv sync", plan)
        self.assertNotIn("unittest", plan)
        self.assertNotIn("ensure-renderer", plan)
        self.assertNotIn("--protocol-only", plan)

    def test_unprepared_checkout_fails_with_preparation_instruction(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = pathlib.Path(temporary) / "absent-cli"
            result = subprocess.run(["make", "--no-print-directory", "mcp-smoke", f"CLI={missing}", "UV=/must-not-run"],
                                    cwd=ROOT, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("make mcp-build", result.stderr)


class ProbeEnvironment:
    def environment(self, base):
        consumer = base / "consumer"
        consumer.mkdir()
        (consumer / "authored.txt").write_text("preserve original consumer")
        guard = base / "guard"
        guard.mkdir()
        shutil.copyfile(ROOT / "tests/d0_sitecustomize.py", guard / "sitecustomize.py")
        configuration = {
            "engine_checkout": str(ROOT), "package_root": str(pathlib.Path(registry.__file__).parent),
            "consumer": str(consumer), "allow_consumer": str(base / "never-allow-consumer"),
            "log": str(base / "audit.jsonl"), "strict_rm": True,
            "development": os.environ.get("DIAVISUALS_INSTALLED") != "1",
            "forbidden_image_refs": ["diavisuals/render:v0.3.0", OLD_IMAGE],
        }
        config = base / "guard.json"
        config.write_text(json.dumps(configuration))
        env = {key: value for key, value in os.environ.items() if key not in {
            "PYTHONPATH", "DIAVISUALS_DIR", "DIAVISUALS_RUNTIME_IMAGE", "DIAVISUALS_RUNTIME_EXPECTED_ID",
        }}
        env.update(PYTHONPATH=str(guard), DIAVISUALS_TEST_GUARD=str(config), MCP_CONSUMER_WORKSPACE=str(consumer),
                   DIAVISUALS_JOB_STORAGE_GRANT=str(consumer / "must-not-be-opened.json"),
                   MCP_JOB_STORAGE_BINDING=str(consumer / "must-not-be-used.json"))
        return consumer, env

    def check_probe(self, base, consumer, result, *, ok, protocol_only):
        self.assertEqual(result.returncode, 0 if ok else 1, result.stderr + result.stdout)
        value = json.loads(result.stdout)
        self.assertEqual(value["ok"], ok, value)
        self.assertEqual(value["protocol_only"], protocol_only)
        self.assertEqual(value["runtime_verified"], ok and not protocol_only)
        self.assertEqual(set(value["renders"]), {"mermaid", "plantuml"})
        self.assertEqual((consumer / "authored.txt").read_text(), "preserve original consumer")
        self.assertEqual({path.name for path in consumer.iterdir()}, {"authored.txt"})
        events = [json.loads(line) for line in (base / "audit.jsonl").read_text().splitlines()]
        self.assertFalse([event for event in events if event["event"].startswith("denied-")], events)
        return value, [event["value"] for event in events if event["event"] == "subprocess" and pathlib.Path(event["value"][0]).name == "docker"]


@unittest.skipUnless(os.environ.get("DIAVISUALS_MCP_SMOKE") == "1", "set DIAVISUALS_MCP_SMOKE=1")
class SmokeProtocolTest(ProbeEnvironment, unittest.TestCase):
    def test_protocol_diagnostic_is_partial_without_docker_or_caller_job(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = pathlib.Path(temporary)
            consumer, env = self.environment(base)
            env["PATH"] = str(base / "no-executables")
            result = subprocess.run([str(CLI), "--project", str(base / "nonexistent-project"), "mcp-smoke", "--protocol-only"],
                                    cwd=base, env=env, text=True, capture_output=True, timeout=45)
            _, commands = self.check_probe(base, consumer, result, ok=True, protocol_only=True)
            self.assertEqual(commands, [])

    def test_real_smoke_refuses_absent_selected_runtime_without_preparation(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = pathlib.Path(temporary)
            consumer, env = self.environment(base)
            env["PATH"] = str(base / "no-executables")
            env["DIAVISUALS_RUNTIME_IMAGE"] = "sha256:" + "0" * 64
            result = subprocess.run([str(CLI), "mcp-smoke"], cwd=base, env=env, text=True, capture_output=True, timeout=45)
            value, commands = self.check_probe(base, consumer, result, ok=False, protocol_only=False)
            self.assertTrue(value["errors"])
            self.assertTrue(commands)
            self.assertTrue(all(command[1:3] == ["image", "inspect"] for command in commands))


@unittest.skipUnless(os.environ.get("DIAVISUALS_DOCKER_SMOKE") == "1", "set DIAVISUALS_DOCKER_SMOKE=1")
class SmokeDockerTest(ProbeEnvironment, unittest.TestCase):
    def test_real_smoke_refuses_missing_or_mismatched_runtime_without_fallback(self):
        current = registry.renderer_status(runtime=registry.RuntimeSelection())
        self.assertTrue(current["ok"], current)
        missing = "sha256:" + "0" * 64
        for selection in (missing, current["renderer"]["image"]):
            with self.subTest(selection=selection), tempfile.TemporaryDirectory() as temporary:
                base = pathlib.Path(temporary)
                consumer, env = self.environment(base)
                env.update(DIAVISUALS_RUNTIME_IMAGE=selection, DIAVISUALS_RUNTIME_EXPECTED_ID=missing)
                result = subprocess.run([str(CLI), "mcp-smoke"], cwd=base, env=env, text=True, capture_output=True, timeout=45)
                value, commands = self.check_probe(base, consumer, result, ok=False, protocol_only=False)
                self.assertEqual(set(value["errors"]), {"mermaid", "plantuml"})
                self.assertFalse(any(command[1] == "run" for command in commands), commands)
                self.assertTrue(commands)
                self.assertTrue(all(command[-1] == selection for command in commands if command[1:3] == ["image", "inspect"]), commands)

    def test_cli_and_make_share_one_real_offline_current_image_workflow(self):
        current = registry.renderer_status(runtime=registry.RuntimeSelection())
        self.assertTrue(current["ok"], current)
        for via_make in (False, True):
            with self.subTest(via_make=via_make), tempfile.TemporaryDirectory() as temporary:
                base = pathlib.Path(temporary)
                consumer, env = self.environment(base)
                env.update(DIAVISUALS_RUNTIME_IMAGE=current["image_id"], DIAVISUALS_RUNTIME_EXPECTED_ID=current["image_id"])
                command = ["make", "--no-print-directory", "mcp-smoke", f"CLI={CLI}", "UV=/must-not-run"] if via_make else [str(CLI), "mcp-smoke"]
                result = subprocess.run(command, cwd=ROOT if via_make else base, env=env, text=True, capture_output=True, timeout=120)
                value, commands = self.check_probe(base, consumer, result, ok=True, protocol_only=False)
                self.assertTrue(all(value["renders"].values()))
                renders = [command for command in commands if command[1] == "run"]
                self.assertEqual(len(renders), 2, commands)
                for command in renders:
                    self.assertIn(current["image_id"], command)
                    self.assertIn("--pull=never", command)
                    self.assertEqual(command[command.index("--network") + 1], "none")
                self.assertFalse(any("volume" in command for command in commands), commands)
