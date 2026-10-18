# Release Matrix

Short SemVer tags identify a reviewed controller, style assets, compatibility
profile and renderer tuple. Engine versions are recorded independently.

## Current release: 0.7.0

0.7.0 adds [W1 private volume jobs and durable directory retention](w1-job-storage.md)
and migrates the stdio server to MCP SDK **2.3.0**. It preserves the native
[runtime selectors](runtime-selection.md), [D0 lifecycle](native-runtime-d0.md)
and existing artifact-handoff-v1 formats. Shared [gaContExt memory](memory-integration.md)
is an independent companion described by the shipped agent guide.

| Component | Reviewed version |
| --- | --- |
| Compatibility profile | `mermaid-12.0.0-plantuml-1.2026.9` |
| Mermaid CLI / library | 12.0.0 / 12.2.0 |
| PlantUML | 1.2026.9 |
| Puppeteer / Chrome for Testing | 25.14.0 / 155.0.8059.79 |
| Node | 24.21.0 |
| Java | Temurin 25.0.4.1 LTS; required for modern PlantUML PDF export |
| DOMPurify / KaTeX | 3.4.17 / 0.19.0 |
| Style family | `benizar` |
| Gallery | `docs/gallery/benizar/mermaid-12.0.0-plantuml-1.2026.9/manifest.csv` |

The new default requires a complete **zero-finding npm audit, without exceptions**.
The gate also runs an offline, no-mount image probe that verifies the installed
dependency lock, package versions and PlantUML JAR against the reviewed inputs.
Historical audit exceptions remain records for their exact old tuples, not
permissions to waive findings on the new renderer.

The browser entry used by Mermaid CLI is rebuilt from Mermaid's published core
with the locked DOMPurify and KaTeX versions. Updating npm's dependency tree alone
does not replace libraries embedded in upstream browser bundles. The image keeps
an esbuild 0.28.2 receipt binding 2,111 source inputs and 212 generated files; the
offline probe verifies their hashes and versions as well as the npm tree.

## Published artifacts

Use the [GitHub release](https://github.com/dosquartsdedocs/diavisuals/releases/tag/v0.7.0),
not an unqualified PyPI package name. Its immutable `release.json` binds the
integrated source commit, artifact sizes/hashes, descriptors and tested runtime.

| Asset | Purpose |
| --- | --- |
| `diavisuals-0.7.0-py3-none-any.whl` | Installable CLI/MCP with all package assets. |
| `diavisuals-0.7.0.tar.gz` | Source distribution. |
| `diavisuals-render-v0.7.0-linux-amd64.tar.gz` | Tested renderer Docker archive. |
| `mcp-factory-package.yml` | Exact installed discovery descriptor. |
| `mcp-job-storage.json` | Separate W1 provider declaration. |
| `acceptance.json` | Final-artifact acceptance, evidence hashes and profile limits. |
| `renderer-proof.json` / `npm-audit.json` | Installed-image identity proof and exact dependency audit. |
| `release.json` / `SHA256SUMS` | Publication identity and complete checksum inventory. |

The tested renderer's Docker image/config ID is
`sha256:6eb15796cf394cd53df723e3278800b600dbf526f7d9f79b681ae0858c8f6501`.
Its archive hash is a separate identity, recorded in `release.json`; no registry
RepoDigest is claimed. Its alias is `diavisuals/render:v0.7.0`.

```bash
gh release download v0.7.0 --repo dosquartsdedocs/diavisuals --dir /absolute/release-download
# From the download directory:
sha256sum --check SHA256SUMS
docker image load --input diavisuals-render-v0.7.0-linux-amd64.tar.gz
docker image inspect diavisuals/render:v0.7.0 --format '{{.Id}}'
uv tool install './diavisuals-0.7.0-py3-none-any.whl[mcp]'
export DIAVISUALS_RUNTIME_IMAGE=sha256:6eb15796cf394cd53df723e3278800b600dbf526f7d9f79b681ae0858c8f6501
diavisuals renderer-status
diavisuals factory-check
diavisuals mcp-smoke
```

Compare the inspected ID with the release manifest before activating it. A
differing pre-existing alias requires explicit resolution. Ordinary launch and
explicit runtime selection never pull, rebuild or retag an image. A source build
is development preparation; it is not a substitute for downloaded-artifact proof.
The published platform is Linux/amd64.

Existing stdio processes retain their loaded code. Start a normal fresh session
after updating; a successful install does not hot-reload an old connection or
activate a missing memory companion. Do not interrupt another busy client.

## Acceptance and publication

1. Run `make check`, `make lint tests tests-mcp`, `make docker-test` and installed
   wheel/sdist gates, including W1. Review the regenerated gallery and real PDF
   output, not just successful process exit codes.
2. Merge the reviewed source through normal PR/CI. Build final wheel/sdist from
   the clean integrated commit. Keep the tested image ID; export that exact image
   and record the resulting archive hash. Never replace a published old identity.
3. Bind final installed evidence to those exact bytes in `acceptance.json` and
   `release.json`; publish the annotated version tag and checksum-pinned assets.
4. Require the cold downloaded-wheel/sdist workflow to pass. Return the exact
   tuple and limits to coordinating consumers; do not silently update their pins.

W1's accepted native-private scope is directory retention on local Linux Docker,
with monitored budgets. Shared-manager adoption, foreign-registry ownership
transfer, remote Docker, hard quotas and compressed retention require separate
tested adapters. The geoprocessing diagram type remains future work.

## Historical releases

| Release | Profile / renderer | Main change |
| --- | --- | --- |
| `v0.6.0` | `mermaid-11.16.0-plantuml-1.2026.1` / `v0.3.0` | Live D0 identity, busy/drain observation and exact orphan recovery. |
| `v0.5.0` | Same retained renderer | Native runtime selection, provenance and freshness. |
| `v0.4.0` | Same retained renderer | Opt-in retained leaf diagram bundles. |
| `v0.3.x` | Same retained renderer | Private staging and hardened offline rendering. |
| `v0.2.0` | `mermaid-11.4.2-plantuml-1.2026.1` | Historical consumer-mounted renderer. |
| `v0.1.x` | `mermaid-10.9.1-plantuml-1.2020.02` | Historical Ubuntu-package-based renderer. |

The published v0.3.0 image remains
`sha256:5a6887b372a0e1c386a7b54981d11ae1910215baeb6a12dfd0706b3e85ef0846`,
with archive hash `de5d98d6bcff2f427e2ce83db6e7a14edaf6963d199483cb68674ab43d3d75e4`.
Older release assets and receipts are unchanged. Old-engine rollback reproduces
its original output bytes; new-engine output is validated independently. The
published 0.5.0 baseline lacks full live D0 identity and is reported as such.

The [previous preparation report](owner-preparation-2026-09-29.md),
[runtime-selection handoff](runtime-selection-report-2026-09-29.md) and
[historical audit decision](renderer-audit-exception-2026-09-30.md) retain the
identities and boundaries of those earlier publications.
