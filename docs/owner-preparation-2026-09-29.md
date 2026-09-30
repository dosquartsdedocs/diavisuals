# Packaged factory preparation report — 2026-09-29

Historical baseline: this report records acceptance of the published **0.4.0**
bytes, including the limitations stated below. The subsequent
[native runtime-selection candidate](runtime-selection.md) is **0.5.0.dev0**,
proposed for a separate control-plane distribution. The baseline's conclusion
does not assert that 0.4.0 implements the later H2 selector. The original report
was received by the hub as SHA-256
`9f6402678af79555d7249f81d0566ac4f76e9530bdb6e56ca78bddca25eb270b`;
this integration note is a later documentation addition.

## Result and handoff to gContExt

**Published v0.4.0 satisfies the tested native installation, preparation and
rendering requirements. No new implementation or release is needed.** The
downloaded wheel and sdist resolve their own assets and installed lifecycle,
serve real MCP stdio, render both engines and export/verifiably retain v1 bundles.

- Owner checkout: `/home/benizar/git/diavisuals`, branch `main`.
- Tested source/tag revision: `1e842967eabbad4cdb7dcb081493c1c25772dc5f`
  (`v0.4.0`), initially clean and identical to the published `release.json`.
- Rules consulted: owner `AGENTS.md`; hub
  `src/bash/mcp_factories/handoffs/owner-preparation-prompts.md` and
  `audits/2026-09-28-manual-runtime-baseline.md`. Hub HEAD observed:
  `a33f512d59fafcbdb0d43738daa7892f46866e79`.
- Tracked-path changes for this preparation: this report and the link in
  `docs/releases.md`. Runtime, descriptors, profiles, styles and pins retain
  their released content. This documentation is an **unpublished working-tree
  handoff**, not a new released artifact.
