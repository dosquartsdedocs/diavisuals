# Opt-in diagram artifact handoff v1

Available in the **0.4.0 release target**, through the checkout CLI, installed
wheel/sdist and startup-bound MCP. This is a leaf producer for **one** Mermaid or
PlantUML product. The reviewed shared contract is `my-scripts-factory` revision
`9167e3efb5968a64bb9100792163a179c1491860`, integrated through merge
`fc8745db950b04013c73eb49acf6781a26eb83f8`. The central verifier is an explicit,
pinned test reference, never a runtime dependency.

## Enable and export

Use the explicit absolute consumer checkout root. File paths are normalized
workspace-relative POSIX paths. The MCP always uses its startup root, including
when the server's working directory is the factory.

```bash
diavisuals --project /absolute/consumer init --artifact-export
diavisuals --project /absolute/consumer export-diagram-bundle \
  --input assets/diagrams/process.mmd --bundle-id process
diavisuals --project /absolute/consumer export-diagram-bundle \
  --text $'@startuml\nAlice -> Bob : Handoff\n@enduml\n' \
  --bundle-id sequence --format pdf
```

`export-diagram-bundle` also enables the feature when needed. Its source is
exactly one of `--input`, `--text`, or `--stdin`. File and inline UTF-8 bytes are
retained **without whitespace/newline normalization** and are the exact bytes
sent to private renderer staging. `--engine auto|mermaid|plantuml`, `--family`,
`--style`, `--profile` and `--format svg|png|pdf` select effective render options.
`--dry-run` validates the request without initializing, rendering or publishing.
Omitting `--bundle-id` generates a unique name; explicit IDs follow
`[a-z][a-z0-9._-]{0,79}` and the v1 reserved-name rules.

MCP tools use the same implementation:

| Tool | Arguments |
| --- | --- |
| `initialize_artifact_export` | none |
| `export_diagram_bundle` | exactly one of `input_path` / `diagram_text`; optional `bundle_id`, `engine`, `family`, `style`, `profile`, `output_format`, `original_path`, `edited_paths`, `dry_run` |
| `check_diagram_bundle` | `path`, sender's `sha256` |
| `recover_diagram_bundle` | exact staging manifest `path`, sender's `sha256`, new `bundle_id` |

Success returns:

```json
{
  "ok": true,
  "bundle": {
    "path": ".diavisuals/artifacts/process/bundle.json",
    "sha256": "<64 lowercase hex characters over exact manifest bytes>"
  }
}
```

The manifest has no self-hash. It contains only v1 fields, declares every retained
payload with ID/kind/role/ownership/SHA-256/size, and has an empty `dependencies`
array. This adapter does not accept composite bundle inputs. Sources or selected
SVGs beneath an existing artifact `bundle.json` are explicitly rejected, so their
upstream provenance cannot be silently flattened. An integrator must retain that
whole child tree and declare the exact child output for a composite product.

## Retained product

```text
bundle.json
payload/request.json
payload/render/input/source.mmd                 # or source.puml
payload/render/styles/<engine>/<style>.*
payload/render/styles/<engine>/<style>/<overrides>
payload/render/tools/<every staged rendering tool>
payload/resources/<effective compatibility profile>.env
payload/producer/<actual Python package source files>
payload/producer/identity.json
payload/outputs/generated.svg                   # or .png / .pdf
payload/outputs/original.svg                    # when selected
payload/outputs/edited-1.svg                    # when selected
payload/render-evidence.json
```

All resources actually staged for the selected engine/style are retained,
including type overrides, the normalizer where used and the rendering scripts.
The complete style directory is kept conservatively; it is not pruned from a
short declared input list. Fonts, renderer binaries, browser, JVM and their
dependencies are in the **actual immutable Docker image ID used by the command**.
The compatibility profile's friendly tag is not used as the runtime revision.

`producer.revision` is `sha256:` of the exact retained `producer/identity.json`.
That document inventories exact Python module source bytes under the versioned
`diavisuals-python-sources-v1` identity profile. The same files produce the same
identity in checkout, wheel and sdist installations. It describes development
bytes truthfully as well as released package bytes; it does not mislabel a dirty
checkout with its old Git HEAD. The renderer has a separate immutable runtime
revision. Release evidence must associate the producer snapshot with the
published distribution and its Git revision; a digest alone is not publisher
authentication or proof of release availability.

Installed package managers such as `uv` may hardlink package assets to their
cache. Those factory-owned reads are bounded and snapshotted, then materialized
as independent payload files. Consumer inputs and sealed bundles reject
hardlinks. An on-disk package upgrade during a long-running MCP session requires
a restart before export, so retained code cannot silently describe a different
version from the loaded producer.

The request stores effective options and **bundle-relative** source/resource/
output references. Original consumer filenames are informational origin metadata,
not dependencies needed after relocation. Render evidence records the input
hash, image ID, successful execution and verified teardown, network/mount
boundary and explicit original/edit selection. Checkers treat scripts and
requests as data; they never execute retained code.

### Reviewed edits and originals

```bash
diavisuals --project /absolute/consumer export-diagram-bundle \
  --input assets/process.mmd --bundle-id process-reviewed \
  --original assets/process.mmd.svg \
  --edited assets/process.mmd.edited.svg
```

