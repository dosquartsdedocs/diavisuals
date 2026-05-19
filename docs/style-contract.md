# Contracte d'estil

`diavisuals` publica fitxers en la mateixa forma que ja consumeixen els filtres de `my-slides-vault`.

## Mermaid

```text
styles/mermaid/<preset>.json
styles/mermaid/<preset>/<diagram-type>.mmd
```

Exemple:

```text
styles/mermaid/benizar-mermaid.json
styles/mermaid/benizar-mermaid/quadrantchart.mmd
```

El JSON es passa a `mmdc` com a configuracio base. El fitxer per tipus es un snippet Mermaid, normalment una directiva `%%{init: ...}%%`, que es prependeix al diagrama abans de renderitzar-lo.

## PlantUML

```text
styles/plantuml/<preset>.puml
styles/plantuml/<preset>/<diagram-type>.puml
```

Exemple:

```text
styles/plantuml/benizar-plantuml.puml
styles/plantuml/benizar-plantuml/sequence.puml
```

El preset base s'injecta despres de `@start...`. Si existeix un override per tipus, s'afegeix despres del preset base.

## Regla practica

- El preset base defineix font, colors principals, nodes, linies, notes i clusters.
- El fitxer de tipus nomes ajusta allo que eixe tipus necessita.
- Si un tipus encara no necessita cap ajust real, el fitxer pot ser minim, pero ha d'existir per fer visible el contracte i evitar nyaps locals.

## Noms normalitzats

Els consumidors haurien de normalitzar els tipus amb claus estables:

- Mermaid: `flowchart`, `sequence`, `class`, `state`, `er`, `gantt`, `journey`, `pie`, `gitgraph`, `quadrantchart`, `sankey`, `kanban`, `timeline`, `block`, `treemap`.
- PlantUML: `sequence`, `class`, `state`, `usecase`, `activity`, `component`, `deployment`, `object`, `mindmap`, `wbs`, `json`, `yaml`, `gantt`, `salt`, `files`.
