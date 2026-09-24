from __future__ import annotations

import pathlib
from typing import Any

from . import artifacts
from . import registry as core


def _resolve_consumer_root(project: pathlib.Path) -> pathlib.Path:
    try:
        root = project.expanduser().resolve(strict=True)
    except OSError as exc:
        raise FileNotFoundError(f"consumer project root not found: {project}") from exc
    if not root.is_dir():
        raise NotADirectoryError(f"consumer project root is not a directory: {project}")
    return root


def run_server(project: pathlib.Path) -> None:
    consumer_root = _resolve_consumer_root(project)
    # Preserve the selected spelling for the stricter v1 no-link ancestor check.
    artifact_root = project.expanduser().absolute()
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import CallToolResult, TextContent
    except ImportError as exc:  # pragma: no cover - optional runtime dependency
        raise SystemExit(
            "The MCP server requires the optional dependency. Install with: "
            "python3 -m pip install 'diavisuals[mcp]'"
        ) from exc

    mcp = FastMCP("diavisuals")

    def require_ok(payload: dict[str, Any]) -> Any:
        if payload.get("ok") is not True:
            return CallToolResult(
                content=[TextContent(type="text", text=core.json_dumps(payload))],
                structuredContent=payload,
                isError=True,
            )
        return payload

    def tool_result(callback: Any) -> Any:
        try:
            payload = callback()
        except Exception as exc:
            payload = {"ok": False, "error": str(exc)}
        return require_ok(payload)

    @mcp.resource("diavisuals://agent-guide")
    def agent_guide() -> str:
        """Repository guidance for visual-style work."""
        path = core.repo_dir() / "AGENTS.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    @mcp.resource("diavisuals://styles")
    def styles() -> str:
        """Style family inventory."""
        return core.json_dumps(core.style_inventory())

    @mcp.resource("diavisuals://compatibility")
    def compatibility() -> str:
        """Compatibility profile inventory."""
        return core.json_dumps(core.compatibility_status())

    @mcp.resource("diavisuals://style-audit")
    def default_style_audit() -> str:
        """Default style-family audit."""
        return core.json_dumps(core.style_audit())

    @mcp.resource("diavisuals://examples")
    def examples() -> str:
        """Rendered/source example inventory grouped by style family."""
        inventory = core.style_inventory()
        return core.json_dumps(
            {
                "ok": inventory.get("ok", False),
                "families": [
                    {
                        "family": item["family"],
                        "mermaid": item["mermaid"]["examples"],
                        "plantuml": item["plantuml"]["examples"],
                    }
                    for item in inventory.get("families", [])
                ],
            }
        )

    @mcp.resource("diavisuals://project/check")
    def project_check_resource() -> str:
        """Project-wide diagram output and unaltraweb receipt check."""
        return core.json_dumps(core.project_check(consumer_root))

    @mcp.resource("diavisuals://factory-manifest")
    def manifest() -> str:
        """Factory discovery manifest for gContExt-style launchers."""
        return core.json_dumps(core.factory_manifest())

    @mcp.tool()
    def style_inventory() -> dict[str, Any]:
        """List style families, overrides, examples, and tokens."""
        return tool_result(core.style_inventory)

    @mcp.tool()
    def style_audit(profile: str = core.DEFAULT_COMPATIBILITY, family: str = core.DEFAULT_FAMILY) -> dict[str, Any]:
        """Validate tokens, examples, compatibility, and rendered gallery for a style family."""
        return tool_result(lambda: core.style_audit(profile=profile, family=family))

    @mcp.tool()
    def check_styles(profile: str = core.DEFAULT_COMPATIBILITY, family: str = core.DEFAULT_FAMILY) -> dict[str, Any]:
        """Validate a style family and compatibility profile."""
        return tool_result(lambda: core.check_styles(profile=profile, family=family))

    @mcp.tool()
    def compatibility_status(profile: str = core.DEFAULT_COMPATIBILITY) -> dict[str, Any]:
        """Inspect compatibility profiles."""
        return tool_result(lambda: core.compatibility_status(profile))

    @mcp.tool()
    def release_status(release: str = core.DEFAULT_RELEASE) -> dict[str, Any]:
        """Inspect Git release tag status."""
        return tool_result(lambda: core.release_status(release))

    @mcp.tool()
    def submodule_plan(
        path: str = "docs/slides/resources/diavisuals",
        release: str = core.DEFAULT_RELEASE,
        remote: str = "git@github.com:dosquartsdedocs/diavisuals.git",
    ) -> dict[str, Any]:
        """Return commands for pinning diavisuals as a submodule in a consumer repo."""
        return tool_result(
            lambda: core.submodule_plan(str(consumer_root), path=path, release=release, remote=remote)
        )

    @mcp.tool()
    def project_check() -> dict[str, Any]:
        """Check all supported project diagram outputs and publish the provider receipt."""
        return tool_result(lambda: core.project_check(consumer_root))

    @mcp.tool()
    def render_diagram(
        input_path: str,
        output_path: str,
        engine: str = "auto",
        family: str = core.DEFAULT_FAMILY,
        style: str = "",
        profile: str = core.DEFAULT_COMPATIBILITY,
        output_format: str = "",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Render one styled Mermaid or PlantUML diagram through the diavisuals Docker renderer."""
        return tool_result(
            lambda: core.render_diagram(
                consumer_root,
                input_path=input_path,
                output_path=output_path,
                engine=engine,
                family=family,
                style=style or None,
                profile=profile,
                output_format=output_format,
                dry_run=dry_run,
            )
        )

    @mcp.tool()
    def render_diagram_text(
        diagram_text: str,
        engine: str = "auto",
        family: str = core.DEFAULT_FAMILY,
        style: str = "",
        profile: str = core.DEFAULT_COMPATIBILITY,
        output_format: str = "",
        output_path: str = "",
        include_data: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Render Mermaid or PlantUML source text and return the generated image artifact."""
        return tool_result(
            lambda: core.render_diagram_text(
                consumer_root,
                diagram_text=diagram_text,
                output_path=output_path or None,
                engine=engine,
                family=family,
                style=style or None,
                profile=profile,
                output_format=output_format,
                include_data=include_data,
                dry_run=dry_run,
            )
        )

    @mcp.tool()
    def initialize_artifact_export() -> dict[str, Any]:
        """Opt in to retained diagram bundles and prepare confined ignored recovery staging."""
        return tool_result(lambda: artifacts.initialize_artifact_export(artifact_root))

    @mcp.tool()
    def export_diagram_bundle(
        input_path: str | None = None,
        diagram_text: str | None = None,
        bundle_id: str = "",
        engine: str = "auto",
        family: str = core.DEFAULT_FAMILY,
        style: str = "",
        profile: str = core.DEFAULT_COMPATIBILITY,
        output_format: str = "svg",
        original_path: str | None = None,
        edited_paths: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Render one file OR inline source and retain a sealed v1 bundle, optionally with selected original/edited SVGs."""
        return tool_result(lambda: artifacts.export_diagram_bundle(
            artifact_root, input_path=input_path, diagram_text=diagram_text, bundle_id=bundle_id,
            engine=engine, family=family, style=style, profile=profile, output_format=output_format,
            original_path=original_path, edited_paths=edited_paths, dry_run=dry_run,
        ))

    @mcp.tool()
    def check_diagram_bundle(path: str, sha256: str) -> dict[str, Any]:
        """Verify a diagram bundle's sender hash, complete tree and retained source/resource/SVG references."""
        return tool_result(lambda: artifacts.check_diagram_bundle(artifact_root, path=path, sha256=sha256))

    @mcp.tool()
    def recover_diagram_bundle(path: str, sha256: str, bundle_id: str) -> dict[str, Any]:
        """Publish an exact sealed staging job to a new bundle name after a publication failure."""
        return tool_result(lambda: artifacts.recover_diagram_bundle(artifact_root, path=path, sha256=sha256, bundle_id=bundle_id))

    @mcp.tool()
    def update(dry_run: bool = False) -> dict[str, Any]:
        """Update the diavisuals factory checkout."""
        return tool_result(lambda: core.update_factory(dry_run=dry_run))

    @mcp.tool()
    def factory_manifest() -> dict[str, Any]:
        """Return the factory discovery manifest."""
        return tool_result(core.factory_manifest)

    mcp.run()