The selected existing original is preserved byte-for-byte and each selected
edited SVG is an author-owned output with `variant_of: original`. Up to 32
explicit variants can share that original. The selected original is also
author-controlled material: the producer does not claim to have freshly created
it. The new render is a separate producer-owned output. This avoids equating an
old original with a new render whose SVG IDs or layout might differ. Selection
must be explicit, with both original and edits; there is no inferred filename
ownership or automatic replacement. SVG edits/originals may accompany any of
the three generated output formats.

## Supported dependency profile

Sources are self-contained Mermaid or one supported PlantUML product
(`uml`, `json`, `yaml`, `gantt`, `salt`, `files`, `wbs`, `mindmap`). Export rejects
external or implicit dependencies rather than sealing a lossy bundle:

- PlantUML includes/themes/preprocessor directives, user functions, sprites,
  images, other product languages and linked content are unsupported. The
  package style's exact `%version()` fallback is checked and retained.
- Mermaid source configuration/front matter, click actions, images/icons,
  embedded HTML beyond simple formatting, linked content and CSS/URL references
  are unsupported. Use the retained package style for effective configuration.
- SVGs must be UTF-8 XML, with existing local fragment references or embedded
  PNG/JPEG data. External files/URLs, unresolved fragment IDs, entities, active
  content and indirect/obfuscated CSS resource loading are rejected. Basic
  formatting in generated XHTML labels and PlantUML's inert numeric-version
  and encoded-source metadata processing instructions remain supported.

These deliberately conservative checks can reject a literal label containing
dependency-like syntax. Direct-output rendering keeps its existing behavior.
Supporting another dependency mechanism requires a versioned complete-input
adapter and domain tests; adding a caller-supplied inventory is insufficient.

`check-diagram-bundle PATH --sha256 HASH` verifies the exact manifest, every file,
the complete tree, revisions, original/variant relationships, effective request,
required resource layout and source/SVG references. It also works on a relocated
bundle anywhere inside the explicit receiving workspace. This is a **Diavisuals
leaf-profile check**, not a general importer or composite-v1 verifier. It does
not require Docker, Git, the original job or its source files.

The adapter follows v1 NFC paths, case-alias/collision checks, 1 MiB manifests,
bounded JSON, no symlinks/hardlinks/special files and no-follow workspace ancestor
access. The narrower owner limits are 4 MiB source, 64 MiB per retained file and
256 MiB per diagram product, within v1's 2 GiB cumulative read and 10,000-entry
limits. There are no empty or undeclared directories in a sealed bundle.

## Initialization, publication and recovery

`.diavisuals/artifacts` has `git: consumer`, `cleanup: explicit`. Adding this
policy does **not** make an absent opt-in path an ignored-path obligation for
existing consumers. Plain `init` continues to create only the regular cache.

Explicit enablement creates the confined `.diavisuals/artifacts/.staging` area
and a narrow `/.staging/` rule in `.diavisuals/artifacts/.gitignore`. Existing
customizations are retained; updates compare against the inspected bytes before
replacement. Git consumers are checked for effective ignore coverage and
already tracked recovery files. Conflicting rules/unsafe files fail with their
bytes preserved. Durable bundles and authored sources are outside the ignored
work area; their Git treatment remains the consumer's choice. Review the ignore
file together with retained bundles.

Export holds an owner coordination lock, snapshots source/edit bytes, renders
using private temporary mounts **outside the consumer**, without networking,
and verifies teardown before sealing. Staged input/resources are rechecked
against retained bytes. It then verifies the sealed host-side tree and uses
Linux `renameat2(RENAME_NOREPLACE)` for a single atomic directory publication.
Existing files/directories, even empty or identical ones, are never replaced.
Concurrent changes cause failure. There is no simultaneous direct-output write
or receipt update requiring a second transaction.

On failure, the result includes `recovery.path`, `recovery.sha256` (null until
sealed) and the intended `recovery.destination`. **Recovery jobs are retained**,
including exact inline inputs. A complete job can be republished explicitly:

```bash
diavisuals --project /absolute/consumer recover-diagram-bundle \
  .diavisuals/artifacts/.staging/job-EXACT_ID/bundle.json \
  --sha256 SENDER_HASH --bundle-id process-recovered
```

A crash after rename can leave a complete destination before acknowledgement.
Recovery with the original ID verifies that destination against the expected
hash and succeeds idempotently. A differing destination fails; choose a new ID
only when the staged job still exists. An incomplete job cannot be recovered as
a sealed product; preserve its source/request for a fresh export. Neither a
normal exception nor an interrupted process deletes recovery material.

No export/check/down operation deletes bundles. After an integrator has verified
its recoverable integration transaction and the runtime is stopped, a human or
future owner cleanup mechanism may explicitly retire the exact acknowledged job.
Registration metadata and `cleanup: explicit` are not deletion authorization.

## Integrator boundary and native receipts

The client/agent transports the returned **entire tree**, keeping manifest bytes
unchanged, into the receiving workspace. The integrator owns durable archive
layout, selected file mappings, reference updates, collision protection, its
transaction and the integration record. Preserve the original source, all edits,
originals, resources and evidence even when exposing only one SVG. For a composite
product, retain the whole child tree and identify the exact child output ID.

`.unaltraweb/receipts/diavisuals.json` retains its original `project_check`
contract and location. Export/check/recovery do not read, relocate, rewrite or
invalidate it. Once an integrator creates managed diagram paths, it must invoke
the genuine provider check at those final paths. The receipt is not a bundle or
an integration record.

See [release/pin handoff](artifact-handoff-release.md) for owner adoption and the
explicit pinned-reference and real-runtime acceptance commands.
