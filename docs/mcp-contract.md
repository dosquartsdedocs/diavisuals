# MCP Contract

`diavisuals` exposes the shared visual style registry and diagram renderer
through a stdio MCP server. It is the catalog, validation layer, and Dockerized
Mermaid/PlantUML rendering engine for agents working in consumer repositories.

## Runtime Rule

Consumers should declare `diavisuals` as an MCP dependency when they need
Mermaid or PlantUML rendering. Document builds still own their local pipeline,
but they should call this MCP/CLI for diagram rendering instead of carrying
Mermaid CLI, PlantUML, Chromium, or Java dependencies themselves. Submodule use
is optional and explicit for older compatibility paths.

The default generated workspace path is `.cache/diavisuals`. File-rendering
tools may also write to an explicit `output_path`, but that path must stay
inside the consumer workspace passed as `${workspaceFolder}` / `--project`.

The consumer root is fixed when the MCP starts. Rendering stages only the
selected source and style files outside that workspace. Containers receive no
consumer mount and no network, and artifacts are validated before atomic
publication. Failed renders preserve an existing output.

## Resources

| Resource | Description |
| --- | --- |
| `diavisuals://agent-guide` | Repository guidance for visual-style work. |
| `diavisuals://styles` | Style family inventory. |
| `diavisuals://compatibility` | Compatibility profile inventory. |
| `diavisuals://style-audit` | Default family audit covering tokens, examples, compatibility, and rendered gallery outputs. |
| `diavisuals://examples` | Source example inventory grouped by style family. |
| `diavisuals://project/check` | Check all supported diagram outputs in the startup consumer root and publish its provider receipt. |
| `diavisuals://factory-manifest` | Discovery manifest for ContExt-style launchers. |

## Tools

| Tool | Description |
| --- | --- |
| `style_inventory` | List style families, overrides, examples, and tokens. |
| `style_audit` | Validate tokens, examples, compatibility, and rendered gallery outputs for one family. |
| `check_styles` | Validate a style family and compatibility profile. |
| `compatibility_status` | Inspect compatibility profiles. |
| `release_status` | Inspect Git release tag status. |
| `submodule_plan` | Return optional commands for pinning `diavisuals` as a submodule. |
| `project_check` | Check every supported unaltraweb diagram source and atomically publish its version-1 provider receipt. |
| `render_diagram` | Render one `.mmd`, `.mermaid`, `.puml`, `.plantuml`, or `.uml` file to SVG, PNG, or PDF. |
| `render_diagram_text` | Render Mermaid or PlantUML source text and return the generated artifact path plus inline SVG or base64 image data. |
| `update` | Update the factory checkout with a fast-forward pull. |
| `factory_manifest` | Return the factory discovery manifest. |

Tool payloads with `ok: false` are returned as MCP tool errors (`isError:
true`) rather than successful protocol results. The JSON payload is available
in both text content and `structuredContent` for clients that need diagnostics.

## Project Check And Receipt

`project_check` recursively scans only `assets/`, `_chapters/`, and
`_documentation/` for `.mmd`, `.mermaid`, `.puml`, `.plantuml`, and `.uml`
sources. Each source requires `source.svg`, except that an existing
`source.edited.svg` is always preferred. The selected SVG must be a bounded
regular file and at least as new as its source. The check does not render or
modify sources or artifacts; its only successful write is an atomic,
descriptor-relative replacement of
`.unaltraweb/receipts/diavisuals.json`. Failed checks safely remove an older
receipt when its confined parent is accessible.

The receipt has exactly `schema_version`, `provider`, `provider_version`,
`release`, `request_sha256`, `ok`, `inputs`, and `artifacts`. The provider is
`diavisuals`; provider version and release are the current package version and
its `v<version>` release. `ok` is `true`. `inputs` is exactly empty until a
versioned local-include contract exists. Each artifact contains only its exact
project-relative `path` and lowercase `sha256`.

The request hash is SHA-256 over
`unaltraweb-companion-receipt-v1\0diavisuals\0`, followed by every supported
source sorted by project-relative path. Each UTF-8 path and then its exact file
bytes is prefixed by its unsigned eight-byte big-endian length. Reads are
bounded and no-follow; source discovery and receipt publication stay confined
to the startup workspace.

## ContExt Discovery

External launchers can scan sibling Git repositories for `mcp-factory.yml`.
The checkout manifest runs build, check, tests, and smoke in the factory and
passes `${workspaceFolder}` only to project operations such as init, stdio
serve, down, and rendering. Its `transport.command` is the client configuration
source; a separate `commands.client_config` hook is not required. The packaged
manifest keeps the same lifecycle split while using only the installed
`diavisuals` entrypoint, with no Make, checkout, or launcher-script dependency.

`commands.down` force-removes only containers carrying both the exact
`io.context.mcp-factory=diavisuals` label and the current workspace label; it
validates every Docker container ID before cleanup and preserves renderer
images, volumes, other workspaces, and unrelated containers. There is no
implicit all-workspace teardown; any future broad cleanup must be an explicit
down-all operation rather than changing the project-scoped down contract.
