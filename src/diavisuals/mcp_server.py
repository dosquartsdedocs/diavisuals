from __future__ import annotations

import pathlib
from typing import Any

from . import registry as core


def run_server(project: pathlib.Path) -> None:
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import CallToolResult, TextContent
    except ImportError as exc:  # pragma: no cover - optional runtime dependency
        raise SystemExit(
            "The MCP server requires the optional dependency. Install with: "
            "python3 -m pip install 'diavisuals[mcp]'"
        ) from exc

    consumer_root = project.expanduser().resolve()
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
        """Factory discovery manifest for ContExt-style launchers."""
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
    def update(dry_run: bool = False) -> dict[str, Any]:
        """Update the diavisuals factory checkout."""
        return tool_result(lambda: core.update_factory(dry_run=dry_run))

    @mcp.tool()
    def factory_manifest() -> dict[str, Any]:
        """Return the factory discovery manifest."""
        return tool_result(core.factory_manifest)

    mcp.run()
