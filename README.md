# diavisuals

![release](https://img.shields.io/badge/release-v0.1.0-blue) ![Mermaid CLI](https://img.shields.io/badge/Mermaid_CLI-11.4.2-ff3670) ![PlantUML](https://img.shields.io/badge/PlantUML-1.2026.1-2a5db0) ![family](https://img.shields.io/badge/family-benizar-2a5db0)

`diavisuals` centralizes shared Mermaid and PlantUML visual styles for dosquartsdedocs projects. The goal is to stop copying one-off CSS and `skinparam` fragments into each paper, website, or slide deck, and to keep one tested contract for technical diagrams.

The first complete family is `benizar`, extracted from the previous `my-slides-vault` work. The repository is prepared for additional families such as `tonidomo` or `urv`, following the `<family>-mermaid` and `<family>-plantuml` naming convention.

## Contents

```text
styles/
  mermaid/
    benizar-mermaid.json
    benizar-mermaid/<diagram-type>.mmd
  plantuml/
    benizar-plantuml.puml
    benizar-plantuml/<diagram-type>.puml
tokens/
  benizar.yml
compat/
docs/
examples/
tools/
```

The repository has two style layers:

- One engine-level preset: `benizar-mermaid.json` and `benizar-plantuml.puml`.
- Small per-diagram-type overrides: `quadrantchart`, `block`, `treemap`, `sequence`, `class`, `state`, and so on.

That split matters because a quadrant chart, a sequence diagram, and a treemap need different visual decisions.

## Quick Use

In a consumer project:

```bash
git submodule add git@github.com:dosquartsdedocs/diavisuals.git resources/diavisuals
```

Prepare a styled Mermaid source:

```bash
resources/diavisuals/tools/style-diagram-source.sh \
  mermaid benizar \
  figures/pipeline.mmd \
  .cache/figures/pipeline.styled.mmd
```

Render it:

```bash
mmdc \
  -i .cache/figures/pipeline.styled.mmd \
  -o figures/pipeline.svg \
  -c resources/diavisuals/styles/mermaid/benizar-mermaid.json
```

For PlantUML:

```bash
resources/diavisuals/tools/style-diagram-source.sh \
  plantuml benizar \
  figures/architecture.puml \
  .cache/figures/architecture.styled.puml
plantuml -tsvg .cache/figures/architecture.styled.puml
```

See `docs/integration.md` for how `unaltrepaper`, `unaltraweb`, and `my-slides-vault` should consume the package, `docs/style-families.md` for the family contract, and `docs/style-contract.md` for the engine style contract.

## Rendered Gallery

The default gallery is generated for the current release target `v0.1.0`. That short release tag points to the compatibility profile `mermaid-11.4.2-plantuml-1.2026.1`: Mermaid CLI 11.4.2 and PlantUML 1.2026.1, matching the modern diagram support used by `my-slides-vault`. The full manifest is [`docs/gallery/benizar/mermaid-11.4.2-plantuml-1.2026.1/manifest.csv`](docs/gallery/benizar/mermaid-11.4.2-plantuml-1.2026.1/manifest.csv).

README previews are generated as PNG thumbnails from the same examples as the full SVG gallery. This keeps labels stable in Markdown renderers that handle Mermaid SVG `foreignObject` text differently.

| Mermaid workflow | Mermaid board | Mermaid decision matrix |
| --- | --- | --- |
| <img src="docs/gallery/benizar/mermaid-11.4.2-plantuml-1.2026.1/readme/mermaid-flowchart.png" width="300"> | <img src="docs/gallery/benizar/mermaid-11.4.2-plantuml-1.2026.1/readme/mermaid-kanban.png" width="300"> | <img src="docs/gallery/benizar/mermaid-11.4.2-plantuml-1.2026.1/readme/mermaid-quadrantchart.png" width="300"> |

| PlantUML sequence | PlantUML files | PlantUML activity |
| --- | --- | --- |
| <img src="docs/gallery/benizar/mermaid-11.4.2-plantuml-1.2026.1/readme/plantuml-sequence.png" width="300"> | <img src="docs/gallery/benizar/mermaid-11.4.2-plantuml-1.2026.1/readme/plantuml-files.png" width="300"> | <img src="docs/gallery/benizar/mermaid-11.4.2-plantuml-1.2026.1/readme/plantuml-activity.png" width="300"> |

Regenerate the gallery with:

```bash
make render-gallery
```

The older `mermaid-10.9.1-plantuml-1.2020.02` profile remains available to document what the previous Ubuntu-package-based paper image rendered.

## Compatibility Profiles

Files under `compat/` define which Mermaid and PlantUML versions are part of a rendering guarantee. Child projects should pin a short SemVer tag such as `v0.1.0` and declare the compatibility profile they support. If a new engine version changes support for `block`, `kanban`, `treemap`, `@startfiles`, `@startjson`, or another diagram type, add a new profile instead of changing the meaning of an existing one.

See `docs/versioning.md` for the versioning policy, `docs/releases.md` for the release matrix, and `docs/supported-diagrams.md` for the diagram type map.

## Consumers

This repository does not build full documents. It provides style assets, examples, compatibility profiles, and rendering checks. Consumers own their local pipelines:

- `my-slides-vault`: slide decks and Lua filters.
- `unaltrepaper`: papers, submissions, revisions, and latexdiff outputs.
- `unaltrepaperalpap`: public paper demo.
- `unaltraweb`: manuals and websites that can pre-render `.mmd` or `.puml` files.

## Checks

```bash
make check
```

Render the default compatibility gallery through Docker:

```bash
make render-gallery
```

If Mermaid CLI and PlantUML are already installed locally, render examples without Docker:

```bash
make render-examples
```
