from __future__ import annotations

import pathlib
from typing import Any

from .registry import (
    DEFAULT_COMPATIBILITY,
    DEFAULT_FAMILY,
    DEFAULT_RELEASE,
    check_styles as core_check_styles,
    compatibility_status as core_compatibility_status,
    factory_manifest as core_factory_manifest,
    json_dumps,
    release_status as core_release_status,
    render_diagram as core_render_diagram,
    render_diagram_text as core_render_diagram_text,
    style_audit as core_style_audit,
    repo_dir,
    style_inventory as core_style_inventory,
    submodule_plan as core_submodule_plan,
    update_factory as core_update_factory,
)


def run_server(project: pathlib.Path) -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - optional runtime dependency
        raise SystemExit(
            "The MCP server requires the optional dependency. Install with: "
            "python3 -m pip install 'diavisuals[mcp]'"
        ) from exc

    consumer_root = project.expanduser().resolve()
    mcp = FastMCP("diavisuals")

    @mcp.resource("diavisuals://agent-guide")
    def agent_guide() -> str:
        """Repository guidance for visual-style work."""
        path = repo_dir() / "AGENTS.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    @mcp.resource("diavisuals://styles")
    def styles() -> str:
        """Style family inventory."""
        return json_dumps(core_style_inventory())

    @mcp.resource("diavisuals://compatibility")
    def compatibility() -> str:
        """Compatibility profile inventory."""
        return json_dumps(core_compatibility_status())

    @mcp.resource("diavisuals://style-audit")
    def default_style_audit() -> str:
        """Default style-family audit."""
        return json_dumps(core_style_audit())

    @mcp.resource("diavisuals://examples")
    def examples() -> str:
        """Rendered/source example inventory grouped by style family."""
        inventory = core_style_inventory()
        return json_dumps(
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

    @mcp.resource("diavisuals://factory-manifest")
    def manifest() -> str:
        """Factory discovery manifest for ContExt-style launchers."""
        return json_dumps(core_factory_manifest())

    @mcp.tool()
    def style_inventory() -> dict[str, Any]:
        """List style families, overrides, examples, and tokens."""
        return core_style_inventory()

    @mcp.tool()
    def style_audit(profile: str = DEFAULT_COMPATIBILITY, family: str = DEFAULT_FAMILY) -> dict[str, Any]:
        """Validate tokens, examples, compatibility, and rendered gallery for a style family."""
        return core_style_audit(profile=profile, family=family)

    @mcp.tool()
    def check_styles(profile: str = DEFAULT_COMPATIBILITY, family: str = DEFAULT_FAMILY) -> dict[str, Any]:
        """Validate a style family and compatibility profile."""
        return core_check_styles(profile=profile, family=family)

    @mcp.tool()
    def compatibility_status(profile: str = DEFAULT_COMPATIBILITY) -> dict[str, Any]:
        """Inspect compatibility profiles."""
        return core_compatibility_status(profile)

    @mcp.tool()
    def release_status(release: str = DEFAULT_RELEASE) -> dict[str, Any]:
        """Inspect Git release tag status."""
        return core_release_status(release)

    @mcp.tool()
    def submodule_plan(
        path: str = "docs/slides/resources/diavisuals",
        release: str = DEFAULT_RELEASE,
        remote: str = "git@github.com:dosquartsdedocs/diavisuals.git",
    ) -> dict[str, Any]:
        """Return commands for pinning diavisuals as a submodule in a consumer repo."""
        return core_submodule_plan(str(consumer_root), path=path, release=release, remote=remote)

    @mcp.tool()
    def render_diagram(
        input_path: str,
        output_path: str,
        engine: str = "auto",
        family: str = DEFAULT_FAMILY,
        style: str = "",
        profile: str = DEFAULT_COMPATIBILITY,
        output_format: str = "",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Render one styled Mermaid or PlantUML diagram through the diavisuals Docker renderer."""
        return core_render_diagram(
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

    @mcp.tool()
    def render_diagram_text(
        diagram_text: str,
        engine: str = "auto",
        family: str = DEFAULT_FAMILY,
        style: str = "",
        profile: str = DEFAULT_COMPATIBILITY,
        output_format: str = "",
        output_path: str = "",
        include_data: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Render Mermaid or PlantUML source text and return the generated image artifact."""
        return core_render_diagram_text(
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

    @mcp.tool()
    def update(dry_run: bool = False) -> dict[str, Any]:
        """Update the diavisuals factory checkout."""
        return core_update_factory(dry_run=dry_run)

    @mcp.tool()
    def factory_manifest() -> dict[str, Any]:
        """Return the factory discovery manifest."""
        return core_factory_manifest()

    mcp.run()
