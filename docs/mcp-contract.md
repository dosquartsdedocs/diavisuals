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

## Resources

| Resource | Description |
| --- | --- |
| `diavisuals://agent-guide` | Repository guidance for visual-style work. |
| `diavisuals://styles` | Style family inventory. |
| `diavisuals://compatibility` | Compatibility profile inventory. |
| `diavisuals://style-audit` | Default family audit covering tokens, examples, compatibility, and rendered gallery outputs. |
| `diavisuals://examples` | Source example inventory grouped by style family. |
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
| `render_diagram` | Render one `.mmd`, `.mermaid`, `.puml`, `.plantuml`, or `.uml` file to SVG, PNG, or PDF. |
| `render_diagram_text` | Render Mermaid or PlantUML source text and return the generated artifact path plus inline SVG or base64 image data. |
| `update` | Update the factory checkout with a fast-forward pull. |
| `factory_manifest` | Return the factory discovery manifest. |

## ContExt Discovery

External launchers can scan sibling Git repositories for `mcp-factory.yml`.
The file exposes stable JSON commands for checks, updates, Codex MCP
registration, client configuration, server launch, and renderer teardown.
`commands.down` force-removes only containers carrying the exact
`io.context.mcp-factory=diavisuals` label; it preserves renderer images,
volumes, and unrelated containers and is safe to run repeatedly.
