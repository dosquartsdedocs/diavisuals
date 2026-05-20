# Style Contract

`diavisuals` publishes files in the same shape expected by existing consumers such as `my-slides-vault`.

## Mermaid

```text
styles/mermaid/<preset>.json
styles/mermaid/<preset>/<diagram-type>.mmd
```

Example:

```text
styles/mermaid/benizar-mermaid.json
styles/mermaid/benizar-mermaid/quadrantchart.mmd
```

The JSON file is passed to `mmdc` as the base configuration. The per-type file is a Mermaid snippet, usually an `%%{init: ...}%%` directive, that is prepended to the diagram before rendering.

## PlantUML

```text
styles/plantuml/<preset>.puml
styles/plantuml/<preset>/<diagram-type>.puml
```

Example:

```text
styles/plantuml/benizar-plantuml.puml
styles/plantuml/benizar-plantuml/sequence.puml
```

The base preset is injected after `@start...`. When a type override exists, it is injected after the base preset.

## Practical Rule

- The base preset defines fonts, main colors, nodes, lines, notes, and clusters.
- The type file adjusts only what that type needs.
- If a type does not need a real adjustment yet, the file can stay minimal, but it should exist to make the contract visible and avoid local patches.

## Normalized Names

Consumers should normalize diagram types to stable keys:

- Mermaid: `flowchart`, `sequence`, `class`, `state`, `er`, `gantt`, `journey`, `pie`, `gitgraph`, `quadrantchart`, `sankey`, `kanban`, `timeline`, `block`, `treemap`.
- PlantUML: `sequence`, `class`, `state`, `usecase`, `activity`, `component`, `deployment`, `object`, `mindmap`, `wbs`, `json`, `yaml`, `gantt`, `salt`, `files`.
