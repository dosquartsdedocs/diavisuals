from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
from typing import Any


DEFAULT_RELEASE = "v0.1.0"
DEFAULT_COMPATIBILITY = "mermaid-11.4.2-plantuml-1.2026.1"
DEFAULT_FAMILY = "benizar"
DEFAULT_REMOTE = "git@github.com:dosquartsdedocs/diavisuals.git"


def repo_dir() -> pathlib.Path:
    env = os.environ.get("DIAVISUALS_DIR", "").strip()
    if env:
        return pathlib.Path(env).expanduser().resolve()

    module_path = pathlib.Path(__file__).resolve()
    checkout = module_path.parents[2]
    if (checkout / "styles").is_dir() and (checkout / "compat").is_dir():
        return checkout

    packaged = module_path.parent / "assets"
    if packaged.is_dir():
        return packaged

    return checkout


def rel(path: pathlib.Path, root: pathlib.Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def run(command: list[str], cwd: pathlib.Path | None = None, timeout: int = 120) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=str(cwd or repo_dir()),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def git_head(path: pathlib.Path | None = None) -> str | None:
    root = path or repo_dir()
    result = run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], cwd=root)
    if result["returncode"] == 0:
        return str(result["stdout"]).strip()
    return None


def git_tag(path: pathlib.Path | None = None) -> str | None:
    root = path or repo_dir()
    result = run(["git", "-C", str(root), "describe", "--tags", "--exact-match"], cwd=root)
    if result["returncode"] == 0:
        return str(result["stdout"]).strip()
    return None


def parse_env(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def style_family_item(root: pathlib.Path, family: str) -> dict[str, Any]:
    mermaid_name = f"{family}-mermaid"
    plantuml_name = f"{family}-plantuml"
    mermaid_base = root / "styles" / "mermaid" / f"{mermaid_name}.json"
    mermaid_overrides = root / "styles" / "mermaid" / mermaid_name
    plantuml_base = root / "styles" / "plantuml" / f"{plantuml_name}.puml"
    plantuml_overrides = root / "styles" / "plantuml" / plantuml_name
    examples = root / "examples" / family
    tokens = root / "tokens" / f"{family}.yml"
    return {
        "family": family,
        "ok": mermaid_base.is_file() and plantuml_base.is_file(),
        "tokens": {"path": rel(tokens, root), "exists": tokens.is_file()},
        "mermaid": {
            "name": mermaid_name,
            "base": rel(mermaid_base, root),
            "base_exists": mermaid_base.is_file(),
            "overrides": [rel(path, root) for path in sorted(mermaid_overrides.glob("*.mmd"))] if mermaid_overrides.is_dir() else [],
            "examples": [rel(path, root) for path in sorted((examples / "mermaid").glob("*.mmd"))] if (examples / "mermaid").is_dir() else [],
        },
        "plantuml": {
            "name": plantuml_name,
            "base": rel(plantuml_base, root),
            "base_exists": plantuml_base.is_file(),
            "overrides": [rel(path, root) for path in sorted(plantuml_overrides.glob("*.puml"))] if plantuml_overrides.is_dir() else [],
            "examples": [rel(path, root) for path in sorted((examples / "plantuml").glob("*.puml"))] if (examples / "plantuml").is_dir() else [],
        },
    }


def style_inventory() -> dict[str, Any]:
    root = repo_dir()
    families: list[str] = []
    for style in sorted((root / "styles" / "mermaid").glob("*-mermaid.json")):
        family = style.name.removesuffix("-mermaid.json")
        if (root / "styles" / "plantuml" / f"{family}-plantuml.puml").is_file():
            families.append(family)
    items = [style_family_item(root, family) for family in families]
    return {
        "ok": all(item["ok"] for item in items),
        "repo": str(root),
        "git_head": git_head(root),
        "git_tag": git_tag(root),
        "families": items,
        "count": len(items),
    }


def compatibility_status(profile: str = DEFAULT_COMPATIBILITY) -> dict[str, Any]:
    root = repo_dir()
    compat_root = root / "compat"
    requested = profile.removesuffix(".env")
    profile_file = compat_root / f"{requested}.env"
    profiles = []
    for path in sorted(compat_root.glob("*.env")):
        values = parse_env(path)
        profiles.append(
            {
                "name": path.stem,
                "path": rel(path, root),
                "mermaid": values.get("MERMAID_CLI_VERSION"),
                "plantuml": values.get("PLANTUML_VERSION"),
                "family": values.get("DIAVISUALS_FAMILY"),
                "mermaid_types": values.get("MERMAID_TYPES"),
                "plantuml_types": values.get("PLANTUML_TYPES"),
            }
        )
    return {
        "ok": profile_file.is_file(),
        "requested": requested,
        "requested_path": rel(profile_file, root),
        "values": parse_env(profile_file),
        "profiles": profiles,
    }


def check_styles(profile: str = DEFAULT_COMPATIBILITY, family: str = DEFAULT_FAMILY) -> dict[str, Any]:
    inventory = style_inventory()
    compat = compatibility_status(profile)
    family_item = next((item for item in inventory["families"] if item["family"] == family), None)
    issues: list[str] = []
    if family_item is None:
        issues.append(f"missing style family: {family}")
    elif not family_item["ok"]:
        issues.append(f"incomplete style family: {family}")
    if not compat["ok"]:
        issues.append(f"missing compatibility profile: {profile}")
    return {
        "ok": not issues,
        "issues": issues,
        "family": family_item,
        "compatibility": compat,
    }


def release_status(release: str = DEFAULT_RELEASE) -> dict[str, Any]:
    root = repo_dir()
    tag_result = run(["git", "-C", str(root), "rev-parse", "--verify", f"refs/tags/{release}"], cwd=root)
    current_tag = git_tag(root)
    return {
        "ok": tag_result["returncode"] == 0,
        "requested": release,
        "requested_sha": str(tag_result["stdout"]).strip() if tag_result["returncode"] == 0 else None,
        "current_head": git_head(root),
        "current_tag": current_tag,
        "current_matches_release": current_tag == release,
    }


def submodule_plan(
    project_root: str = ".",
    *,
    path: str = "docs/slides/resources/diavisuals",
    release: str = DEFAULT_RELEASE,
    remote: str = DEFAULT_REMOTE,
) -> dict[str, Any]:
    return {
        "ok": True,
        "project_root": project_root,
        "path": path,
        "release": release,
        "remote": remote,
        "commands": [
            ["git", "submodule", "add", remote, path],
            ["git", "-C", path, "checkout", release],
            ["git", "add", ".gitmodules", path],
        ],
    }


def update_factory(dry_run: bool = False) -> dict[str, Any]:
    root = repo_dir()
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "command": ["git", "pull", "--ff-only"],
            "repo": str(root),
        }
    status = run(["git", "-C", str(root), "status", "--porcelain"], cwd=root)
    if status["returncode"] != 0 or status["stdout"].strip():
        return {
            "ok": False,
            "message": "Refusing to update a dirty or unreadable diavisuals checkout.",
            "status": status,
        }
    result = run(["git", "-C", str(root), "pull", "--ff-only"], cwd=root, timeout=300)
    return {
        "ok": result["returncode"] == 0,
        "result": result,
        "git_head": git_head(root),
    }


