# Notes for Codex agents

This repo is the shared diagram-style package and Docker renderer for Mermaid and PlantUML. Keep changes scoped to reusable style assets, examples, docs, renderer profiles, and lightweight validation tools.

Do not add project-specific rendering filters here. Consumers such as `my-slides-vault`, `unaltrepaper`, or `unaltraweb` should own their build pipelines and call the `diavisuals` CLI/MCP for diagram rendering instead of carrying Mermaid, PlantUML, Chromium, or Java layers themselves.

Run `make check` after style or renderer-contract changes. Use `make mcp-build` to prepare the shared Docker renderer. Use `make render-gallery` when the README/gallery images or compatibility profile outputs should be refreshed.

Renderer changes must preserve the private-staging boundary: never mount a
consumer workspace into the container, never enable runtime networking, and
publish only validated artifacts through an atomic host-side replacement. Run
`make lint tests tests-mcp` plus `make docker-test` for those changes.

## MCP Factory Contract

This repository is a reusable, user-scoped MCP factory for diagram style assets and rendering. Keep the MCP manifest aligned with the standard gContExt lifecycle:

- `make mcp-build`: prepare package/runtime dependencies in the factory checkout without starting a persistent service.
- `make mcp-check`: run a fast deterministic factory check without depending on a consumer workspace.
- `make mcp-smoke`: prove the factory MCP can answer a minimal style/tooling request.
- `make mcp-init PROJECT=/path/to/project`: initialize only the selected consumer workspace.
- `make project-check PROJECT=/path/to/project`: verify supported unaltraweb diagram outputs and publish only the confined provider receipt.
- `make mcp-down PROJECT=/path/to/project`: force-remove only renderer containers labeled for the selected consumer workspace; preserve images, volumes, other workspaces, and unrelated containers.

The smoke test stays in this repository because only `diavisuals` knows what a meaningful minimal style proof is. gContExt invokes `commands.smoke`, stores the latest result in its smoke status cache, and disables the generated switch only when the last known smoke state is `failed`.

The source and installed smoke execute the same two small real SVG renders using
the prepared selected runtime. Historical-version and W1 regression suites belong
to explicit test/CI targets. `mcp-smoke --protocol-only` is a partial diagnostic,
never the advertised factory smoke. Smoke does not prepare software or inherit a
consumer's private job grant.

## Common runtime convergence

Follow gaContExt #30/#31: managed controls come from versioned canonical scaffold
assets; generic runtime/client/worker behavior belongs to the common SDK dependency.
Keep provider code focused on diagram execution, styles and domain completeness.
The published native-private W1 profile is a migration input. Confirm the common
API and distribution before adopting it; missing fenced controls must be resolved
upstream rather than emulated with another provider ledger or lock.

Consumers should call this MCP from the workspace where slides, papers, or documentation are being produced; generated artefacts and project-specific decisions belong in the consumer repository.

## Shared gaContExt memory

When the companion gaContExt memory tools are connected, recall context with the
technical factory name `diavisuals` at task start and review its backlog before
development. Record reusable user preferences and future diagram ideas in their
appropriate scope, with concise provenance. Keep tentative ideas candidate/open
until the user supplies or approves their requirements. Use the selected original
consumer's project binding for project-specific notes, not a Docker job root.

Memory is supplied independently by gaContExt; upgrading this package does not
install or activate a memory server. If it is unavailable, continue the diagram
task and report that persistence did not happen. Do not create a second local
memory store, export memory into diagram bundles, or restart another busy client.
