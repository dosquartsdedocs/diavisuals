# Release Matrix

`diavisuals` release tags stay short. The engine versions and supported diagram sets are documented here, in the README badges, and in the gallery manifests.

## Current Release

| Release tag | Compatibility profile | Mermaid CLI | PlantUML | Families | Gallery |
| --- | --- | --- | --- | --- | --- |
| `v0.4.0` | `mermaid-11.16.0-plantuml-1.2026.1` | 11.16.0 | 1.2026.1 | `benizar` | `docs/gallery/benizar/mermaid-11.16.0-plantuml-1.2026.1/manifest.csv` |

Badges for this release:

```markdown
![release](https://img.shields.io/badge/release-v0.4.0-2a5db0)
![Mermaid CLI](https://img.shields.io/badge/Mermaid_CLI-11.16.0-ff3670)
![PlantUML](https://img.shields.io/badge/PlantUML-1.2026.1-2a5db0)
![family](https://img.shields.io/badge/family-benizar-2a5db0)
```

The 0.4.0 release adds the opt-in artifact producer on the host. Engine versions,
styles, gallery outputs and renderer image build inputs are unchanged. See the
[owner release/pin handoff](artifact-handoff-release.md) for dependent upgrades.

## Published artifacts

The publication channel is the
[GitHub release](https://github.com/dosquartsdedocs/diavisuals/releases/tag/v0.4.0),
as for 0.3.1. A bare PyPI package name is not the release reference. Assets are:

| Asset | Purpose |
| --- | --- |
| `diavisuals-0.4.0-py3-none-any.whl` | Installable CLI/MCP package, including all runtime style/tool/profile assets. |
| `diavisuals-0.4.0.tar.gz` | Source distribution. |
| `diavisuals-render-v0.3.0-linux-amd64.tar.gz` | Docker archive of the unchanged, tested renderer. |
| `release.json` | Immutable Git revision, artifact hashes/sizes, producer source identity, runtime identity and capabilities. |
| `SHA256SUMS` | SHA-256 checksums for the four assets above. |

The renderer's **Docker image ID** remains
`sha256:5a6887b372a0e1c386a7b54981d11ae1910215baeb6a12dfd0706b3e85ef0846`.
It is distributed as a Docker archive rather than an OCI registry reference:
its archive SHA-256 is recorded separately in `release.json`. No registry
`RepoDigest` is claimed. Loading the archive supplies the existing profile alias
`diavisuals/render:v0.3.0`; rendering executes its immutable image ID.

Download into a new dedicated directory and verify before installation:

```bash
gh release download v0.4.0 --repo dosquartsdedocs/diavisuals --dir /absolute/release-download
# Run the remaining commands from /absolute/release-download.
sha256sum --check SHA256SUMS
docker image load --input diavisuals-render-v0.3.0-linux-amd64.tar.gz
docker image inspect diavisuals/render:v0.3.0 --format '{{.Id}}'
uv tool install './diavisuals-0.4.0-py3-none-any.whl[mcp]'
diavisuals factory-check
diavisuals mcp-smoke
```

Require the inspected ID to equal the value above. A differing pre-existing
profile alias must be reviewed before loading; retain any custom image under
its own name. After this explicit bootstrap, normal `ensure-renderer`/`mcp-build`
reuses the released image. Building an absent image from source is a development
workflow, not the published-runtime acceptance proof. The archive supports
Linux/amd64; no additional platform build is implied.

For dependency pins, append `#sha256=<wheel hash from release.json>` to the
wheel URL, record the release's full Git commit and keep the runtime archive
hash plus image ID. `verify-release.yml` downloads the public assets on a fresh
GitHub runner, checks hashes and the tagged commit, loads the archive, installs
the wheel and exercises real MCP, both engines, retained-source replay and
relocation. It can also be rerun with `workflow_dispatch` and the release tag.

## Maintainer publication

1. Run the owner/rollout checks in `docs/artifact-handoff-release.md`, including
   installed-package and real Docker tests. Confirm unchanged renderer inputs
   against the previous release and preserve the tested image ID.
2. Merge reviewed release metadata through the protected-branch PR workflow.
   Build wheel/sdist from that clean commit; export the exact existing image with
   `docker image save diavisuals/render:v0.3.0`, gzip it without timestamps, and
   recheck the alias's image ID. Do not rebuild or retag a different engine image.
3. Prepare `release.json` and checksums from actual artifact bytes. Create and push
   the annotated version tag at the approved commit. Upload all assets to a draft
   GitHub release, inspect them, then publish it. Never replace a published tag or
   differing asset silently.
4. Require the cold published-artifact workflow to pass before returning adoption
   pins to Diapora, Unaltraweb or Unaltrepaper. Consumer dependency updates preserve
   the full `mcp_dependencies` closure and retain the existing direct-render tools.

## Legacy Compatibility Records

`v0.2.0` used Mermaid CLI 11.4.2 and mounted the consumer workspace into the
renderer. Upgrade to `v0.3.0` for supported Node/Puppeteer dependencies,
private staging, and the hardened container boundary.

| Release | Compatibility profile | Mermaid CLI | PlantUML | Purpose |
| --- | --- | --- | --- | --- |
| `v0.2.0` | `mermaid-11.4.2-plantuml-1.2026.1` | 11.4.2 | 1.2026.1 | Records the first Docker renderer contract. |
| `v0.1.x` | `mermaid-10.9.1-plantuml-1.2020.02` | 10.9.1 | 1.2020.02 | Documents the older Ubuntu-package-based paper image. |

These profiles are record-only and cannot build a renderer from the current
checkout. They are retained so consumers can compare what changed when
upgrading engines.
