from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
from typing import Any

from . import __version__
from .registry import (
    DEFAULT_COMPATIBILITY,
    DEFAULT_FAMILY,
    DEFAULT_RELEASE,
    check_styles,
    client_config,
    compatibility_status,
    factory_manifest,
    install_check,
    json_dumps,
    release_status,
    style_inventory,
    submodule_plan,
    update_factory,
    vscode_client_config,
)


def print_payload(payload: Any) -> None:
    print(json_dumps(payload))


def cmd_style_inventory(args: argparse.Namespace) -> int:
    payload = style_inventory()
    print_payload(payload)
    return 0 if payload.get("ok") else 1


def cmd_compatibility_status(args: argparse.Namespace) -> int:
    payload = compatibility_status(args.profile)
    print_payload(payload)
    return 0 if payload.get("ok") else 1


def cmd_check(args: argparse.Namespace) -> int:
    payload = check_styles(profile=args.profile, family=args.family)
    print_payload(payload)
    return 0 if payload.get("ok") else 1


def cmd_release_status(args: argparse.Namespace) -> int:
    payload = release_status(args.release)
    print_payload(payload)
    return 0 if payload.get("ok") else 1


def cmd_submodule_plan(args: argparse.Namespace) -> int:
    payload = submodule_plan(
        args.project_root,
        path=args.path,
        release=args.release,
        remote=args.remote,
    )
    print_payload(payload)
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    payload = update_factory(dry_run=args.dry_run)
    print_payload(payload)
    return 0 if payload.get("ok") else 1


def cmd_factory_manifest(args: argparse.Namespace) -> int:
    print_payload(factory_manifest())
    return 0


def cmd_install_check(args: argparse.Namespace) -> int:
    payload = install_check(args.command)
    print_payload(payload)
    return 0 if payload.get("ok") else 1


def cmd_client_config(args: argparse.Namespace) -> int:
    if args.format == "vscode-workspace":
        payload = vscode_client_config(project=args.workspace_placeholder, command=args.command)
    else:
        payload = client_config(project=args.workspace_placeholder, command=args.command)
    print_payload(payload)
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    if args.mcp_command == "serve":
        from .mcp_server import run_server

        run_server(pathlib.Path(args.project))
        return 0
    if args.mcp_command == "client-config":
        return cmd_client_config(args)
    raise SystemExit(f"unknown mcp command: {args.mcp_command}")


def cmd_install_codex_mcp(args: argparse.Namespace) -> int:
    codex_bin = shutil.which(args.codex_bin) or (args.codex_bin if args.dry_run else None)
    if not codex_bin:
        payload = {"ok": False, "message": f"Codex binary not found: {args.codex_bin}"}
        print_payload(payload)
        return 1

    server_command = [
        args.command,
        "--project",
        args.codex_project or ".",
        "mcp",
        "serve",
    ]
    remove_cmd = [codex_bin, "mcp", "remove", args.server_name]
    add_cmd = [codex_bin, "mcp", "add", args.server_name, "--", *server_command]
    payload: dict[str, Any] = {
        "ok": True,
        "server_name": args.server_name,
        "remove": remove_cmd,
        "add": add_cmd,
        "dry_run": args.dry_run,
    }
    if args.dry_run:
        print_payload(payload)
        return 0

    remove_result = subprocess.run(remove_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    add_result = subprocess.run(add_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    payload["remove_result"] = {
        "returncode": remove_result.returncode,
        "stdout": remove_result.stdout,
        "stderr": remove_result.stderr,
    }
    payload["add_result"] = {
        "returncode": add_result.returncode,
        "stdout": add_result.stdout,
        "stderr": add_result.stderr,
    }
    payload["ok"] = add_result.returncode == 0
    print_payload(payload)
    return 0 if payload["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="diavisuals")
    parser.add_argument("--project", default=".", help="Consumer repository root for MCP launchers")
    parser.add_argument("--version", action="version", version=f"diavisuals {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    styles_parser = subcommands.add_parser("style-inventory", help="List style families, overrides, examples, and tokens")
    styles_parser.set_defaults(func=cmd_style_inventory)

    compat_parser = subcommands.add_parser("compatibility-status", help="Inspect compatibility profiles")
    compat_parser.add_argument("--profile", default=DEFAULT_COMPATIBILITY)
    compat_parser.set_defaults(func=cmd_compatibility_status)

    check_parser = subcommands.add_parser("check", help="Validate the default style family and compatibility profile")
    check_parser.add_argument("--profile", default=DEFAULT_COMPATIBILITY)
    check_parser.add_argument("--family", default=DEFAULT_FAMILY)
    check_parser.set_defaults(func=cmd_check)

    release_parser = subcommands.add_parser("release-status", help="Inspect Git release tag status")
    release_parser.add_argument("--release", default=DEFAULT_RELEASE)
    release_parser.set_defaults(func=cmd_release_status)

    submodule_parser = subcommands.add_parser("submodule-plan", help="Print commands for pinning diavisuals as a submodule")
    submodule_parser.add_argument("--project-root", default=".")
    submodule_parser.add_argument("--path", default="docs/slides/resources/diavisuals")
    submodule_parser.add_argument("--release", default=DEFAULT_RELEASE)
    submodule_parser.add_argument("--remote", default="git@github.com:dosquartsdedocs/diavisuals.git")
    submodule_parser.set_defaults(func=cmd_submodule_plan)

    update_parser = subcommands.add_parser("update", help="Update the diavisuals factory checkout")
    update_parser.add_argument("--dry-run", action="store_true")
    update_parser.set_defaults(func=cmd_update)

    manifest_parser = subcommands.add_parser("factory-manifest", help="Print the ContExt/discovery manifest")
    manifest_parser.set_defaults(func=cmd_factory_manifest)

    install_check_parser = subcommands.add_parser("install-check", help="Check whether the CLI is installed as an executable tool")
    install_check_parser.add_argument("--command", default="diavisuals")
    install_check_parser.set_defaults(func=cmd_install_check)

    codex_parser = subcommands.add_parser("install-codex-mcp", help="Register this MCP server with Codex")
    codex_parser.add_argument("--server-name", default="diavisuals")
    codex_parser.add_argument("--codex-bin", default="codex")
    codex_parser.add_argument("--command", default="diavisuals")
    codex_parser.add_argument("--project-root", dest="codex_project", help="Pin the server to a repository instead of Codex's current workspace")
    codex_parser.add_argument("--dry-run", action="store_true")
    codex_parser.set_defaults(func=cmd_install_codex_mcp)

    mcp_parser = subcommands.add_parser("mcp", help="MCP server and client snippets")
    mcp_subcommands = mcp_parser.add_subparsers(dest="mcp_command", required=True)
    serve_parser = mcp_subcommands.add_parser("serve", help="Run the stdio MCP server")
    serve_parser.set_defaults(func=cmd_mcp)
    client_parser = mcp_subcommands.add_parser("client-config", help="Print an MCP client configuration snippet")
    client_parser.add_argument("--format", choices=["generic", "vscode-workspace"], default="generic")
    client_parser.add_argument("--workspace-placeholder", default="${workspaceFolder}")
    client_parser.add_argument("--command", default="diavisuals")
    client_parser.set_defaults(func=cmd_mcp)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

