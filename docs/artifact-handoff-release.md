# Artifact handoff v1: owner release and dependent-pin handoff

## Scope and identities

- Owner PR: [#10](https://github.com/dosquartsdedocs/diavisuals/pull/10), developed
  on `feat/artifact-handoff-v1` in the selected Diavisuals checkout.
- Inspected base: `70702b7705f0385b552176d3551b3acc4b3e5af1`.
- Prepared package/release target: **0.4.0 / v0.4.0**, currently unreleased.
- Tested producer-source snapshot (identical in checkout, wheel and sdist):
  `sha256:547e898d58fe8f66206c9345b30afc55fd268a17ec0e39e8e262a53f648741f7`.
  This is the retained source identity, not a published Git/package pin.
- Shared contract/schema/verifier/fixtures:
  `9167e3efb5968a64bb9100792163a179c1491860`; central merge
  `fc8745db950b04013c73eb49acf6781a26eb83f8`.
- Capability: `contracts.artifact_handoff: v1-opt-in-leaf-diagram`, identical
  checkout/package/CLI/MCP discovery. The four new tools are
  `initialize_artifact_export`, `export_diagram_bundle`, `check_diagram_bundle`
  and `recover_diagram_bundle`.
- Engine/style/profile inputs unchanged:
  `mermaid-11.16.0-plantuml-1.2026.1`, family `benizar`, image label
  `diavisuals/render:v0.3.0`. No gallery output changes are required.
- Local real-runtime proof used image ID
  `sha256:5a6887b372a0e1c386a7b54981d11ae1910215baeb6a12dfd0706b3e85ef0846`.
  Its inspected `RepoDigests` list was empty: this is **local test evidence**,
  not a published image pin for adoption.

The owner implementation is intentionally producer-only. Importers, native
receipt regeneration at final destinations, composite bundle assembly and
consumer reference transactions belong to their respective factories.

## Acceptance commands

Use an explicit read-only reference checkout. Tests extract the reviewed **Git
objects**, including schema/verifier/fixtures, into independent temporary
directories. They do not execute mutable sibling working files or depend on
that checkout in the installed runtime.

```bash
export DIAVISUALS_HANDOFF_REFERENCE=/absolute/my-scripts-factory
export DIAVISUALS_FACTORY_MANAGER=/absolute/my-scripts-factory/src/bash/mcp_factories/mcp-factory-manager.py
make lint tests tests-mcp
make mcp-build
make mcp-check
make mcp-smoke
make docker-test
make check
DIAVISUALS_DOCKER_SMOKE=1 make tests-install
git diff --check
```

Evidence includes both engines and both source modes, real SVG/PNG/PDF outputs,
selected original/reviewed SVGs, complete resource retention, central v1 byte
verification, removal of the original temporary job and relocation of an
independent final consumer. Both engines are also replayed from retained
source/style/tool bytes in new private staging after the original job is gone.
Failure tests cover malformed/incomplete bundles,
missing/changed inputs, external references, links, aliases, collisions, concurrent
edits, failed teardown, interrupted publication and idempotent recovery after
rename. Existing direct-output/project-check/provider-receipt behavior remains
in the full suite. Wheel and sdist tests run with the installed module, not a
source-path substitution, including real MCP and optional real Docker proofs.

### Recorded owner run — 2026-09-24

| Check | Result |
| --- | --- |
| `make lint tests tests-mcp` with both explicit reference environments | Passed: 108 host tests discovered, 102 passed and 6 runtime-gated; real stdio tests passed separately. |
| Pinned central artifact suite, executed inside the owner suite | Passed: 26 test methods with table-driven adversarial cases, from the reviewed Git objects. |
| `make mcp-build`, `make mcp-check`, `make check` | Passed. |
| `make mcp-smoke` / `make docker-test` | Passed: real stdio plus 4 Docker/runtime test methods, including both-engine source/format matrices, relocation and retained-resource replay. |
| Wheel installation, Python 3.10.20, real Docker enabled | Passed: 34 owner handoff tests plus installed init/project-check/factory/MCP checks. |
| Sdist installation, Python 3.10.20, real Docker enabled | Passed: the same 34 tests and installed lifecycle checks. |
| Existing optional real PlantUML workspace-include isolation test | Passed. |
| `git diff --check` | Passed. |

The normal host suite uses Python 3.12. Runtime-gated cases are exercised by the
explicit smoke targets and the separate existing isolation test. Both installed
environments emitted a non-failing Pydantic settings forward-reference warning
for MCP's `lifespan` annotation; protocol and render checks still passed.

The recorded run includes regression coverage for both PR review findings:
rehashed evidence cannot change the selected original or ordered edits, and
rehashed manifests cannot change the kind/ownership required by retained roles.

## Publication handoff

1. Review the owner diff and its tests. Record the approved owner issue/PR URL
   and immutable implementation commit in the central coordinator's tracking.
   Use the merged revision from PR #10; a branch name or local test wheel is
   not a released dependency. Package/runtime publication remains separate.
2. Obtain the QGIS pilot's reviewed findings before declaring coordinated rollout
   conformance. The supplied central handoff and available pilot checkout did
   not contain a completed reviewed pilot report at implementation time.
3. Publish the approved `v0.4.0` Git revision and the affected Diavisuals Python
   distributions using the owner's publication process. Record the full Git
   object ID and wheel/sdist SHA-256 values. Associate a released export's
   retained producer-source snapshot revision with these distributions.
4. Keep the unchanged engine image **if a published immutable artifact is
   available**. Record its registry digest and prove that a cold runtime produces
   bundles whose actual Docker image ID matches the release evidence. The local
   image ID above, a tag alone, and a sibling development checkout are insufficient
   adoption pins. If no published engine artifact exists, publish/approve that
   artifact first; rebuilding engines solely for this host feature is unnecessary.
5. Prepare the dependent owner PRs below against the published immutable package
   revision. Preserve every unrelated dependency and the full transitive
   `mcp_dependencies` closure. Do not remove older direct-render tools/resources
   while adding opt-in export capabilities.
6. Run each importer's own transaction/domain/native-provider acceptance against
   the released producer, then coordinate real content upgrades. Record the owner
   PRs, immutable revisions, checks and remaining blockers in `my-scripts-factory`
   through its coordinating session, not from simultaneous sibling edits.

## Dependent PR specifications

All three owners currently declare Diavisuals `v0.3.1` in their inspected
checkout. The package version becomes `0.4.0`, the display release `v0.4.0`, and
the install reference must bind the **published full commit** or hashed published
wheel. Record both the human release and resolved immutable revision; never mark
an unpublished candidate `released`.

### Diapora — `Adopt released Diavisuals v1 bundles`

- Update `mcp-factory.yml` and `src/diapora/factory/mcp-factory.yml`: the
  Diavisuals dependency release and the separate `diavisuals.release` field.
- Update `DEFAULT_DIAVISUALS_RELEASE` in `src/diapora/workspace.py`, generated
  scaffold baselines, dependency checks and version-specific tests together.
- Add the four bundle tools to required capabilities for the opt-in integration
  workflow; retain existing render tools and the unchanged compatibility/style.
- Keep workspace-root binding. Final slide-owned files are under `docs/slides`;
  integration paths must not duplicate that prefix. Keep the complete child
  bundle byte-for-byte and name the selected direct-child output in the parent.
- Acceptance: real presentation import/export, retire temporary jobs, relocate
  the final consumer and check slide references plus transitive provenance.

### Unaltraweb — `Pin Diavisuals v1 for opt-in figure integration`

- Update Diavisuals `uv_spec`, `version`, `release` and capability declarations
  in `mcp-factory.yml`, plus the Diavisuals entry in
  `src/unaltraweb_mcp/component-contract.json`. Update package-owned manifest/
  scaffold projections through the genuine owner generator/baselines.
- Preserve the separate **Vegavisuals** dependency and all of its pins and
  resources. This owner currently has both dependencies; upgrading Diavisuals
  must not shorten that closure.
- Update native receipt expected provider version/release with the genuine
  component contract. Keep `.unaltraweb/receipts/diavisuals.json` at its existing
  location and call `project_check` at final managed paths.
- Acceptance: independent web and manual/PDF consumers, original/edited/source
  retention, failed-import recovery, relocated archive, rendered HTML/PDF
  references and native checks. Content publication remains human-controlled.

### Unaltrepaper — `Adopt released Diavisuals artifact producer`

- Update the Diavisuals `uv_spec`, `version`, `release` and bundle capabilities
  in `mcp-factory.yml` and any owner-generated/package manifest equivalents.
- Retain the dependency's existing init/build semantics and the full dependency
  closure. Explicitly initialize bundle staging when the importer feature is
  enabled; registration alone neither creates paths nor invokes export.
- Keep `figures/` as mixed durable material and `sandbox/` as mixed intake.
  Retain whole child bundles outside disposable submission projections, preserve
  selected originals/edits and update manuscript references transactionally.
- Acceptance: real paper PDF after producer-job retirement/consumer relocation,
  collision protection and rollback/recovery, plus provider checks at final
  managed paths. Submission archives and round semantics stay owner-controlled.

## Coordinator record still required

Record the merged PR and its immutable revision in the central coordinator.
The remaining external gates are reviewed QGIS findings, published package/runtime
artifact evidence and the three dependent owner PRs. This handoff supplies the
exact API, paths, proposed release, unchanged engine contract, test procedure and pin-update scope without
claiming that those external publication/integration steps have happened.
