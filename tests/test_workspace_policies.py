from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
import os
import runpy
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from diavisuals import registry  # noqa: E402

CACHE = ".cache/diavisuals"
RECEIPT = ".unaltraweb/receipts/diavisuals.json"
POLICIES = [
    {"path": CACHE, "type": "directory", "role": "diagram-render-cache", "git": "ignored", "cleanup": "disposable"},
    {"path": RECEIPT, "type": "file", "role": "diagram-validation-receipt", "git": "consumer", "cleanup": "explicit"},
]
MANAGER = os.environ.get("DIAVISUALS_FACTORY_MANAGER", "")


def git(root: Path, *arguments: str) -> bytes:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update({"GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1"})
    return subprocess.run(
        ["git", "-C", str(root), *arguments], env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=20,
    ).stdout


def tree_snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    snapshot = {}
    for path in [root, *sorted(root.rglob("*"))]:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            content = os.readlink(path)
        elif stat.S_ISREG(metadata.st_mode):
            content = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            content = ""
        snapshot[path.relative_to(root).as_posix()] = (metadata.st_mode, metadata.st_mtime_ns, content)
    return snapshot


def consumer_snapshot(root: Path) -> dict[str, object]:
    return {
        "head": git(root, "rev-parse", "HEAD"),
        "index": (root / ".git/index").read_bytes(),
        "status": git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=matching"),
        "worktrees": git(root, "worktree", "list", "--porcelain"),
        "tree": tree_snapshot(root),
    }


class WorkspaceManifestTest(unittest.TestCase):
    def test_exact_policies_match_all_manifest_forms(self) -> None:
        manifests = [
            registry.yaml.safe_load((REPO_ROOT / name).read_text(encoding="utf-8"))
            for name in ("mcp-factory.yml", "mcp-factory-package.yml")
        ]
        manifests.append(registry.factory_manifest())
        with mock.patch.object(registry, "source_checkout", return_value=None):
            manifests.append(registry.factory_manifest())
        for manifest in manifests:
            with self.subTest(commands=manifest["commands"]["init"]):
                self.assertEqual(manifest["schema_version"], 1)
                self.assertEqual(manifest["workspace_rule"]["binding"], "consumer")
                self.assertEqual(manifest["workspace_rule"]["consumer_root"], ".")
                self.assertEqual(manifest["workspace_rule"]["path_policies"], POLICIES)

    def test_factory_ignore_really_covers_cache_without_tracked_content(self) -> None:
        for path in (f"{CACHE}/", f"{CACHE}/outputs/mermaid/example.svg", f"{CACHE}/nested/probe.txt"):
            matched = git(REPO_ROOT, "check-ignore", "--no-index", "--verbose", "--", path).decode()
            self.assertIn(".gitignore:1:.cache/\t", matched)
        self.assertEqual(git(REPO_ROOT, "ls-files", "--cached", "--", CACHE), b"")


class GitConsumerTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="diavisuals-path-policies-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        environment = mock.patch.dict(os.environ, {
            "HOME": str(self.root / "home"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.consumer = self.root / "consumer with spaces"
        self.consumer.mkdir()
        git(self.consumer, "init", "-q", "-b", "main")
        (self.consumer / ".gitignore").write_text(f"/{CACHE}/\n", encoding="utf-8")
        (self.consumer / "README.md").write_text("Consumer-owned content\n", encoding="utf-8")
        git(self.consumer, "add", "--", ".gitignore", "README.md")
        git(self.consumer, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "Fixture")

    def render_inline(self, output_path: str | None = None) -> dict[str, object]:
        def render(command: list[str], **kwargs: object) -> dict[str, object]:
            for index, argument in enumerate(command):
                if argument == "--mount":
                    fields = next(csv.reader([command[index + 1]]))
                    options = dict(field.split("=", 1) for field in fields if "=" in field)
                    if options.get("target") == "/output":
                        (Path(options["source"]) / "artifact.svg").write_text("<svg/>\n", encoding="utf-8")
                        return {"returncode": 0, "cleanup": {"ok": True}}
            self.fail("private output mount missing")

        with mock.patch.object(registry, "ensure_renderer_image", return_value={
            "ok": True, "image_id": "sha256:" + "1" * 64,
        }), mock.patch.object(registry, "_run_renderer", side_effect=render):
            result = registry.render_diagram_text(
                self.consumer, diagram_text="flowchart LR\n  A --> B\n", output_path=output_path,
            )
        self.assertTrue(result["ok"], result)
        return result

    def populate(self) -> None:
        self.assertTrue(registry.initialize_project(self.consumer)["ok"])
        self.render_inline()
        source = self.consumer / "assets/diagram.mmd"
        source.parent.mkdir()
        source.write_text("flowchart LR\n  A --> B\n", encoding="utf-8")
        Path(f"{source}.svg").write_text("<svg/>\n", encoding="utf-8")
        self.assertTrue(registry.project_check(self.consumer)["ok"])


class WorkspaceLifecycleTest(GitConsumerTest):
    def test_init_only_creates_cache_and_preserves_git_state(self) -> None:
        before = consumer_snapshot(self.consumer)
        for _ in range(2):
            initialized = registry.initialize_project(self.consumer)
            self.assertTrue(initialized["ok"])
            self.assertEqual(initialized["created"], [CACHE])
        after = consumer_snapshot(self.consumer)
        for key in ("head", "index", "worktrees"):
            self.assertEqual(before[key], after[key], key)
        self.assertEqual(git(self.consumer, "status", "--porcelain"), b"")
        self.assertEqual((self.consumer / ".gitignore").read_text(), f"/{CACHE}/\n")
        self.assertEqual(set(after["tree"]) - set(before["tree"]), {".cache", CACHE})

    def test_inline_publication_uses_cache_but_does_not_persist_logical_input(self) -> None:
        result = self.render_inline()
        output = result["output"]
        self.assertTrue(output.startswith(f"{CACHE}/outputs/mermaid/"))
        self.assertEqual((self.consumer / output).read_bytes(), b"<svg/>\n")
        self.assertFalse((self.consumer / CACHE / "inline").exists())
        self.assertFalse((self.consumer / result["input_source"]).exists())
        self.assertEqual(git(self.consumer, "check-ignore", "--", output).decode().strip(), output)
        self.assertEqual(git(self.consumer, "ls-files", "--cached", "--", CACHE), b"")

    def test_explicit_output_does_not_create_cache(self) -> None:
        result = self.render_inline("figures/consumer-chosen.svg")
        self.assertEqual(result["output"], "figures/consumer-chosen.svg")
        self.assertTrue((self.consumer / result["output"]).is_file())
        self.assertFalse((self.consumer / CACHE).exists())

    def test_receipt_lifecycle_and_down_preserve_consumer_paths(self) -> None:
        self.populate()
        other_receipt = self.consumer / ".unaltraweb/receipts/other-provider.json"
        other_receipt.write_text("{}\n", encoding="utf-8")
        receipt = self.consumer / RECEIPT
        self.assertEqual(json.loads(receipt.read_text())["provider"], "diavisuals")
        before = consumer_snapshot(self.consumer)
        with mock.patch.object(registry.shutil, "which", return_value="/usr/bin/docker"), mock.patch.object(
            registry, "run", side_effect=[
                {"returncode": 0, "stdout": "a" * 12 + "\n"},
                {"returncode": 0, "stdout": ""},
            ],
        ) as runner:
            self.assertTrue(registry.down_factory(self.consumer)["ok"])
        self.assertEqual(runner.call_args_list[-1].args[0], ["/usr/bin/docker", "container", "rm", "--force", "a" * 12])
        self.assertEqual(consumer_snapshot(self.consumer), before)
        # Invalidation belongs to project_check, not metadata-driven cleanup.
        (self.consumer / "assets/diagram.mmd.svg").unlink()
        self.assertFalse(registry.project_check(self.consumer)["ok"])
        self.assertFalse(receipt.exists())
        self.assertEqual(other_receipt.read_text(), "{}\n")
        self.assertTrue((self.consumer / CACHE).is_dir())


@unittest.skipUnless(MANAGER, "set DIAVISUALS_FACTORY_MANAGER to the central manager script")
class WorkspaceManagerTest(GitConsumerTest):
    def setUp(self) -> None:
        super().setUp()
        manager = Path(MANAGER)
        self.assertTrue(manager.is_absolute() and manager.is_file(), MANAGER)
        # run_path loads the real script without writing bytecode into its checkout.
        self.manager_main = runpy.run_path(str(manager))["main"]
        self.factories = self.root / "factories"
        factory = self.factories / "diavisuals"
        factory.mkdir(parents=True)
        (factory / "mcp-factory.yml").write_bytes((REPO_ROOT / "mcp-factory.yml").read_bytes())
        # Preserve an intentionally dirty consumer, including staged and untracked data.
        (self.consumer / "README.md").write_text("Unstaged consumer edit\n", encoding="utf-8")
        (self.consumer / "staged.txt").write_text("Staged consumer edit\n", encoding="utf-8")
        git(self.consumer, "add", "--", "staged.txt")
        (self.consumer / "untracked.txt").write_text("Untracked consumer file\n", encoding="utf-8")

    def check_workspace(self, expected_codes: tuple[str, ...] = ()) -> dict[str, object]:
        before = consumer_snapshot(self.consumer)
        factories_before = tree_snapshot(self.factories)
        commands = []
        real_popen = subprocess.Popen

        def read_only_git(command: list[str], *args: object, **kwargs: object):
            commands.append(command)
            self.assertFalse(kwargs.get("shell"), command)
            self.assertEqual(command[:3], ["git", "-C", str(self.consumer)], command)
            verb = command[4] if command[3] == "--literal-pathspecs" else command[3]
            self.assertIn(verb, {"rev-parse", "check-ignore", "ls-files"}, command)
            return real_popen(command, *args, **kwargs)

        output = io.StringIO()
        with mock.patch.object(subprocess, "Popen", side_effect=read_only_git), mock.patch.object(
            os, "system", side_effect=AssertionError("workspace-check must not run shell/provider commands"),
        ), contextlib.redirect_stdout(output):
            code = self.manager_main([
                "workspace-check", "--dir", str(self.factories), "--factory", "diavisuals",
                "--workspace", str(self.consumer), "--json",
            ])
        self.assertEqual(consumer_snapshot(self.consumer), before)
        self.assertEqual(tree_snapshot(self.factories), factories_before)
        self.assertTrue(commands, "the manager must perform real Git inspection")
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 1 if expected_codes else 0, payload)
        self.assertTrue(payload["inspection_ok"], payload)
        self.assertEqual(payload["errors"], [])
        self.assertEqual(sorted(finding["code"] for finding in payload["findings"]), sorted(expected_codes), payload)
        self.assertEqual(payload["summary"]["declared_path_policy_count"], len(POLICIES))
        self.assertEqual(payload["summary"]["path_count"], len(POLICIES))
        for observation in payload["resolved_paths"]:
            self.assertEqual(observation["binding"], "consumer")
            self.assertEqual(observation["resolved_root"], str(self.consumer))
        return payload

    def test_cold_consumer_is_not_initialized(self) -> None:
        payload = self.check_workspace()
        self.assertTrue(all(not observation["exists"] for observation in payload["resolved_paths"]))
        self.assertEqual(payload["summary"]["consumer_policy_count"], 1)

    def test_populated_consumer_accepts_each_receipt_git_choice(self) -> None:
        self.populate()
        for state in ("untracked", "versioned", "ignored"):
            with self.subTest(state=state):
                if state == "versioned":
                    git(self.consumer, "add", "--", RECEIPT)
                elif state == "ignored":
                    git(self.consumer, "rm", "--cached", "--", RECEIPT)
                    (self.consumer / ".gitignore").write_text(f"/{CACHE}/\n/{RECEIPT}\n", encoding="utf-8")
                payload = self.check_workspace()
                observations = {item["declared_path"]: item for item in payload["resolved_paths"]}
                self.assertEqual(observations[CACHE]["git_state"], "ignored")
                self.assertEqual(observations[RECEIPT]["git_state"], state)

    def test_missing_cache_ignore_is_reported_without_repair(self) -> None:
        (self.consumer / ".gitignore").write_text("", encoding="utf-8")
        self.check_workspace(("path-not-ignored",))

    def test_forced_tracked_cache_is_reported_without_untracking(self) -> None:
        self.populate()
        git(self.consumer, "add", "--force", "--", CACHE)
        payload = self.check_workspace(("ignored-path-versioned",))
        self.assertTrue(payload["resolved_paths"][0]["tracked_paths"])

    def test_wrong_types_are_reported_without_replacement(self) -> None:
        for policy in POLICIES:
            with self.subTest(path=policy["path"]):
                path = self.consumer / policy["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                if policy["type"] == "directory":
                    path.write_text("Consumer file\n", encoding="utf-8")
                else:
                    path.mkdir()
                self.check_workspace(("path-type-mismatch",))
                path.unlink() if path.is_file() else path.rmdir()

    def test_symlinked_paths_are_reported_without_following(self) -> None:
        external = self.root / "external"
        external.mkdir()
        (external / "sentinel.txt").write_text("Preserve\n", encoding="utf-8")
        before = tree_snapshot(external)
        for policy in POLICIES:
            with self.subTest(path=policy["path"]):
                path = self.consumer / policy["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to(external, target_is_directory=True)
                self.check_workspace(("path-symlink-component",))
                self.assertEqual(tree_snapshot(external), before)
                path.unlink()


if __name__ == "__main__":
    unittest.main()
