#!/usr/bin/env python3
"""Zero-exception audit gate plus an offline, no-mount installed-image proof."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import tempfile

from diavisuals import registry as core
from diavisuals.session import IMAGE_LABEL, JOB_LABEL, owner_labels


def check_report(report, exit_code):
    counts = {name: 0 for name in ("info", "low", "moderate", "high", "critical", "total")}
    if (exit_code != 0 or not isinstance(report, dict) or report.get("auditReportVersion") != 2 or "error" in report
            or report.get("vulnerabilities") != {} or report.get("metadata", {}).get("vulnerabilities") != counts):
        raise ValueError("current renderer requires a complete, zero-finding npm audit; no exceptions apply")


def inspect_image(image, lock_path):
    if not core.DOCKER_IMAGE_ID_RE.fullmatch(image):
        raise ValueError("provide the prepared immutable image ID")
    profile = core.renderer_profile()
    if not profile["ok"]:
        raise ValueError("current profile is invalid")
    names = ["@mermaid-js/mermaid-cli", "mermaid", "puppeteer", "dompurify", "katex"]
    script = """
const fs = require('node:fs');
const crypto = require('node:crypto');
const child = require('node:child_process');
const sha = path => crypto.createHash('sha256').update(fs.readFileSync(path)).digest('hex');
const names = ['@mermaid-js/mermaid-cli','mermaid','puppeteer','dompurify','katex'];
const versions = Object.fromEntries(names.map(name => [name, JSON.parse(fs.readFileSync('/opt/mermaid/node_modules/'+name+'/package.json')).version]));
const browserRaw = fs.readFileSync('/opt/mermaid/browser-build.json');
if(browserRaw.length > 1048576) throw new Error('browser build metadata exceeds bound');
const browserBuild = JSON.parse(browserRaw);
if(browserBuild.profile!=='diavisuals-mermaid-browser-build-v1' || browserBuild.compiler.version!=='0.28.2') throw new Error('unknown browser build profile');
if(browserBuild.outputs.length > 512 || browserBuild.inputs.length > 4096) throw new Error('browser build inventory exceeds bound');
for(const item of [...browserBuild.inputs,...browserBuild.outputs]) {
  if(!item.path.startsWith('node_modules/') || item.path.includes('..') || sha('/opt/mermaid/'+item.path)!==item.sha256) throw new Error('browser build source/output changed');
}
for(const name of ['mermaid','dompurify','katex']) if(browserBuild.versions[name]!==versions[name]) throw new Error('embedded browser dependency differs');
if(browserBuild.lock_sha256!==sha('/opt/mermaid/package-lock.json')) throw new Error('browser build lock differs');
const chrome = child.execFileSync(process.env.PUPPETEER_EXECUTABLE_PATH, ['--version'], {encoding:'utf8',timeout:15000,maxBuffer:65536}).trim();
const java = child.spawnSync('java', ['-version'], {encoding:'utf8',timeout:15000,maxBuffer:65536});
if (java.status !== 0) throw new Error('Java version probe failed');
console.log(JSON.stringify({versions,node:process.version,chrome,java:java.stderr.trim(),lock_sha256:sha('/opt/mermaid/package-lock.json'),plantuml_sha256:sha('/opt/plantuml/plantuml.jar'),browser_build:{sha256:sha('/opt/mermaid/browser-build.json'),versions:browserBuild.versions,compiler:browserBuild.compiler,inputs:browserBuild.inputs.length,outputs:browserBuild.outputs.length}}));
"""
    name = core.renderer_container_name(core.repo_dir())
    labels = {**owner_labels(), "io.context.mcp-factory": "diavisuals", JOB_LABEL: name, IMAGE_LABEL: image,
              core.RENDERER_WORKSPACE_LABEL: core.renderer_workspace_id(core.repo_dir())}
    with tempfile.TemporaryDirectory(prefix="diavisuals-image-proof-") as directory:
        command = ["docker", "run", "--rm", "--pull=never", "--name", name, "--cidfile", str(pathlib.Path(directory) / "container.cid"),
                   "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true", "--user", "65532:65532",
                   "--memory", "512m", "--memory-swap", "512m", "--cpus", "1", "--pids-limit", "64", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777",
                   *[part for key, value in labels.items() for part in ("--label", f"{key}={value}")], "--entrypoint", "node", image, "-e", script]
        result = core._run_renderer(command, container_name=name, cwd=core.repo_dir(), timeout=45)
    if result["returncode"] or not result["cleanup"]["ok"]:
        raise ValueError("offline image proof failed: " + result["stderr"][:1024])
    proof = json.loads(result["stdout"])
    raw = lock_path.read_bytes()
    lock = json.loads(raw)
    expected = {name: lock["packages"]["node_modules/" + name]["version"] for name in names}
    if proof["lock_sha256"] != hashlib.sha256(raw).hexdigest() or proof["versions"] != expected:
        raise ValueError("prepared image differs from the audited dependency lock")
    if proof["plantuml_sha256"] != profile["values"]["PLANTUML_SHA256"]:
        raise ValueError("prepared PlantUML differs from the selected profile")
    if expected["@mermaid-js/mermaid-cli"] != profile["values"]["MERMAID_CLI_VERSION"] or expected["puppeteer"] != profile["values"]["PUPPETEER_VERSION"]:
        raise ValueError("audited dependency versions differ from the current profile")
    return {**proof, "image_id": image, "profile": profile["profile"], "profile_sha256": profile["profile_sha256"],
            "network": "none", "host_mounts": [], "worker_absence_verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=pathlib.Path)
    parser.add_argument("--lock", type=pathlib.Path, default=core.repo_dir() / "docker/current/package-lock.json")
    parser.add_argument("--audit-exit-code", type=int, required=True)
    parser.add_argument("--image-id", required=True)
    args = parser.parse_args()
    try:
        if args.report.stat().st_size > 1024 * 1024 or args.lock.stat().st_size > 1024 * 1024:
            raise ValueError("audit/lock exceeds the bounded profile")
        raw = args.report.read_bytes()
        check_report(json.loads(raw), args.audit_exit_code)
        proof = inspect_image(args.image_id, args.lock)
        print(json.dumps({"ok": True, "accepted_advisories": [], "audit_sha256": hashlib.sha256(raw).hexdigest(), **proof}, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
