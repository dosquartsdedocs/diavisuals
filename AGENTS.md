# Notes for Codex agents

This repo is the shared diagram-style package and Docker renderer for Mermaid and PlantUML. Keep changes scoped to reusable style assets, examples, docs, renderer profiles, and lightweight validation tools.

Do not add project-specific rendering filters here. Consumers such as `my-slides-vault`, `unaltrepaper`, or `unaltraweb` should own their build pipelines and call the `diavisuals` CLI/MCP for diagram rendering instead of carrying Mermaid, PlantUML, Chromium, or Java layers themselves.

Run `make check` after style or renderer-contract changes. Use `make mcp-build` to prepare the shared Docker renderer. Use `make render-gallery` when the README/gallery images or compatibility profile outputs should be refreshed.

Renderer changes must preserve the private-staging boundary: never mount a
consumer workspace into the container, never enable runtime networking, and
publish only validated artifacts through an atomic host-side replacement. Run
`make lint tests tests-mcp` plus `make docker-test` for those changes.

## MCP Factory Contract

This repository is a reusable, user-scoped MCP factory for diagram style assets and rendering. Keep the MCP manifest aligned with the standard ContExt lifecycle:

- `make mcp-build`: prepare package/runtime dependencies in the factory checkout without starting a persistent service.
- `make mcp-check`: run a fast deterministic factory check without depending on a consumer workspace.
- `make mcp-smoke`: prove the factory MCP can answer a minimal style/tooling request.
- `make mcp-init PROJECT=/path/to/project`: initialize only the selected consumer workspace.
- `make project-check PROJECT=/path/to/project`: verify supported unaltraweb diagram outputs and publish only the confined provider receipt.
- `make mcp-down PROJECT=/path/to/project`: force-remove only renderer containers labeled for the selected consumer workspace; preserve images, volumes, other workspaces, and unrelated containers.

The smoke test stays in this repository because only `diavisuals` knows what a meaningful minimal style proof is. ContExt invokes `commands.smoke`, stores the latest result in its smoke status cache, and disables the generated switch only when the last known smoke state is `failed`.

Consumers should call this MCP from the workspace where slides, papers, or documentation are being produced; generated artefacts and project-specific decisions belong in the consumer repository.
