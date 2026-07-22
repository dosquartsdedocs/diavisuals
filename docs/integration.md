# Project Integration

`diavisuals` is not a document build system. It is a style package plus small helpers for preparing diagram sources. Each consumer keeps its own pipeline and decides when to call `mmdc`, `plantuml`, Jekyll, Pandoc, or LaTeX.

## Architecture Decision

- `diavisuals` publishes tokens, presets, type overrides, examples, compatibility profiles, and rendered galleries.
- `diavisuals` can transform a `.mmd` or `.puml` source into a styled source with `tools/style-diagram-source.sh`.
- `unaltrepaper`, `unaltraweb`, `my-slides-vault`, and other projects render with their own tools.
- Documentation repositories should not copy local CSS or `skinparam` fragments when the preset already lives here.

This keeps `diavisuals` from knowing too much about LaTeX, Jekyll, or Beamer, while still giving consumers a simple contract: shared style, local rendering, declared compatibility profile.

Consumers should pin a short `diavisuals` release tag such as `v0.1.2` and declare which compatibility profile they render, for example `mermaid-11.4.2-plantuml-1.2026.1`. The profile does not replace the local pipeline; it only states which engine versions and diagram types have been visually checked.

## Recommended Installation

For dosquartsdedocs projects, prefer a vendored package copy. The consumer
factory should copy `styles/`, `compat/`, and `tokens/` from the installed
`diavisuals` package or checkout into its own resource tree and record:

```yaml
diavisuals:
  path: resources/diavisuals
  source: package
  release: v0.1.2
  compatibility: mermaid-11.4.2-plantuml-1.2026.1
diagram_styles:
  family: benizar
```

If a project already expects `res/styles/mermaid` and `res/styles/plantuml`, expose the assets with:

```bash
./resources/diavisuals/tools/install-to-project.sh . link
```

Use `copy` only when the project cannot use symlinks.

Submodules remain an explicit opt-in for repositories that want Git to own the
style checkout:

```bash
diavisuals submodule-plan --path resources/diavisuals
```

## Common Helper

For Mermaid, normally pass the family name:

```bash
resources/diavisuals/tools/style-diagram-source.sh \
  mermaid benizar \
  assets/diagrams/pipeline.mmd \
  .cache/diagrams/pipeline.styled.mmd

mmdc \
  -i .cache/diagrams/pipeline.styled.mmd \
  -o assets/diagrams/pipeline.mmd.svg \
  -c resources/diavisuals/styles/mermaid/benizar-mermaid.json
```

For PlantUML:

```bash
resources/diavisuals/tools/style-diagram-source.sh \
  plantuml benizar \
  figures/architecture.puml \
  .cache/diagrams/architecture.styled.puml

plantuml -tsvg .cache/diagrams/architecture.styled.puml
```

The helper resolves a family (`benizar`) to the engine-specific style name (`benizar-mermaid` or `benizar-plantuml`), detects the diagram type, and applies the matching override when it exists.

## my-slides-vault

`my-slides-vault` is the reference consumer for the `v0.1.2` release target and its modern profile `mermaid-11.4.2-plantuml-1.2026.1`. It already implements the style contract in Lua filters:

```yaml
diagram_styles:
  mermaid: benizar-mermaid
  plantuml: benizar-plantuml
```

Migration can happen in two steps:

1. Run `my-slides-vault init` to vendor `diavisuals` under `docs/slides/resources/diavisuals`.
2. Keep `diagram_styles.family: benizar` unless the deck intentionally chooses another family.

The Lua filters should stay in `my-slides-vault`; they are part of the slide build pipeline.

## unaltrepaper

`unaltrepaper` owns the paper support layer: Docker, Makefile targets, figures, submission bundles, diffs, and journal templates. `diavisuals` should enter as a shared style resource, not as duplicated code inside each paper.

Recommended paper layout:

```text
resources/unaltrepaper/       # paper factory
resources/diavisuals/         # vendored shared style assets
figures/                      # paper SVG, Mermaid, and PlantUML sources
```

Recommended build behavior in `unaltrepaper/scripts/build-figures.sh`:

- Accept `DIAVISUALS_DIR`, defaulting to `/workspace/resources/diavisuals` when present.
- Accept `DIAGRAM_STYLE_FAMILY`, defaulting to `benizar`.
- Accept `MERMAID_STYLE` and `PLANTUML_STYLE` as optional per-engine overrides.
- Before `mmdc`, generate a `.cache/*.styled.mmd` file with `style-diagram-source.sh` and use the matching JSON preset with `--configFile`.
- Before `plantuml`, generate a `.cache/*.styled.puml` file with the same helper.

This lets `unaltrepaperalpap` demonstrate diagrams while keeping build logic in `unaltrepaper` and style logic in `diavisuals`.

## unaltraweb

`unaltraweb` already has a plugin that rewrites `.mmd` references to `.mmd.svg` when the generated SVG exists. The best initial fit is build-time rendering, not browser-time rendering.

Recommended flow:

```text
assets/diagrams/manual-flow.mmd          # editable source
assets/diagrams/manual-flow.mmd.svg      # generated SVG with diavisuals
```

The core or template of `unaltraweb` should add a target such as `make diagrams` that runs `style-diagram-source.sh`, then calls `mmdc` or `plantuml` with the profile supported by that web project.

Inline ```mermaid``` blocks rendered in the browser can keep using the current dynamic website theme. `diavisuals` should apply first to versioned diagram sources such as `.mmd` and `.puml`, because those are reproducible and fit the existing plugin.

## Other Projects

Any project can consume the repository in two ways:

- Directly, by calling `style-diagram-source.sh` and the relevant render engine.
- By copying or symlinking `styles/` to the location where its pipeline already expects presets.

The rule is always the same: centralized style, local rendering, explicit compatibility profile.