- New issue/PR/commit/tag: none. Existing release PR:
  [#11](https://github.com/dosquartsdedocs/diavisuals/pull/11).
- Coordinator action: record this evidence against published v0.4.0; map the
  native descriptor and exact package/runtime selection after H1 is integrated.
  The report is returned from this owner checkout for the hub's coordinating
  session; it does not edit the hub or switch live clients/consumers.

## Published identity and current descriptor

Publication:
[GitHub release v0.4.0](https://github.com/dosquartsdedocs/diavisuals/releases/tag/v0.4.0),
published `2026-09-24T20:03:10Z`. All five assets were freshly downloaded and
`sha256sum --check SHA256SUMS` passed for its four entries. Artifact sizes also
match `release.json`.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `diavisuals-0.4.0-py3-none-any.whl` | 501550 | `bfedcc9e2554f25ce4a1c33e556f352210848fccb8da800d1c3900dd86c48c93` |
| `diavisuals-0.4.0.tar.gz` | 494022 | `642f6df767f54d501ce7b2a8abe444c713f076de5d9b0c0b77ee63291f5b1921` |
| `diavisuals-render-v0.3.0-linux-amd64.tar.gz` | 1014844791 | `de5d98d6bcff2f427e2ce83db6e7a14edaf6963d199483cb68674ab43d3d75e4` |
| `release.json` | 2175 | `49d6ee6142e61e9b895ff529d9d37ea5e6c5119cbec4458ea67411657cc5ad3e` |
| `SHA256SUMS` | 379 | `6a47e4707b1b8d4a65d50b15a902b09877e50017acba1536ea78db0f61390139` |

The existing descriptor is available without a clone:

- Immutable source:
  [`mcp-factory-package.yml` at the released commit](https://raw.githubusercontent.com/dosquartsdedocs/diavisuals/1e842967eabbad4cdb7dcb081493c1c25772dc5f/mcp-factory-package.yml).
- In the verified wheel: `diavisuals/assets/mcp-factory.yml`.
- Installed discovery: `diavisuals factory-manifest` and MCP resource
  `diavisuals://factory-manifest`. JSON adds the success field `ok`; the
  descriptor fields were compared structurally with the packaged YAML.
- Exact YAML SHA-256:
  `6acb6fa272011de125b9718e2a5b0a1b30d5848f3b04feb01ea9e9387e3124e7`.
  Source, downloaded wheel and both installed environments have identical bytes.

The package descriptor uses `[diavisuals, mcp, serve]`, consumer binding through
`MCP_CONSUMER_WORKSPACE`, CLI lifecycle commands and
`checkout_required_for_make_lifecycle: false`. It contains no `${factoryRoot}`
reference. The checkout's separate `mcp-factory.yml` continues to describe its
Make/launcher development lifecycle.

Exact install reference for the hub's later selection:

```text
diavisuals[mcp] @ https://github.com/dosquartsdedocs/diavisuals/releases/download/v0.4.0/diavisuals-0.4.0-py3-none-any.whl#sha256=bfedcc9e2554f25ce4a1c33e556f352210848fccb8da800d1c3900dd86c48c93
```

## Wheel/runtime relationship and preparation boundary

`release.json` binds that wheel and source commit to:

- Profile `mermaid-11.16.0-plantuml-1.2026.1`, family `benizar`.
- Profile SHA-256:
  `3d4e0ec5d3d646e68e14a9c549c338d11feb34b29d11e95b75b9f8c5fd2739ef`.
- Profile alias `diavisuals/render:v0.3.0`.
- Immutable Docker image ID:
  `sha256:5a6887b372a0e1c386a7b54981d11ae1910215baeb6a12dfd0706b3e85ef0846`.
- Archive hash from the table above; platform `linux/amd64`; no registry
  `RepoDigest` (`[]`). An image ID and an archive checksum are different identities.
- Producer source revision:
  `sha256:547e898d58fe8f66206c9345b30afc55fd268a17ec0e39e8e262a53f648741f7`,
  verified from both installed packages and retained in their bundles.

This session streamed the archive, verified all **41 content-addressed blobs**,
hashed the image config to the published image ID, and compared its rootfs
diff IDs with the locally installed image. The matching shared image was reused:
no archive load, image rebuild or retag was needed. Repeated installed
`ensure-renderer` calls returned `built: false` and the published ID. Every real
render executed that ID, rather than the mutable alias.

A separate offline, mount-free container probe reported Mermaid CLI `11.16.0`,
Puppeteer `25.9.0` and PlantUML `1.2026.1`. The installed PlantUML JAR SHA-256 was
`89c116168a2a0f7cf5292e11617ba22abd743f891914f1fec5bc9c7d257b3092`,
matching the packaged profile.

Cold preparation remains the explicit archive bootstrap documented in
[releases.md](releases.md#published-artifacts). `ensure-renderer` is not a
release downloader or a verifier of the expected published ID: an absent alias
can trigger a local source build. A manager must verify/bootstrap the selected
published archive before invoking this lifecycle. Source build planning was
checked with `build-renderer --dry-run`; rebuilding the engine was unnecessary.

Independent cold-load evidence is the successful published-artifact CI run
[36052260081](https://github.com/dosquartsdedocs/diavisuals/actions/runs/36052260081)
at the same commit on 2026-09-24. That workflow downloads/verifies the assets,
loads the archive on a fresh runner and tests the installed wheel. This session
queried its result; it did not claim to repeat a cold Docker load locally.

## Installed acceptance and isolation

Two dedicated non-editable environments used the actual downloaded assets:

| Installation | Python | Result |
| --- | --- | --- |
| Published wheel with `[mcp]` | CPython 3.12.3 | Installed lifecycle, resource reads, real CLI/MCP renders and bundles passed; 34 artifact tests passed. |
| Published sdist with `[mcp]` | CPython 3.10.20 | Same acceptance passed; 34 artifact tests passed. |
| Locally rebuilt wheel and sdist | CPython 3.10.20 each | `make tests-install` passed, including 34 artifact tests per installation with Docker enabled. The builds were byte-identical to the published wheel/sdist before adding this report. |

In both downloaded installations `registry.source_checkout()` is `None` and
asset resolution points into `site-packages/diavisuals/assets`. The tests removed
`PYTHONPATH`/`DIAVISUALS_DIR` overrides. The session runner invoked the installed
CLI from independent synthetic consumers under `/tmp/opencode`, not from the
engine source directory.

Observed capabilities:

- Styles, compatibility profiles, packaged examples, tokens, gallery audit and
  renderer build assets resolve from the installed distribution.
- `factory-manifest`, `style-inventory`, `compatibility-status`, `check`,
  `style-audit`, `install-check`, `factory-check`, `lifecycle-check`, `self-test`,
  `release-status` and `mcp-smoke` passed.
- Explicit `init`, `init --artifact-export`, repeated `ensure-renderer`, real
  `render-diagram`, `project-check`, export/check of bundles and consumer-scoped
  `down` passed. `project-check` published the synthetic provider receipt.
- Real MCP negotiated protocol `2025-11-25`, listed all **15 tools** and read all
  **7 resources** successfully. MCP exported and verified a real PlantUML bundle.
- The existing artifact suite exercised Mermaid and PlantUML with file and inline
  input, SVG/PNG/PDF outputs, original/edited SVG selection, bundle verification,
  producer-job retirement, final-consumer relocation and retained-resource replay.
  It also ran the pinned central verifier/fixtures, revision
  `9167e3efb5968a64bb9100792163a179c1491860`, from immutable Git objects.
- Renderer commands mounted only private staged input/style/tool bytes and a
  private output directory, never an engine checkout or consumer tree. They used
  `--network none`, a read-only root filesystem, dropped capabilities, non-root
  execution and scoped unique containers. The Docker cleanup test verified
  cross-consumer isolation; the real PlantUML workspace-include denial test passed.

`update --dry-run` resolved a package operation without a clone. Its existing
plan uses `uv pip install --python <installed interpreter> --upgrade
diavisuals[mcp]`; it does **not** bind to the GitHub wheel above. Actual update
and global client registration were not part of acceptance. H1's eventual
verified release selection must not treat that bare-name plan as this exact pin.

## Commands and gate results

Executed from the owner checkout, except checksum verification from the download
directory. Commands below use `P=.tmp/owner-preparation-20260929` as shorthand
for the actual paths used during this run.

```bash
gh release download v0.4.0 --repo dosquartsdedocs/diavisuals \
  --dir .tmp/owner-preparation-20260929/release
# In that release directory:
sha256sum --check SHA256SUMS

# From the owner checkout:
P=.tmp/owner-preparation-20260929
uv venv --python 3.12 "$P/wheel-venv"
uv pip install --python "$P/wheel-venv/bin/python" \
  "$P/release/diavisuals-0.4.0-py3-none-any.whl[mcp]"
uv venv --python 3.10 "$P/sdist-venv"
uv pip install --python "$P/sdist-venv/bin/python" \
  "$P/release/diavisuals-0.4.0.tar.gz[mcp]"

# Session evidence runner; both passed (retained locally, hash below).
env -u PYTHONPATH -u DIAVISUALS_DIR -u MCP_CONSUMER_WORKSPACE \
  "$P/wheel-venv/bin/python" "$P/verify-installed.py" \
  /tmp/opencode/diavisuals-preparation-wheel-20260929
env -u PYTHONPATH -u DIAVISUALS_DIR -u MCP_CONSUMER_WORKSPACE \
  "$P/sdist-venv/bin/python" "$P/verify-installed.py" \
  /tmp/opencode/diavisuals-preparation-sdist-20260929

env -u PYTHONPATH -u DIAVISUALS_DIR \
  DIAVISUALS_HANDOFF_REFERENCE=/home/benizar/git/gacontext \
  DIAVISUALS_INSTALLED=1 DIAVISUALS_DOCKER_SMOKE=1 DIAVISUALS_MCP_SMOKE=1 \
  "$P/wheel-venv/bin/python" -m unittest tests.test_artifacts tests.test_artifacts_runtime
env -u PYTHONPATH -u DIAVISUALS_DIR \
  DIAVISUALS_HANDOFF_REFERENCE=/home/benizar/git/gacontext \
  DIAVISUALS_INSTALLED=1 DIAVISUALS_DOCKER_SMOKE=1 DIAVISUALS_MCP_SMOKE=1 \
  "$P/sdist-venv/bin/python" -m unittest tests.test_artifacts tests.test_artifacts_runtime

DIAVISUALS_HANDOFF_REFERENCE=/home/benizar/git/gacontext \
DIAVISUALS_FACTORY_MANAGER=/home/benizar/git/gacontext/src/bash/mcp_factories/mcp-factory-manager.py \
  make lint tests tests-mcp mcp-build mcp-check docker-test mcp-smoke
DIAVISUALS_HANDOFF_REFERENCE=/home/benizar/git/gacontext \
DIAVISUALS_DOCKER_SMOKE=1 make tests-install
DIAVISUALS_MCP_SMOKE=1 .venv/bin/python -m unittest \
  tests.test_registry.RegistryTest.test_plantuml_renderer_blocks_workspace_includes_when_enabled
docker run --rm --pull=never --name diavisuals-owner-preparation-20260929-probe \
  --label io.context.mcp-factory=diavisuals --label io.context.mcp-role=owner-preparation \
  --network none --read-only --cap-drop ALL --security-opt no-new-privileges=true \
  --user 65532:65532 --memory 512m --pids-limit 128 \
  --tmpfs /tmp:rw,nosuid,nodev,size=67108864,mode=1777 \
  sha256:5a6887b372a0e1c386a7b54981d11ae1910215baeb6a12dfd0706b3e85ef0846 \
  bash -c "mmdc --version && node -p \"require('/opt/mermaid/node_modules/puppeteer/package.json').version\" && plantuml -version && sha256sum /opt/plantuml/plantuml.jar"
git diff --check
```

All final gates passed. The host suite discovered **108 tests: 102 passed, 6
runtime-gated**. The explicit gates covered those runtime paths: two real stdio
checks, four Docker/artifact-runtime tests and the separate include-denial test.
`check` ran as a Make prerequisite. In the combined invocation, `mcp-smoke`
reused its already completed `tests-mcp` and `docker-test` prerequisites.
Installed environments emitted the existing non-failing Pydantic `lifespan`
forward-reference warning; protocol and rendering assertions passed.

### Disk-space interruption and requested cleanup

The first downloaded-wheel artifact-suite attempt failed with an empty output
and `OSError: [Errno 28] No space left on device`. It is recorded as a failed
attempt, not as successful acceptance. After the user requested cleanup:

- Checked disk/inodes, Docker disk usage, all containers associated with the
  three Diavisuals renderer tags, the factory label and manual references.
- No Diavisuals container needed removal. Removed the unused historical images
  with `docker image rm diavisuals/render:v0.1.0 diavisuals/render:v0.1.1`.
- Removed image IDs were
  `sha256:af0eb844203906d3223e60fc7b51aa8ce242cd425c80c887544c44395aeb2039`
  and `sha256:0d659757822377dc563b89d89bdeeae7b6d6a0ae0d32b3362a3e0a86161e5fe2`.
- The supported `v0.3.0` image ID stayed unchanged. No broad Docker prune,
  manual-worker rebuild or manual configuration/registration change was made.
- Available disk space was 14 GiB immediately after cleanup. Other activity
  shared the filesystem, so this is not a claim that deleting those images alone
  reclaimed that amount. Both published suites and all subsequent gates passed.

## Retained evidence for the coordinator

Both synthetic consumers remain available locally:

```text
/tmp/opencode/diavisuals-preparation-wheel-20260929
/tmp/opencode/diavisuals-preparation-sdist-20260929
```

Each has `installed-mcp-factory.yml`, direct SVGs, the native receipt and these
complete retained bundles. The two installations produced the same bundle hashes:

| Consumer-relative bundle | SHA-256 of `bundle.json` |
| --- | --- |
| `.diavisuals/artifacts/published-mermaid/bundle.json` | `884c981872bc833ab1a48fedff4dd5d9d3a4d8107bfb682655a2b587002cf923` |
| `.diavisuals/artifacts/published-plantuml/bundle.json` | `61fd87104b0df036b70b050dbf9987a57c0234ab687a82db6c6208ba6e6256ed` |
| `.diavisuals/artifacts/published-mcp/bundle.json` | `38a11aa044f75ca461fd55ef41b13a4a359b079b2ddf6dc2d9fca322c070a074` |

Unpublished session evidence under `.tmp/owner-preparation-20260929/`:

| File | SHA-256 |
| --- | --- |
| `verify-installed.py` | `d5ba18cf2494ad65bb3e8983856a7eaa4802353961fc146b8d91c24678e34ba8` |
| `diavisuals-preparation-wheel-20260929-evidence.json` | `c456a46c5328c0949d47dee372e542904781f834ad56e3f186808daff702c190` |
| `diavisuals-preparation-sdist-20260929-evidence.json` | `cea1a812c0bb83cd1c88975a9a92b8d7a94cd0521aba415bfc4379dc66fb9e94` |

These JSON files retain the dependency versions, CLI results, actual Docker
commands, MCP resource hashes, descriptor equality checks, archive verification
and bundle identities. They and the synthetic consumers are local test evidence,
not GitHub release assets. The hub should retain the required evidence in its
own coordinating session before temporary directories are retired.

## Tested compatibility bounds and pending H1 integration

| Dimension | Evidence-supported selection/bounds |
| --- | --- |
| Package and native descriptor | Exactly `0.4.0`, native descriptor schema 1. No package-version interval beyond that singleton was exercised. |
| Host Python | Observed points `3.10.20` and `3.12.3`. The declaration `>=3.10` is broader than this run; intermediate and newer versions are not inferred as tested. |
| Host/platform | Linux x86-64; Docker client/engine `27.2.0`, API `1.47`; uv `0.11.19`. The wheel's `py3-none-any` tag does not certify other operating systems or renderer architectures. |
| MCP / YAML dependency | Exactly `mcp==1.29.0`, `PyYAML==6.0.3`; stdio protocol negotiated `2025-11-25`. |
| Engine tuple | Mermaid CLI `11.16.0`, Puppeteer `25.9.0`, PlantUML `1.2026.1`, exact image ID above; family `benizar`. No engine interval beyond these pins was exercised. |
| Diagrams/formats | Fresh Mermaid flowchart and PlantUML sequence rendering; SVG, PNG, PDF; file/inline source; retained original/edited SVGs. Other packaged examples/gallery entries were audited, not freshly rerendered in this session. |
| Artifact contract | `v1-opt-in-leaf-diagram`, native and pinned central checks, relocation and replay. Legacy compatibility profiles remain record-only. |

H1 adoption remains pending its integrated contract: catalogue/distribution
discovery, accepted compatibility intervals versus exact selected versions,
binding the hashed wheel to archive/image identities, cold bootstrap planning,
verified update selection and installation/registration state. No speculative H1
fields were added to either manifest. Real TIG/TIGIT/Geodisseny upgrades and live
client switching remain separate consumer operations.