def client_config(project: str = "${workspaceFolder}", command: str = "diavisuals") -> dict[str, Any]:
    return {
        "mcpServers": {
            "diavisuals": {
                "command": command,
                "args": ["--project", project, "mcp", "serve"],
            }
        }
    }


def vscode_client_config(project: str = "${workspaceFolder}", command: str = "diavisuals") -> dict[str, Any]:
    return {
        "servers": {
            "diavisuals": {
                "type": "stdio",
                "command": command,
                "args": ["--project", project, "mcp", "serve"],
            }
        }
    }


def factory_manifest() -> dict[str, Any]:
    root = repo_dir()
    return {
        "ok": True,
        "name": "diavisuals",
        "kind": "codex-mcp-factory",
        "version": "0.1.0",
        "factory": str(root),
        "git_head": git_head(root),
        "workspace_rule": {
            "consumer_root": "shared-style-submodule",
            "allowed_external_writes": [".gitmodules"],
        },
        "commands": {
            "check": ["diavisuals", "check"],
            "update": ["diavisuals", "update"],
            "install_codex_mcp": ["diavisuals", "install-codex-mcp"],
            "client_config": ["diavisuals", "mcp", "client-config"],
            "serve": ["diavisuals", "mcp", "serve"],
            "manifest": ["diavisuals", "factory-manifest"],
            "styles": ["diavisuals", "style-inventory"],
        },
        "mcp": {
            "server_name": "diavisuals",
            "transport": "stdio",
            "resources": [
                "diavisuals://agent-guide",
                "diavisuals://styles",
                "diavisuals://compatibility",
                "diavisuals://examples",
                "diavisuals://factory-manifest",
            ],
            "tools": [
                "style_inventory",
                "check_styles",
                "compatibility_status",
                "release_status",
                "submodule_plan",
                "update",
                "factory_manifest",
            ],
        },
        "release": {
            "default": DEFAULT_RELEASE,
            "compatibility": DEFAULT_COMPATIBILITY,
            "family": DEFAULT_FAMILY,
        },
    }


def install_check(command: str = "diavisuals") -> dict[str, Any]:
    resolved = shutil.which(command)
    result = None
    mcp_dependency = None
    if resolved:
        result = run([resolved, "--version"], cwd=repo_dir(), timeout=30)
        mcp_dependency = check_mcp_dependency(resolved)
    return {
        "ok": bool(
            resolved
            and result
            and result["returncode"] == 0
            and mcp_dependency
            and mcp_dependency["returncode"] == 0
        ),
        "command": command,
        "resolved": resolved,
        "version_result": result,
        "mcp_dependency": mcp_dependency,
        "install_hints": [
            "uv tool install --editable .",
            "uv tool install --editable '.[mcp]'",
        ],
    }


def entrypoint_python(command_path: str) -> str | None:
    try:
        first_line = pathlib.Path(command_path).read_text(encoding="utf-8", errors="ignore").splitlines()[0]
    except (IndexError, OSError, UnicodeDecodeError):
        return None
    if not first_line.startswith("#!"):
        return None
    executable = first_line[2:].strip().split()[0]
    if pathlib.Path(executable).exists():
        return executable
    return None


def check_mcp_dependency(command_path: str) -> dict[str, Any]:
    python = entrypoint_python(command_path)
    if not python:
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": "Could not determine the Python interpreter used by the CLI entrypoint.",
            "command": [command_path],
        }
    return run(
        [python, "-c", "from mcp.server.fastmcp import FastMCP; print('ok')"],
        cwd=repo_dir(),
        timeout=30,
    )


def json_dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
