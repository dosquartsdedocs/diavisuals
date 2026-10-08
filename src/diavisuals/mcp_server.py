from __future__ import annotations

import os
import pathlib
from contextlib import asynccontextmanager
from typing import Any

from . import artifacts
from . import job_storage as storage
from . import registry as core
from .session import CURRENT_SESSION, ServerSession


def _resolve_consumer_root(project: pathlib.Path) -> pathlib.Path:
    try:
        root = project.expanduser().resolve(strict=True)
    except OSError as exc:
        raise FileNotFoundError(f"consumer project root not found: {project}") from exc
    if not root.is_dir():
        raise NotADirectoryError(f"consumer project root is not a directory: {project}")
    return root


def run_server(project: pathlib.Path, *, runtime: core.RuntimeSelection | None = None) -> None:
    consumer_root = _resolve_consumer_root(project)
    # Bind the selection once, just like the consumer root; tools cannot silently
    # fall back to a changed process environment or the profile's shared alias.
    runtime = runtime if runtime is not None else core.runtime_selection()
    # Preserve the selected spelling for the stricter v1 no-link ancestor check.
    artifact_root = project.expanduser().absolute()
    instance = ServerSession(consumer_root, runtime)
    store = storage.selected(consumer_root) if os.environ.get(storage.CONTEXT_ENV) else None
    interest = store.client_attach() if store else None
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import CallToolResult, TextContent
    except ImportError as exc:  # pragma: no cover - optional runtime dependency
        raise SystemExit(
            "The MCP server requires the optional dependency. Install with: "
            "python3 -m pip install 'diavisuals[mcp]'"
        ) from exc

    @asynccontextmanager
    async def lifespan(_server):
        try:
            yield {}
        finally:
            if store and interest and not interest.get("released"):
                store.client_detach(interest["lease_id"])
            instance.close()

    mcp = FastMCP("diavisuals", lifespan=lifespan)

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
            if hasattr(exc, "code"):
                payload["code"] = exc.code
        return require_ok(payload)

    async def operation(name: str, callback: Any) -> Any:
        import anyio

        def execute():
            if store and name in {"render_diagram", "render_diagram_text", "export_diagram_bundle", "initialize_artifact_export", "recover_diagram_bundle", "project_check"}:
                raise storage.StorageError("storage-binding-mismatch", "W1 is selected: use render_job_diagram and job_storage; receiver delivery is a manager operation")
            with instance.operation(name):
                return callback()

        try:
            # Keep identity/release responsive while an owned job runs. Do not
            # abandon a live worker thread on stdio EOF: let its bounded render
            # and exact-container cleanup finish before process exit.
            payload = await anyio.to_thread.run_sync(execute)
        except Exception as exc:
            payload = {"ok": False, "error": str(exc)}
            if hasattr(exc, "code"):
                payload["code"] = exc.code
        return require_ok(payload)

    async def live_identity() -> dict[str, Any]:
        import anyio

        value = await anyio.to_thread.run_sync(instance.identity)
        if store:
            value["job_storage"] = {"contract": storage.CONTRACT, "profile": "diavisuals-private-directory-v1",
                                    "registry_id": store.grant["registry_id"], "job_id": store.grant["job_id"], "lease_id": interest["lease_id"],
                                    "origin_consumer": str(consumer_root), "job_root": "/work", "scratch_root": "/work/scratch"}
        return value

    @mcp.resource("diavisuals://server/identity")
    async def identity_resource() -> str:
        """Bounded identity of this live serving process; no consumer reads or preparation."""
        return core.json_dumps(await live_identity())

    @mcp.tool()
    async def server_identity() -> dict[str, Any]:
        """Observe this serving instance, loaded code/disk drift, binding, workers and lifecycle."""
        return await live_identity()

    @mcp.tool()
    def release_session(expected_instance_id: str) -> dict[str, Any]:
        """Drain this idle stdio instance; refuse busy/unknown state. Caller then closes/waits."""
        def release():
            result = instance.release(expected_instance_id)
            if result["ok"] and store and interest and not interest.get("released"):
                result["job_storage"] = store.client_detach(interest["lease_id"])
                interest["released"] = True
            return result
        return tool_result(release)

    @mcp.resource("diavisuals://job-storage")
    def storage_contract() -> str:
        """Exact installed W1 declaration; private-manager selection is explicit."""
        provider, sha256 = storage.declaration()
        return core.json_dumps({"provider": provider, "sha256": sha256, "profile": "diavisuals-private-directory-v1"})

    @mcp.tool()
    async def job_storage(request: dict[str, Any]) -> dict[str, Any]:
        """Bound W1 status/quiesce/seal; exact revision/epoch CAS for mutations. No arbitrary mounts or acknowledgements."""
        import anyio

        try:
            storage.need(store is not None, "storage-binding-mismatch", "select a private manager-issued job at startup")
            # Quiesce/status stay responsive while an admitted render completes.
            def control():
                if request.get("operation") == "seal":
                    with instance.operation("job_storage_seal"):
                        return store.control(request)
                if request.get("operation") != "status":
                    storage.need(instance.lifecycle()["state"] != "draining", "storage-admission-closed", "native session is draining")
                token = CURRENT_SESSION.set(instance)
                try:
                    return store.control(request)
                finally:
                    CURRENT_SESSION.reset(token)
            return await anyio.to_thread.run_sync(control)
        except Exception as exc:
            return require_ok({"ok": False, "code": getattr(exc, "code", "storage-observation-unknown"), "error": str(exc)[:1024]})

    @mcp.tool()
    async def render_job_diagram(expected_revision: int, expected_epoch: int, input_path: str | None = None,
                                 diagram_text: str | None = None, engine: str = "auto", family: str = core.DEFAULT_FAMILY,
                                 style: str = "", output_format: str = "svg", original_path: str | None = None,
                                 edited_paths: list[str] | None = None) -> dict[str, Any]:
        """Retain inputs/resources and render in the selected W1 volumes; seal through job_storage and deliver through the manager."""
        def render():
            storage.need(store is not None, "storage-binding-mismatch", "select a private manager-issued job at startup")
            return store.render(expected_revision, expected_epoch, input_path=input_path, diagram_text=diagram_text, engine=engine,
                                family=family, style=style, output_format=output_format, original_path=original_path,
                                edited_paths=edited_paths, runtime=runtime)
        return await operation("render_job_diagram", render)

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
    async def project_check_resource() -> str:
        """Project-wide diagram output and unaltraweb receipt check."""
        def checked():
            if store:
                raise storage.StorageError("storage-binding-mismatch", "legacy project checking is outside the selected W1 profile")
            with instance.operation("project_check"):
                return core.project_check(consumer_root, runtime=runtime)
        import anyio
        return core.json_dumps(await anyio.to_thread.run_sync(checked))

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
    def renderer_status(profile: str = core.DEFAULT_COMPATIBILITY) -> dict[str, Any]:
        """Inspect this server's selected local renderer identity without preparing or pulling it."""
        return tool_result(lambda: core.renderer_status(profile, runtime=runtime))

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
    async def project_check() -> dict[str, Any]:
        """Check all supported project diagram outputs and publish the provider receipt."""
        return await operation("project_check", lambda: core.project_check(consumer_root, runtime=runtime))

    @mcp.tool()
    async def render_diagram(
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
        return await operation("render_diagram",
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
                runtime=runtime,
            )
        )

    @mcp.tool()
    async def render_diagram_text(
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
        return await operation("render_diagram_text",
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
                runtime=runtime,
            )
        )

    @mcp.tool()
    async def initialize_artifact_export() -> dict[str, Any]:
        """Opt in to retained diagram bundles and prepare confined ignored recovery staging."""
        return await operation("initialize_artifact_export", lambda: artifacts.initialize_artifact_export(artifact_root))

    @mcp.tool()
    async def export_diagram_bundle(
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
        return await operation("export_diagram_bundle", lambda: artifacts.export_diagram_bundle(
            artifact_root, input_path=input_path, diagram_text=diagram_text, bundle_id=bundle_id,
            engine=engine, family=family, style=style, profile=profile, output_format=output_format,
            original_path=original_path, edited_paths=edited_paths, dry_run=dry_run,
            runtime=runtime,
        ))

    @mcp.tool()
    def check_diagram_bundle(path: str, sha256: str) -> dict[str, Any]:
        """Verify a diagram bundle's sender hash, complete tree and retained source/resource/SVG references."""
        return tool_result(lambda: artifacts.check_diagram_bundle(artifact_root, path=path, sha256=sha256))

    @mcp.tool()
    async def recover_diagram_bundle(path: str, sha256: str, bundle_id: str) -> dict[str, Any]:
        """Publish an exact sealed staging job to a new bundle name after a publication failure."""
        return await operation("recover_diagram_bundle", lambda: artifacts.recover_diagram_bundle(artifact_root, path=path, sha256=sha256, bundle_id=bundle_id))

    @mcp.tool()
    async def update(dry_run: bool = False) -> dict[str, Any]:
        """Update the diavisuals factory checkout."""
        return await operation("update", lambda: core.update_factory(dry_run=dry_run))

    @mcp.tool()
    def factory_manifest() -> dict[str, Any]:
        """Return the factory discovery manifest."""
        return tool_result(core.factory_manifest)

    mcp.run()
