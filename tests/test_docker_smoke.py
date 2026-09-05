from __future__ import annotations

import csv
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from diavisuals.registry import (  # noqa: E402
    RENDERER_CONTAINER_LABEL,
    RENDERER_WORKSPACE_LABEL,
    down_factory,
    ensure_renderer_image,
    render_diagram,
    renderer_workspace_id,
)


def docker_mount_source(command: list[str], target: str) -> pathlib.Path:
    for index, value in enumerate(command):
        if value != "--mount":
            continue
        fields = next(csv.reader([command[index + 1]]))
        options = dict(field.split("=", 1) for field in fields if "=" in field)
        if options.get("target") == target:
            return pathlib.Path(options["source"])
    raise AssertionError(f"mount target not found: {target}")


def docker_available() -> bool:
    if os.environ.get("DIAVISUALS_DOCKER_SMOKE") != "1" or shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=30,
    )
    return result.returncode == 0


@unittest.skipUnless(docker_available(), "set DIAVISUALS_DOCKER_SMOKE=1 with a reachable Docker daemon")
class DockerSmokeTest(unittest.TestCase):
    def test_down_removes_only_the_selected_workspace(self) -> None:
        image = ensure_renderer_image()
        self.assertTrue(image["ok"], image)
        with tempfile.TemporaryDirectory() as temporary:
            base = pathlib.Path(temporary)
            projects = [base / "first", base / "second"]
            for project in projects:
                project.mkdir()
            names = [f"diavisuals-cleanup-{os.getpid()}-{index}" for index in range(2)]
            try:
                for name, project in zip(names, projects, strict=True):
                    created = subprocess.run(
                        [
                            "docker",
                            "create",
                            "--name",
                            name,
                            "--label",
                            RENDERER_CONTAINER_LABEL,
                            "--label",
                            f"{RENDERER_WORKSPACE_LABEL}={renderer_workspace_id(project)}",
                            "--entrypoint",
                            "/bin/sh",
                            image["image_id"],
                            "-c",
                            "exit 0",
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(created.returncode, 0, created.stderr)

                removed = down_factory(projects[0])
                self.assertTrue(removed["ok"], removed)
                self.assertEqual(len(removed["containers"]), 1)
                first = subprocess.run(
                    ["docker", "container", "inspect", names[0]],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                second = subprocess.run(
                    ["docker", "container", "inspect", names[1]],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                self.assertNotEqual(first.returncode, 0)
                self.assertEqual(second.returncode, 0)
            finally:
                subprocess.run(
                    ["docker", "container", "rm", "--force", *names],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )

    def test_real_renders_with_csv_sensitive_tmpdir(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = pathlib.Path(temporary)
            project = base / "project"
            tmpdir = base / 'tmp,with"quote'
            project.mkdir()
            tmpdir.mkdir()
            (project / "diagram.mmd").write_text("flowchart TD\n  A --> B\n", encoding="utf-8")
            (project / "diagram.puml").write_text("@startuml\nAlice -> Bob : Smoke\n@enduml\n", encoding="utf-8")

            previous_tempdir = tempfile.tempdir
            with mock.patch.dict(os.environ, {"TMPDIR": str(tmpdir)}):
                tempfile.tempdir = None
                try:
                    self.assertEqual(pathlib.Path(tempfile.gettempdir()), tmpdir)
                    mermaid = render_diagram(project, input_path="diagram.mmd", output_path="diagram.svg")
                    plantuml = render_diagram(project, input_path="diagram.puml", output_path="diagram.pdf")
                finally:
                    tempfile.tempdir = previous_tempdir

            self.assertTrue(mermaid["ok"], mermaid)
            self.assertTrue(plantuml["ok"], plantuml)
            self.assertEqual(mermaid["command"][mermaid["command"].index("bash") - 1], mermaid["image"]["image_id"])
            self.assertEqual(docker_mount_source(mermaid["command"], "/diavisuals").parent.parent, tmpdir)
            self.assertEqual(docker_mount_source(plantuml["command"], "/output").parent.parent, tmpdir)
            self.assertIn(b"<svg", (project / "diagram.svg").read_bytes()[:4096])
            self.assertTrue((project / "diagram.pdf").read_bytes().startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
