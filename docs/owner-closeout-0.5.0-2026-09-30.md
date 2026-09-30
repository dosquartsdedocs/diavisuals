# Diavisuals 0.5.0 closeout — 2026-09-30

## Delivered state

**v0.5.0 is published and its downloaded wheel/sdist have passed cold installed
acceptance.** This closes the control-plane increment. The previous development
reports remain historical evidence, not the source of the final artifact pins.

- Owner workspace: `/home/benizar/git/diavisuals`; one primary checkout.
- Release source revision and peeled tag:
  **`66cd500e5df4682e0642ecff249b28b08de14566`**, integrated on `main`.
- [Implementation/release PR #12](https://github.com/dosquartsdedocs/diavisuals/pull/12),
  merged `2026-09-30T20:22:50Z`, includes:
  - `dc5a07835e7b4d81051b6933399cf6d7ea010dcd` — native selector and final 0.5.0.
  - `c20197af52e69df93262eff34603bcb033608c77` — exact approved audit exception.
- [Published v0.5.0](https://github.com/dosquartsdedocs/diavisuals/releases/tag/v0.5.0),
  published `2026-09-30T20:33:10Z`.
- Source diff was empty when the final artifacts/gates/receipts were produced.
  This documentation-only handoff follows the release; its integration does not
  move `v0.5.0` or replace any released asset. Use the release revision above,
  rather than a later mutable `main`, when reproducing package bytes.

The owner explicitly authorized commit/push/PR, merge after required checks and
resolved conversations, and tag/publication/download verification. Session
preflight initially found the known prior work on protected `main` and no other
active session; that work was preserved on `release/v0.5.0`. The clean short-branch
preflight subsequently passed. Git and shared-runtime operations were serial;
no worktrees, consumer migrations or global registration changes were used.

## Review findings and resolutions

1. **Malformed CLI selection could leave an old successful provider receipt.**
   CLI failure now invalidates that confined receipt even when parsing fails
   before `project-check` starts; regressions require no Docker call.
2. **RepoDigest evidence accepted membership-bearing non-list values.**
   The resolver now requires a list of strings and exact local membership.
3. **Inline provenance used a logical cache input name as a real source path.**
   A recorded source kind distinguishes file/inline input; project freshness
   accepts inline output only when its exact rendered source bytes match the
   project source. Changed content fails even with backdated mtimes.
4. **A newly published npm advisory blocked the first PR CI run.**
   The owner's scoped decision below was implemented, tested and recorded in the
   PR and receipts. It was not silently bypassed.

The agent reviewed the implementation and regressions; all required branch
checks passed and there were no unresolved review threads. Copilot's requested
review could not run because of its quota, and is not represented as a successful
independent review. Branch protection required the four CI jobs and resolved
conversations; no admin bypass was used.

Implementation paths are `src/diavisuals/{runtime,registry,cli,mcp_server,artifacts}.py`;
version/discovery changes are in `__init__.py`, `pyproject.toml`, `uv.lock` and both
native manifests. Tests, Make gates, gallery launcher and release CI were updated.
The audit gate is `tools/check-renderer-audit.py` with dedicated regressions.
The preparation reports, interface guide, MCP/release documentation and changelog
were integrated with the source PR. No files under `compat/`, `styles/` or
`docker/` changed from v0.4.0, nor did the per-diagram rendering tools.

## Published hashes

All seven assets were freshly downloaded to
`.tmp/closeout-0.5.0/downloaded/`, checked against `SHA256SUMS`, and independently
compared with the sealed local sender bytes. These are the **published final
bytes**, not the earlier dev0 or pre-audit candidates.

| Asset | Bytes | SHA-256 |
| --- | ---: | --- |
| `diavisuals-0.5.0-py3-none-any.whl` | 530475 | `f52e20f20f1fb3a2418f07adb8d6a68a5567d0c321fb7c0ccc0f4db04917b96b` |
| `diavisuals-0.5.0.tar.gz` | 523336 | `a1519b3a9006ccff274279ca830963ab7219ab71a28a18133c47f7cf8ab4dc9b` |
| `mcp-factory-package.yml` | 3690 | `3762a58204d908bb95a63cbb13d6bcc62c8655a2e4af7a59721bd476226cf217` |
| `acceptance.json` | 10229 | `df2d51d28ef28e15c812457958860f4d877944c113e1025bfbed5e146768c746` |
| `release.json` | 3841 | `d3da4a0756ba39ed9d03bfe2fcc504b5dc2cd95aeed648ff2a7be5475460be64` |
| `diavisuals-render-v0.3.0-linux-amd64.tar.gz` | 1014844791 | `de5d98d6bcff2f427e2ce83db6e7a14edaf6963d199483cb68674ab43d3d75e4` |
| `SHA256SUMS` | 551 | `5c58e9fe8103fc174c2633a9a8ec883aef58dc1f827bcbc7a79c63820cde129e` |

`release.json` is the delivery manifest; `acceptance.json` is the final-artifact
acceptance receipt. Both bind the reviewed source and exact runtime. The native
descriptor's bytes match `diavisuals/assets/mcp-factory.yml` in both installed
distributions. Retained producer-source identity:
`sha256:8299d1a1a4dbb31bc39c467ddbdba2f612f42a7cb204a57961e12bd034d37479`.

The successful synthetic native project receipt has SHA-256
`3faa23da8e8743cb157ccb47e41f598319d913c1e63be4729b1349f2b857171f`
in each final source/wheel/sdist proof. Its v1 request format is unchanged;
runtime-specific evidence is held in the native render records and bundles.

Download comparison record:
`.tmp/closeout-0.5.0/download-verification.json`, SHA-256
`4b7f9d54b1a1adc0ae9b16861bcd558255d6a098d17f632087c15fe0b65f7340`.

## Reused renderer and exact audit decision

- Actual image ID:
  `sha256:5a6887b372a0e1c386a7b54981d11ae1910215baeb6a12dfd0706b3e85ef0846`.
- Alias `diavisuals/render:v0.3.0`; platform Linux/amd64; no registry RepoDigest.
- Archive bytes/hash are exactly those published with v0.4.0. Local acceptance
  reused the matching image; cold CI loaded the verified archive on fresh runners.
- Profile `mermaid-11.16.0-plantuml-1.2026.1`, family `benizar`, unchanged profile
  SHA-256 `3d4e0ec5d3d646e68e14a9c549c338d11feb34b29d11e95b75b9f8c5fd2739ef`.

**Known exception:** [GHSA-p98j-92pf-mc4p](https://github.com/advisories/GHSA-p98j-92pf-mc4p),
low severity, DOMPurify 3.4.14. It requires a live-node `IN_PLACE` sanitization
with a node-removing afterSanitize hook; the inspected Mermaid paths sanitize
strings and use an attribute-only hook. The owner explicitly accepted the
[exact-image/lock exception](renderer-audit-exception-2026-09-30.md), also recorded
in both published receipts and the release notes. DOMPurify is **not claimed
patched**. Every other finding, changed severity/title/scope, changed image/lock
or audit error still blocks CI. This decision does not extend to arbitrary images
or DOMPurify applications; a patched renderer is a separate future delivery.

## CI and final acceptance

| Evidence | Result |
| --- | --- |
| [First PR CI 36769117412](https://github.com/dosquartsdedocs/diavisuals/actions/runs/36769117412) | Failed on the newly published low DOMPurify advisory; retained as a failed attempt. |
| [Final PR CI 36771738503](https://github.com/dosquartsdedocs/diavisuals/actions/runs/36771738503) | All required jobs passed: Python 3.10, Python 3.12, package, Docker (including scoped audit and gallery parity). |
| [Integrated-main CI 36772212661](https://github.com/dosquartsdedocs/diavisuals/actions/runs/36772212661) | Passed at the release-producing revision. |
| [Tag CI 36773156734](https://github.com/dosquartsdedocs/diavisuals/actions/runs/36773156734) | Passed for v0.5.0. |
| [Published-artifact CI 36773432804](https://github.com/dosquartsdedocs/diavisuals/actions/runs/36773432804) | **Both wheel and sdist passed**, including fresh downloads/checksums, cold archive load, non-editable installation, real stdio and same-daemon A/B/bundle tests. |

Final local gates ran from the clean integrated revision:

```bash
DIAVISUALS_HANDOFF_REFERENCE=/home/benizar/git/gacontext \
DIAVISUALS_FACTORY_MANAGER=/home/benizar/git/gacontext/src/bash/mcp_factories/mcp-factory-manager.py \
DIAVISUALS_SELECTION_EVIDENCE=/home/benizar/git/diavisuals/.tmp/closeout-0.5.0/final/selections \
  make lint tests tests-mcp mcp-build mcp-check docker-test mcp-smoke

DIAVISUALS_HANDOFF_REFERENCE=/home/benizar/git/gacontext \
DIAVISUALS_FACTORY_MANAGER=/home/benizar/git/gacontext/src/bash/mcp_factories/mcp-factory-manager.py \
DIAVISUALS_SELECTION_EVIDENCE=/home/benizar/git/diavisuals/.tmp/closeout-0.5.0/final/selections \
DIAVISUALS_DOCKER_SMOKE=1 make tests-install

DIAVISUALS_MCP_SMOKE=1 .venv/bin/python -m unittest \
  tests.test_registry.RegistryTest.test_plantuml_renderer_blocks_workspace_includes_when_enabled
git diff --check
git diff --exit-code v0.4.0 -- compat styles docker tools/render-one.sh \
  tools/style-diagram-source.sh tools/resolve-style-name.sh tools/normalize-mermaid-svg.py
```

- Host: **124 discovered, 117 passed, 7 runtime-gated**; explicit stdio and five
  Docker tests passed; include-denial passed separately. Gate counts overlap.
- Final wheel and sdist: **47 tests passed per non-editable installation** on
  Python 3.10.20, with real Docker enabled. Both distributions were rebuilt from
  the integrated revision before this final acceptance.
- Source host: Python 3.12.3; Docker 27.2.0; MCP 1.29.0; PyYAML 6.0.3.
- Both engines exercised file/inline input, SVG/PNG/PDF, source/resource retention,
  originals/edits, relocation, retired jobs and retained-resource replay.
- Final installed 0.5.0 reverified the retained 0.4.0 Mermaid/PlantUML bundles.
  Historical integrity verification does not inspect or require a producing image.
- The existing non-failing Pydantic `lifespan` warning appeared in installed
  environments; protocol and rendering assertions passed.

Logs and checksummed gate index remain at `.tmp/closeout-0.5.0/final/`.
`gates.json` SHA-256:
`ee4c17fb4b2b89d4394f425d8c2337eeadc3a7e298608ab2618a2b2a6cee5b52`.

## A/B evidence and limits

The tests use Docker directly, without an alias-mapping wrapper. B is an untagged,
configuration-only derivative of A's renderer rootfs. Distinct startup-bound MCP
sessions use both actual IDs on the same daemon; A → B → A cache paths, explicit
errors, freshness failures and retained runtime provenance are checked. Active
aliases/profile bytes remain unchanged. Exact test containers/B images are retired.
This proves isolated identity selection, **not a second engine version**.

Final non-editable wheel evidence:
`.tmp/closeout-0.5.0/final/selections/8930be3cdee245499aa57871ddd8c737/evidence.json`,
SHA-256 `d82e0d3aae6f400c0bf450b6402a6e56db9227c50a4d52034ff8dbf5d6a904c2`.
Its B image was
`sha256:8402ba931d526f77da02216e576da9a51f8f7f80fc6dd28c4e745832b3dca580`.
The sibling `consumer/` retains the native receipt, sources, SVGs, render records
and four complete bundles; `acceptance.json` gives all their hashes and the
equivalent source/sdist proof locations. Local evidence is distinct from the
published receipt that records its identities.

Tested engine tuple: Mermaid CLI 11.16.0, Mermaid library 11.17.2, Puppeteer 25.9.0,
PlantUML 1.2026.1, family `benizar`, Linux/amd64. RepoDigest comparison has
deterministic regressions, but live registry-digest acquisition was not exercised
for this archive-based renderer. No broader package/Python/engine/architecture
interval is inferred from the observed points.

## Native interface returned to H2

Hashed published install reference:

```text
diavisuals[mcp] @ https://github.com/dosquartsdedocs/diavisuals/releases/download/v0.5.0/diavisuals-0.5.0-py3-none-any.whl#sha256=f52e20f20f1fb3a2418f07adb8d6a68a5567d0c321fb7c0ccc0f4db04917b96b
```

After independently verifying/preparing the selected image:

```bash
export DIAVISUALS_RUNTIME_IMAGE=sha256:5a6887b372a0e1c386a7b54981d11ae1910215baeb6a12dfd0706b3e85ef0846
diavisuals ensure-renderer
diavisuals renderer-status
MCP_CONSUMER_WORKSPACE=/absolute/consumer diavisuals mcp serve
```

Global CLI `--runtime-image` / `--runtime-expected-id` precede the subcommand.
Full IDs identify themselves; aliases require the expected full ID; repository
digests must be locally verified, with optional expected image ID. Argument pairs
replace environment pairs atomically. Explicit absence/incoherence fails without
build/pull/load/retag/default fallback. See [the native guide](runtime-selection.md).

**Provider delivery is complete.** H1/H2 catalogue/acquisition/activation mapping
remains the hub's work. Coordinators pinned to helper 0.4.0 must explicitly accept
and test their own 0.5.0 adoption. Their pins, manuals, user data and registrations
were not changed. The hub is read-only context in this owner session; this report
and the published receipts are the return packet for its coordinator.
