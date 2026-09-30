# H2 native runtime-selection handoff — 2026-09-29

## Result and publication status

Implemented and locally verified **0.5.0.dev0**, a new control-plane candidate
proposed for reviewed distribution as **0.5.0**. The published 0.4.0 assets remain
the accepted historical native baseline; they do not contain the H2 selector.

- Workspace: `/home/benizar/git/diavisuals`, branch `main`.
- Base/HEAD: `1e842967eabbad4cdb7dcb081493c1c25772dc5f` (`v0.4.0`). This identifies
  the base, **not** the uncommitted implementation.
- New commit/issue/PR/tag/publication: none; changes remain in this owner checkout.
- Reviewed the owner instructions, prior preparation report, hub follow-up rules
  and `2026-09-29-owner-preparation-roundup.md`, at hub HEAD
  `a33f512d59fafcbdb0d43738daa7892f46866e79`.
- Integrated the prior preparation documentation with an explicit historical
  baseline note and its original intake hash. Added the native interface guide
  [runtime-selection.md](runtime-selection.md), changelog and MCP/release links.
- The current installed producer-source identity is
  `sha256:2bc29327b100d7432c7e49a5b5b5d06454e6e4e521af8893a6b0808470d702c8`,
  equal in the tested wheel and sdist installations and their retained bundles.

The report is returned to the hub coordinator from this owner checkout. H1
catalogue/range fields, verified acquisition/activation and live manual/client
adoption remain separate integration steps.

## Native contract delivered

- Global CLI `--runtime-image` / `--runtime-expected-id`, environment
  `DIAVISUALS_RUNTIME_IMAGE` / `DIAVISUALS_RUNTIME_EXPECTED_ID`, and frozen Python
  `RuntimeSelection`. The MCP captures that selection at startup and adds a
  read-only `renderer_status` tool. Client snippets and the smoke subprocess
  propagate the selection.
- Full image IDs pin themselves. An alias requires an expected full image ID.
  Repository-digest refs require local Docker `RepoDigests` verification and can
  additionally require an expected image ID. Argument pairs override environment
  pairs atomically; incomplete or inconsistent selections fail.
- Explicit preparation, including `build-renderer`, only inspects local images.
  Missing/mismatched identities never build, pull, load or retag. Render/export
  and explicit dry runs share this resolver; execution uses the actual ID with
  `--pull=never`. The default profile's documented build/reuse behavior remains.
- Direct results expose effective runtime and resource identities. Inline cache
  keys include actual image ID, resource hash and producer version. Explicit
  selections persist hash-bound render records; project checks reject stale
  runtime/resources/source/output identities and invalidate the native receipt.
  Default direct output without existing provenance keeps its no-cache behavior;
  unmanaged legacy checks retain their original mtime contract.
- Author-edited SVGs retain preference and ownership; their generated originals
  provide renderer provenance. Metadata publication failure preserves an existing
  output. Checks do not render or rewrite authored material.
- New bundles retain `payload/runtime-selection.json` and the unchanged profile
  bytes. The outer artifact/request schema stays v1; the new verifier checks
  selection/profile/effective-ID agreement and reads old 0.4.0 bundles. Historical
  integrity verification is independent of today's selected/available runtime.
- The gallery launcher consumes the resolved ID returned by preparation rather
  than rereading the shared alias for execution.

The native descriptor advertises
`contracts.renderer_selection: explicit-local-ref-and-expected-id-v1`. No new
central H1 schema fields were introduced. `DIAVISUALS_DIR` remains a resource-tree
selection; altered profile bytes change the resource hash and cache/freshness
identity rather than impersonating the published resource tree.

## Exact local distribution proposal

These are **unpublished local test artifacts**, built after the final code,
version metadata, interface guide and integrated baseline documentation. The
final handoff report/link and expanded cold-release CI invocation were added
after that build; these hashes identify that tested snapshot, not a future final
0.5.0 release. They must never replace published 0.4.0 filenames/assets.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `dist/diavisuals-0.5.0.dev0-py3-none-any.whl` | 519280 | `634c2c9c3bbfdafff6e9534fd1285eb0d2fb0944d364f853cfd6c4485fa3663c` |
| `dist/diavisuals-0.5.0.dev0.tar.gz` | 514818 | `36d5c9def16fc9acabd1ee01fd6de1ef7541c657f2b80ca20b3cdbcfcba98935` |
| `mcp-factory-package.yml` | — | `d0d57d01d0e793bcfe5298591481be5f5d021a51ac7909aaf8192fe299045fa7` |

Proposed publication tuple:

1. Review/integrate this control plane and finalize version **0.5.0** consistently
   across package, lock and native manifests.
2. Build new wheel/sdist from the reviewed revision; rerun the installed and
   cold-publication gates on those exact final-version bytes. Publish new
   descriptor/producer/wheel/sdist hashes in the release's native `release.json`.
