# Native renderer selection

This interface is provided by the **0.5.0 control plane**.
Published 0.4.0 does not implement this selector. Engine images,
style assets and the bytes of all published compatibility profiles are unchanged.

## Select outside the profile

Use global CLI options **before the subcommand**, or environment variables:

| CLI | Environment | Meaning |
| --- | --- | --- |
| `--runtime-image` | `DIAVISUALS_RUNTIME_IMAGE` | Local full image ID, repository digest, or alias constrained by an expected image ID. |
| `--runtime-expected-id` | `DIAVISUALS_RUNTIME_EXPECTED_ID` | Expected Docker config/image ID, `sha256:` followed by 64 lowercase hex digits. |

Accepted selections:

- Full image ID: `sha256:<64 hex>`. It is its own expected ID. A separately
  supplied expected ID must agree.
- Repository digest: `repository@sha256:<64 hex>`. Docker must resolve it locally
  and report that exact reference in `RepoDigests`. An optional expected image ID
  additionally constrains the selected platform's config. A registry digest is
  not interchangeable with an image ID.
- Alias/tag: an expected image ID is mandatory. The alias must resolve to that
  ID; rendering then executes the immutable ID, not the alias.

CLI arguments are one selection: supplying either argument replaces the whole
environment pair. An incomplete pair never borrows an expected ID or ref from
the environment. Empty/malformed values fail. With neither argument, the CLI
reads the environment. Python callers can pass a frozen
`diavisuals.runtime.RuntimeSelection` as `runtime=` to preparation, status,
rendering, export and project checks; `RuntimeSelection()` explicitly selects
default-profile behavior without environment fallback.

Example using the existing released renderer (no pull or tag change):

```bash
IMAGE=sha256:5a6887b372a0e1c386a7b54981d11ae1910215baeb6a12dfd0706b3e85ef0846
diavisuals --runtime-image "$IMAGE" renderer-status
diavisuals --runtime-image "$IMAGE" ensure-renderer
diavisuals --project /absolute/synthetic-consumer --runtime-image "$IMAGE" \
  render-diagram-text --text 'flowchart LR; A-->B' --no-data
```

For lifecycle/stdio launchers, set both environment variables from the verified
installation selection (the expected ID can be omitted for a full image ID):

```bash
export DIAVISUALS_RUNTIME_IMAGE=diavisuals/render:v0.3.0
export DIAVISUALS_RUNTIME_EXPECTED_ID=sha256:5a6887b372a0e1c386a7b54981d11ae1910215baeb6a12dfd0706b3e85ef0846
diavisuals ensure-renderer
MCP_CONSUMER_WORKSPACE=/absolute/synthetic-consumer diavisuals mcp serve
```

The MCP server captures the selection once at startup alongside the consumer
root. Its `renderer_status` tool reports the effective selection without
preparation. Render/export/project-check tools use that same selection; they do
not offer a per-call switch to a different environment. CLI-generated client
snippets include the explicit selection, as does the `mcp-smoke` subprocess.
No active client registration is changed merely by generating a snippet.

Since 0.6.0, normal MCP work is preparation-free even with the default profile:
an absent renderer fails instead of building. Standalone CLI preparation retains
the behavior below. Live serving identity and safe per-instance shutdown are
defined by the [D0 native profile](native-runtime-d0.md).

## Preparation and failure behavior

For an explicit selection, `renderer-status`, `ensure-renderer` and even
`build-renderer` are **local inspection only**. They never pull, build, load an
archive or retag. Missing images, unavailable daemons, unverified repository
digests and expected-ID mismatches fail. Rendering and export stop before
creating output/cache/export state on such failures. Explicit dry runs also
perform this read-only identity check. Docker execution always uses
`--pull=never` and the resolved image ID, so removing an image after inspection
cannot trigger an implicit pull. Render containers retain the private-staging,
networkless, read-only and non-root boundary.

Without an explicit selection, the documented profile behavior remains:

- `renderer-status` inspects the profile alias without preparing it.
- `ensure-renderer` reuses an existing image or builds an absent profile image
  under the shared per-daemon/per-image build lock.
- `build-renderer` builds the profile alias explicitly.
- Default render dry runs remain Docker-independent plans; their image ID is
  `null` and their planned inline path need not equal the resolved render path.

