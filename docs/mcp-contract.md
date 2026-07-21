# MCP Contract

`diavisuals` exposes the shared visual style registry through a stdio MCP
server. It is a catalog and validation layer over pinned files in this
repository.

## Runtime Rule

Consumers should not require the MCP server to render documents. Builds should
read pinned files from a `diavisuals` checkout or submodule.

## Resources

| Resource | Description |
| --- | --- |
| `diavisuals://agent-guide` | Repository guidance for visual-style work. |
| `diavisuals://styles` | Style family inventory. |
| `diavisuals://compatibility` | Compatibility profile inventory. |
| `diavisuals://examples` | Source example inventory grouped by style family. |
| `diavisuals://factory-manifest` | Discovery manifest for ContExt-style launchers. |

## Tools

| Tool | Description |
| --- | --- |
| `style_inventory` | List style families, overrides, examples, and tokens. |
| `check_styles` | Validate a style family and compatibility profile. |
| `compatibility_status` | Inspect compatibility profiles. |
| `release_status` | Inspect Git release tag status. |
| `submodule_plan` | Return commands for pinning `diavisuals` as a submodule. |
| `update` | Update the factory checkout with a fast-forward pull. |
| `factory_manifest` | Return the factory discovery manifest. |

## ContExt Discovery

External launchers can scan sibling Git repositories for `mcp-factory.yml`.
The file exposes stable JSON commands for checks, updates, Codex MCP
registration, client configuration, and server launch.
