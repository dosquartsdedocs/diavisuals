from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class FactoryStartupTest(unittest.TestCase):
    def test_concurrent_environment_bound_starts_preserve_literal_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            factory = root / "factory $dollar $(touch injected-curdir) `touch injected-curdir-tick`"
            scripts = factory / "scripts"
            tools = factory / "tools"
            bin_dir = root / "bin"
            cli_dir = factory / ".venv/bin"
            scripts.mkdir(parents=True)
            tools.mkdir()
            bin_dir.mkdir()
            cli_dir.mkdir(parents=True)
            shutil.copy2(REPO_ROOT / "Makefile", factory / "Makefile")
            shutil.copy2(REPO_ROOT / "scripts/factory-launcher", scripts / "factory-launcher")
            shutil.copy2(REPO_ROOT / "scripts/mcp-stdio-launcher", scripts / "mcp-stdio-launcher")

            fake_uv = bin_dir / "uv"
            fake_uv.write_text("#!/usr/bin/env bash\nset -euo pipefail\nsleep 0.1\n", encoding="utf-8")
            fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IXUSR)

            fake_cli = cli_dir / "diavisuals"
            fake_cli.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
arguments=("$@")
project=""
if [[ "${1:-}" == "--project" ]]; then
  project="${2:?}"
  shift 2
fi
if [[ "${1:-}" == "mcp" && "${2:-}" == "serve" ]]; then
  printf '%s' "${project}" >"${STARTUP_RESULT:?}"
elif [[ -n "${CALL_LOG:-}" ]]; then
  printf '%s\\0' "${arguments[@]}" >"${CALL_LOG}"