3. Reuse the existing tested renderer; no engine rebuild is required:
   - Image ID:
     `sha256:5a6887b372a0e1c386a7b54981d11ae1910215baeb6a12dfd0706b3e85ef0846`.
   - Existing alias: `diavisuals/render:v0.3.0` (unchanged throughout acceptance).
   - Existing published archive: `diavisuals-render-v0.3.0-linux-amd64.tar.gz`,
     SHA-256 `de5d98d6bcff2f427e2ce83db6e7a14edaf6963d199483cb68674ab43d3d75e4`,
     available in [v0.4.0](https://github.com/dosquartsdedocs/diavisuals/releases/tag/v0.4.0).
   - Platform `linux/amd64`, no registry RepoDigest claimed.
4. Once published, H2 can launch separate installed control planes with explicit
   expected selections on the same daemon. Verified acquisition, registration and
   real consumer upgrades still belong to their own coordinated transactions.

All files under `compat/`, `styles/`, `docker/`, plus the per-diagram staging
tools, compare byte-identically with `v0.4.0`. The default profile hash remains
`3d4e0ec5d3d646e68e14a9c549c338d11feb34b29d11e95b75b9f8c5fd2739ef`.

## Same-daemon proof

`tests/test_runtime_selection_docker.py` uses the actual Docker executable and
daemon, without an alias-mapping wrapper. It creates an **unstarted, mount-free
test container**, commits a labelled, untagged configuration-only derivative of
the existing renderer, and runs both actual image IDs. Existing rootfs layers
are preserved; the test adds no engine build or package installation. Only the
exact test container/image are retired afterward, without forced image removal.

The test uses a synthetic consumer and concurrent MCP sessions with distinct
startup selections. It verifies both engines through CLI and MCP, preparation
without builds, missing-ID and alias/expected-ID failures (including typed MCP
errors), A → B → A inline keys, stale project receipts, retained bundles and
unchanged profile bytes/active tags. Docker mounts are inspected in the actual
executed commands: private staging only, no consumer or engine checkout mounts.

Primary installed-wheel run:

```text
.tmp/h2-selections/36c27aad14b84863943f2ef6a3371413/
  evidence.json
  consumer/
```

- Selection A: published image ID `sha256:5a6887b372a0e1c386a7b54981d11ae1910215baeb6a12dfd0706b3e85ef0846`.
- Selection B: test image ID `sha256:5a7827726e94dd0b9e9553115390b874ae091641bab460dfd4839905120c0ff8`.
- `evidence.json` SHA-256:
  `637e848fc7aba39bf8063f23ed1c1f47c8f7a7c8a5a245db6f7915579c6bad7a`.
- `source_checkout: null`, package `0.5.0.dev0`, Python `3.10.20`.

The B image is a retired test fixture, not a published runtime selection or a
second supported engine-version tuple. Bundles remain independently verifiable
after its retirement; re-rendering a B bundle would require those image bytes.

Retained bundles relative to that run's `consumer/`:

| Bundle | SHA-256 of `bundle.json` |
| --- | --- |
| `.diavisuals/artifacts/selected-0-mermaid/bundle.json` | `df28d007ca3fc99354c9c51a3c946625d2badc737d3b1281c0a741a8beb8bc0a` |
| `.diavisuals/artifacts/selected-0-plantuml/bundle.json` | `011d2068bc29353fe08d12885000952d59af8ad4c8c001586a1cba0bf49de7f5` |
| `.diavisuals/artifacts/selected-1-mermaid/bundle.json` | `2077611b16b81a726de206bb704f5283de6be3db2e8baebe60be6cc4e0541eae` |
| `.diavisuals/artifacts/selected-1-plantuml/bundle.json` | `518c86e6178f69bc11d7cd88c4ecac71b147b8a5e68224bf1c8d63048a24838a` |

Installed-sdist evidence:
`.tmp/h2-selections/174b7a00ccaa49528c36ca4428a96aa4/evidence.json`, SHA-256
`63e930afd1b8e8095bde4cb110815101f1963369abc0ea251a8eae7069e301f4`.
Its independent B fixture was
`sha256:dcb1a96745b9f476ddd92ecb3dd551a62112d8009c364ede70e050a07fef4448`.
The final source-checkout proof is retained under
`.tmp/h2-selections/77e8f413d4d54110a7af8a4832897d8d/`.

These local evidence/consumer directories retain actual CLI commands/results,
MCP results, provenance, sources, SVGs and complete bundles. They are not public
release assets; the hub coordinator can retain them with this report.

## Final gates and commands

```bash
DIAVISUALS_HANDOFF_REFERENCE=/home/benizar/git/gacontext \
DIAVISUALS_FACTORY_MANAGER=/home/benizar/git/gacontext/src/bash/mcp_factories/mcp-factory-manager.py \
DIAVISUALS_SELECTION_EVIDENCE=/home/benizar/git/diavisuals/.tmp/h2-selections \
  make lint tests tests-mcp mcp-build mcp-check docker-test mcp-smoke

DIAVISUALS_HANDOFF_REFERENCE=/home/benizar/git/gacontext \
DIAVISUALS_DOCKER_SMOKE=1 \
DIAVISUALS_SELECTION_EVIDENCE=/home/benizar/git/diavisuals/.tmp/h2-selections \
  make tests-install

DIAVISUALS_MCP_SMOKE=1 .venv/bin/python -m unittest \
  tests.test_registry.RegistryTest.test_plantuml_renderer_blocks_workspace_includes_when_enabled

git diff --exit-code v0.4.0 -- compat styles docker tools/render-one.sh \
  tools/style-diagram-source.sh tools/resolve-style-name.sh tools/normalize-mermaid-svg.py
git diff --check
```

| Gate | Final result |
| --- | --- |
| Lint/style/factory/lifecycle/build preparation | Passed. `check` ran as a Make prerequisite; default preparation reused the existing image. |
| Host suite | 119 discovered, 112 passed, 7 runtime-gated. Includes 10 native-selection regression methods. |
| Explicit stdio gates | Two tests passed (ordinary factory transport and artifact protocol). |
| Docker gate | Five tests passed, including same-daemon selection and the original renderer/bundle tests. `mcp-smoke` reused its completed prerequisites in the combined invocation. |
| Wheel installation | Non-editable Python 3.10.20; installed lifecycle/MCP checks plus 45 tests passed, real Docker enabled. |
| Sdist installation | Non-editable Python 3.10.20; same 45 tests and lifecycle/MCP checks passed. |
| Real PlantUML workspace-include denial | Passed separately. |
| Preserved resource bytes / whitespace | Both Git checks passed. |

The existing artifact runtime tests also cover SVG/PNG/PDF, file/inline source,
selected originals/edits, relocation and retained-resource replay. The pinned
central v1 verifier/fixtures use Git objects at
`9167e3efb5968a64bb9100792163a179c1491860`. Counts above are individual gate
results, not a sum of disjoint tests. Installed MCPs emitted the existing
non-failing Pydantic `lifespan` annotation warning.

Additional installed checks passed:

- `renderer-status` with the live profile alias and the explicitly expected
  published ID returned `built: false` and the correct actual identity.
- The new installed verifier accepted the retained published-0.4.0 Mermaid and
  PlantUML bundles from the preparation report.
- The published 0.4.0 verifier accepted the new A/Mermaid and B/PlantUML bundle
  trees. This establishes v1 readability, not new-selector support in 0.4.0.
- The new verifier checked a retained B bundle while configured with an absent
  image ID, confirming that historical integrity checks do not prepare a runtime.

## Changed paths and remaining integration

Implementation: `src/diavisuals/runtime.py`, `registry.py`, `artifacts.py`,
`cli.py`, `mcp_server.py`, `__init__.py`; `tools/render-gallery-docker.sh`.

Distribution/discovery: `pyproject.toml`, `uv.lock`, `mcp-factory.yml`,
`mcp-factory-package.yml`. `uv lock` retained dependency versions and normalized
two Python-3.10-only dependency markers.

Gates: `Makefile`, `.github/workflows/verify-release.yml`,
`tests/test_registry.py`, `tests/test_runtime_selection.py`,
`tests/test_runtime_selection_docker.py`.

Documentation: `CHANGELOG.md`, `docs/mcp-contract.md`, `docs/releases.md`,
`docs/owner-preparation-2026-09-29.md` (existing local preparation work retained
and contextualized), `docs/runtime-selection.md`, and this report.

Tested points: Linux x86-64, Docker 27.2.0/API 1.47, CPython 3.12.3 in the source
checkout and 3.10.20 in both installed distributions, MCP 1.29.0, PyYAML 6.0.3,
Mermaid CLI 11.16.0/Puppeteer 25.9.0/PlantUML 1.2026.1 and family `benizar`.
Repository-digest comparison has deterministic tests; this archive-based
renderer has no RepoDigest, so no live registry-digest acquisition is claimed.
No broader Python, engine, architecture or package-version interval is certified.
The gallery launcher change passed shell/style validation; the unchanged visual
gallery was not regenerated in this unit.

**Next blocker:** owner review and publication of the new control plane, followed
by adoption of the integrated H1 contract and H2 verified acquisition/launch
mapping. The legacy bare-package `update --dry-run` plan remains outside a
hash-pinned hub update transaction. TIG/TIGIT/Geodisseny source state, active
registrations and image aliases were not migrated or rebuilt by this work.
