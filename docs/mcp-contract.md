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
| `diavisuals://factory-manifest` | Discovery manifest for gContExt-style launchers. |

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

## gContExt Discovery

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

## Workspace Path Policies

The checkout manifest, packaged manifest, and CLI/MCP `factory_manifest`
response declare the same non-empty `workspace_rule.path_policies` under
`schema_version: 1`. With `binding: consumer` and `consumer_root: .`, every
policy resolves beneath the explicitly selected consumer workspace.

| Path | Type | Role | Git | Cleanup |
| --- | --- | --- | --- | --- |
| `.cache/diavisuals` | `directory` | `diagram-render-cache` | `ignored` | `disposable` |
| `.unaltraweb/receipts/diavisuals.json` | `file` | `diagram-validation-receipt` | `consumer` | `explicit` |

These paths were selected from their writers and lifecycle, independently of
the descriptive `generated_paths` list:

- `initialize_project` creates only `.cache/diavisuals`, idempotently. Inline
  rendering defaults to `outputs/<engine>/<digest>.<format>` beneath that
  cache. The apparent `inline/<engine>/<digest>` input path in render metadata
  is a logical name: the actual source bytes are staged privately, not saved
  in the consumer cache. Cached outputs can be regenerated from the supplied
  diagram text and rendering options.
- `project_check` owns exactly `.unaltraweb/receipts/diavisuals.json`. It
  atomically replaces that file on success and invalidates an older receipt
  on failure. `explicit` records this check-driven lifecycle. It does not
  claim the shared `.unaltraweb` or `receipts` directories. There is no
  guaranteed Git ignore rule for this receipt, so `consumer` reports its
  actual Git state without requiring ignored, tracked, or untracked status.

### Git Expectations

A Git consumer must have an effective ignore rule for the cache directory
and no tracked files beneath it. For example, add this to the consumer's
`.gitignore`:

```gitignore
/.cache/diavisuals/
```

An existing broader `.cache/` rule also covers it, as it does in this factory
checkout. The factory's `.gitignore` is not inherited by other repositories.
`init` does not write `.gitignore`, change the index, or enforce the policies.
`workspace-check` reports a missing ignore rule even before the cache exists,
and reports any forcibly tracked cache content; remediation is a separate
consumer decision.

There are no `versioned` entries in this first policy. The arbitrary source
and output paths accepted by rendering, the scanned `assets/`, `_chapters/`,
and `_documentation/` trees, and author-owned `*.edited.svg` files retain
their consumer-selected Git and retention rules. A future `versioned` entry
would require an existing path to be tracked and not ignored, including no
untracked content in a declared directory.

### Cleanup Boundaries

`cleanup` is descriptive metadata, never authorization to delete anything.
Neither `disposable` nor `explicit` adds cleanup behavior to `workspace-check`
or `down`. `down` removes only the selected workspace's labelled renderer
containers and preserves its cache, receipt, sources, and outputs.

Factory build/test paths (`.venv`, `.tmp`, `dist`), local example caches
(`.cache/mermaid`, `.cache/plantuml`, `.cache/puppeteer.json`), and versioned
gallery outputs in `docs/gallery` are factory concerns, outside this
consumer-bound policy. The developer-only `make clean` removes `dist`,
`.cache`, and `.tmp` in the factory; it is not the MCP `down` command.
Private render/build staging uses temporary directories. Shared image-build
locks live under `/run/user/<uid>/.unaltra-renderer-locks`, falling back to
`/tmp/.unaltra-renderer-locks-<uid>`, scoped by Docker endpoint and image.
Those locks and Docker storage are not consumer-relative paths.

### Verification

`make tests` checks manifest parity, real Git ignore coverage, cache/output
publication, receipt ownership, and preservation of consumer files by `down`.
To include integration tests against the central manager, explicitly select
its script (the manager containing commit
`217365a1bdf9a7772bfb76bc1ffd4d0d74bd7c59` or later is required):

```bash
DIAVISUALS_FACTORY_MANAGER=/absolute/path/to/my-scripts-factory/src/bash/mcp_factories/mcp-factory-manager.py make tests
python3 /absolute/path/to/mcp-factory-manager.py \
  validate --dir /absolute/path/to/factories --factory diavisuals --json
python3 /absolute/path/to/mcp-factory-manager.py \
  workspace-check --dir /absolute/path/to/factories --factory diavisuals \
  --workspace /absolute/path/to/consumer --json
```

The integration tests run the real manager against temporary Git consumers,
allow only read-only Git subprocesses during `workspace-check`, and compare
HEAD, index bytes, status, worktree registry, and the complete consumer tree
(including ignored files and Git metadata) before and after successful and
failing inspections. They cover absent and populated caches, missing ignores,
forcibly tracked cache files, receipt Git choices, wrong types, and symlinks.
The central manager is an explicit test dependency, not a runtime dependency.