Acquire and verify published runtime archives/registry images outside the
explicit selector, before calling the lifecycle. The selector verifies identity,
not arbitrary image compatibility: the caller must obtain expected IDs from the
reviewed wheel/runtime publication tuple. It does not assert that an arbitrary
correctly identified image implements Mermaid/PlantUML.

The gallery launcher now takes the effective ID from `ensure-renderer`, including
environment selection, instead of independently executing the profile alias.

## Resource identity and provenance

Changing `DIAVISUALS_DIR` selects a different resource tree. Editing a profile in
that tree changes its SHA-256; it is not a transparent override of the published
runtime. Native image selection does not edit those bytes. For the released
default profile, the unchanged SHA-256 is:

```text
3d4e0ec5d3d646e68e14a9c549c338d11feb34b29d11e95b75b9f8c5fd2739ef
```

Successful direct render results expose `runtime` (mode, requested ref, expected
image ID, actual image ID and profile hash), `resources_sha256` and
`render_provenance`. Resource identity covers the exact selected profile plus
the staged style/tool closure, independently of image selection. The staged
closure is checked against that identity before and after rendering.

New bundles retain `payload/runtime-selection.json` as producer-owned evidence,
alongside their existing actual image ID in the request, runtime actor and
render evidence. The native verifier checks agreement with the retained profile
bytes and expected ID. The outer artifact schema and retained request remain
v1. Historical 0.4.0 bundles without selection evidence remain readable;
integrity checking/recovery does not inspect Docker or depend on the current
runtime selection. Producer source hashes distinguish the new control-plane
implementation from 0.4.0, even when it uses the same renderer.

## Cache and freshness

Inline output keys include the resolved image ID, resource identity and producer
version as well as the source/options. A → B → A returns to A's path while B has
a distinct path. Rendering still executes freshly on every call; the cache paths
are storage identities, not a new reuse shortcut.

Explicit selections persist direct-output provenance under
`.cache/diavisuals/renders/<output-path-hash>.json`. Inline cache outputs do too.
Once an output has this record, a default-profile render refreshes it when
switching back. Legacy default-profile rendering to an explicit output path
continues to avoid creating a cache when no provenance record already exists.

`project-check`:

- Retains source/mtime checks for legacy unmanaged outputs in default mode.
- Requires provenance for generated SVGs under an explicit selection.
- Accepts inline provenance for a paired project SVG only when its rendered
  source bytes exactly match the current project source; the cache's logical
  input name is not treated as a real source file.
- For managed outputs, verifies source/output hashes, producer version, current
  resource/profile hashes and the currently selected local image ID. Inspection
  never builds a missing image. A changed identity or invalid record invalidates
  the provider receipt and requires a render. Missing records fail in explicit
  mode; default mode retains the legacy unmanaged-output fallback.
- Continues to prefer authored `*.edited.svg`; checks its generated original's
  provenance rather than attributing the author's edits to a renderer. Source,
  generated original and edits are never rewritten by the check.

The native unaltraweb receipt retains its v1 source-request format. Runtime
evidence lives in native render provenance and check results; no speculative H1
receipt/catalogue fields have been introduced. Consumers caching independently
must include the effective runtime/resource identity in their own cache keys.

## Distribution and compatibility limits

Control-plane **0.5.0** has new wheel/sdist/descriptor hashes; the published 0.4.0
assets remain available separately. The existing renderer archive and image ID
are reused in the new release tuple; no engine rebuild is needed. Coordinators
that pin helper 0.4.0 must accept their own adoption of 0.5.0.

Same-daemon acceptance uses the published renderer and an untagged, config-only
test derivative of its rootfs. This proves native selection, fail-closed checks,
CLI/MCP isolation, cache transitions and retained provenance for two actual IDs.
It is not a compatibility claim for a second engine version. The registry-digest
branch also has deterministic inspection tests; the released archive has no
registry RepoDigest, so live registry-digest acquisition is not claimed.

H1 catalogue/range adoption and H2 acquisition/activation remain hub integration
steps. This native contract is advertised as
`contracts.renderer_selection: explicit-local-ref-and-expected-id-v1`.