fi
""",
                encoding="utf-8",
            )
            fake_cli.chmod(fake_cli.stat().st_mode | stat.S_IXUSR)

            tool_script = "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s' \"$1\" >\"${TOOL_RESULT:?}\"\n"
            for name in ("render-examples.sh", "render-gallery-docker.sh", "render-gallery-local.sh"):
                script = tools / name
                script.write_text(tool_script, encoding="utf-8")
                script.chmod(script.stat().st_mode | stat.S_IXUSR)

            consumers = [
                root / "consumer one $dollar $(touch injected-command) `touch injected-tick`",
                root / "consumer two $$ $(touch injected-second)",
            ]
            results = [root / "first-result", root / "second-result"]
            for consumer in consumers:
                consumer.mkdir()

            processes: list[subprocess.Popen[str]] = []
            stdouts: list[str] = []
            for consumer, result in zip(consumers, results, strict=True):
                environment = {
                    **os.environ,
                    "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                    "MCP_CONSUMER_WORKSPACE": str(consumer),
                    "STARTUP_RESULT": str(result),
                }
                processes.append(
                    subprocess.Popen(
                        ["make", "--no-print-directory", "-C", str(factory), "mcp-stdio"],
                        cwd=root,
                        env=environment,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                )

            failures: list[str] = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=20)
                stdouts.append(stdout)
                if process.returncode != 0:
                    failures.append(f"returncode={process.returncode}\nstdout={stdout}\nstderr={stderr}")

            self.assertEqual(failures, [])
            self.assertEqual(stdouts, ["", ""])
            self.assertEqual(
                [result.read_text(encoding="utf-8") for result in results],
                [str(consumer) for consumer in consumers],
            )

            input_path = "input $dollar $(touch injected-input) `touch injected-input-tick`.mmd"
            output_path = "output $dollar $(touch injected-output) `touch injected-output-tick`.svg"
            profile = "profile $dollar $(shell touch injected-profile-make) `touch injected-profile-tick`.env"
            engine = "engine $dollar $(touch injected-engine) `touch injected-engine-tick`"
            family = "family $dollar $(shell touch injected-family-make) `touch injected-family-tick`"
            output_format = "format $dollar $(touch injected-format) `touch injected-format-tick`"
            call_log = root / "render-arguments"
            make_environment = {
                **os.environ,
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "CALL_LOG": str(call_log),
            }
            rendered = subprocess.run(
                [
                    "make",
                    "--no-print-directory",
                    "-C",
                    str(factory),
                    "render-diagram",
                    f"PROJECT={consumers[0]}",
                    f"INPUT={input_path}",
                    f"OUTPUT={output_path}",
                    f"COMPAT_PROFILE={profile}",
                    f"ENGINE={engine}",
                    f"FAMILY={family}",
                    f"FORMAT={output_format}",
                ],
                cwd=root,
                env=make_environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                check=False,
            )
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            arguments = [value.decode() for value in call_log.read_bytes().split(b"\0") if value]
            self.assertEqual(arguments[arguments.index("--project") + 1], str(consumers[0]))
            self.assertEqual(arguments[arguments.index("--engine") + 1], engine)
            self.assertEqual(arguments[arguments.index("--family") + 1], family)
            self.assertEqual(arguments[arguments.index("--profile") + 1], profile)
            self.assertEqual(arguments[arguments.index("--format") + 1], output_format)
            self.assertEqual(arguments[-2:], [input_path, output_path])

            out_dir = "out $dollar $(touch injected-out-dir) `touch injected-out-dir-tick`"
            for target, variable, value in (
                ("render-examples", "OUT_DIR", out_dir),
                ("render-gallery", "COMPAT_PROFILE", profile),
                ("render-gallery-local", "COMPAT_PROFILE", profile),
            ):
                tool_result = root / f"{target}-argument"
                completed = subprocess.run(
                    [
                        "make",
                        "--no-print-directory",
                        "-C",
                        str(factory),
                        target,
                        f"{variable}={value}",
                    ],
                    cwd=root,
                    env={
                        **os.environ,
                        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                        "TOOL_RESULT": str(tool_result),
                    },
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=20,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(tool_result.read_text(encoding="utf-8"), value)

            for injected in (
                "injected-curdir",
                "injected-curdir-tick",
                "injected-command",
                "injected-tick",
                "injected-second",
                "injected-input",
                "injected-input-tick",
                "injected-output",
                "injected-output-tick",
                "injected-profile-make",
                "injected-profile-tick",
                "injected-engine",
                "injected-engine-tick",
                "injected-family-make",
                "injected-family-tick",
                "injected-format",
                "injected-format-tick",
                "injected-out-dir",
                "injected-out-dir-tick",
            ):
                self.assertFalse((factory / injected).exists())

    def test_cross_checkout_concurrent_cold_renderer_ensures_build_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            bin_dir = root / "bin"
            state = root / "docker-state"
            bin_dir.mkdir()
            state.mkdir()

            checkouts = []
            for name in ("checkout-one", "checkout-two"):
                checkout = root / name
                package = checkout / "src/diavisuals"
                shutil.copytree(REPO_ROOT / "src/diavisuals", package)
                assets = package / "assets"
                shutil.copytree(REPO_ROOT / "compat", assets / "compat")
                shutil.copytree(REPO_ROOT / "docker", assets / "docker")
                checkouts.append(checkout)

            fake_docker = bin_dir / "docker"
            fake_docker.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
state="${FAKE_DOCKER_STATE:?}"
case "${1:-} ${2:-}" in
  "image inspect")
    printf '%s\n' inspect >>"${state}/inspect-count"
    [[ -f "${state}/ready" ]] || exit 1
    printf 'sha256:%064d\n' 1
    ;;
  "build --pull")
    printf '%s\n' build >>"${state}/build-count"
    sleep 0.3
    : >"${state}/ready"
    ;;
  *)
    exit 2
    ;;
esac
""",
                encoding="utf-8",
            )
            fake_docker.chmod(fake_docker.stat().st_mode | stat.S_IXUSR)

            processes = []
            for checkout in checkouts:
                environment = {
                    **os.environ,
                    "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                    "PYTHONPATH": str(checkout / "src"),
                    "XDG_CACHE_HOME": str(checkout / "cache"),
                    "DOCKER_HOST": f"unix://{root}/fake-docker.sock",
                    "FAKE_DOCKER_STATE": str(state),
                }
                environment.pop("DIAVISUALS_DIR", None)
                processes.append(
                    subprocess.Popen(
                        [sys.executable, "-m", "diavisuals.cli", "ensure-renderer"],
                        cwd=checkout,
                        env=environment,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                )
            failures: list[str] = []
            payloads: list[dict[str, object]] = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=20)
                if process.returncode != 0:
                    failures.append(f"returncode={process.returncode}\nstdout={stdout}\nstderr={stderr}")
                else:
                    payloads.append(json.loads(stdout))

            self.assertEqual(failures, [])
            self.assertEqual((state / "build-count").read_text(encoding="utf-8"), "build\n")
            self.assertEqual((state / "inspect-count").read_text(encoding="utf-8"), "inspect\n" * 3)
            self.assertEqual(sorted(payload["built"] for payload in payloads), [False, True])
            self.assertEqual({payload["image_id"] for payload in payloads}, {"sha256:" + "0" * 63 + "1"})


if __name__ == "__main__":
    unittest.main()
