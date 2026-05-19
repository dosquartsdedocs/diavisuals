# diavisuals

`diavisuals` centralitza els estils visuals de diagrames de dosquartsdedocs. La idea es deixar de copiar petits ajustos de Mermaid i PlantUML dins de cada projecte i tenir un contracte compartit per a diapositives, papers, webs i documentacio tecnica.

El primer estil complet es `benizar`, basat en el treball existent de `my-slides-vault`.

## Que hi ha

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
docs/
examples/
tools/
```

El repositori guarda dues capes:

- Un preset base per motor: `benizar-mermaid.json` i `benizar-plantuml.puml`.
- Overrides petits per tipus de diagrama: `quadrantchart`, `block`, `treemap`, `sequence`, `class`, `state`, etc.

Aquesta separacio es important: un diagrama de quadrants no necessita la mateixa gramatica visual que un sequence diagram o un treemap.

## Us rapid

En un projecte que ja use els filtres de `my-slides-vault` o un contracte compatible:

```bash
git submodule add <url-del-repo-diavisuals> resources/diavisuals
./resources/diavisuals/tools/install-to-project.sh . link
```

Despres, en metadades:

```yaml
diagram_styles:
  mermaid: benizar-mermaid
  plantuml: benizar-plantuml
```

I en un diagrama concret:

```markdown
![Pipeline](mermaid/pipeline.mmd){width=90% diagram_style=benizar-mermaid}
![Pipeline UML](plantuml/pipeline.puml){width=90% diagram_style=benizar-plantuml}
```

`diagram_style` es l'alias compartit. Tambe funcionen `mermaid_style` i `plantuml_style` en els filtres que venen de `my-slides-vault`.

## Compatibilitat

Aquest repo no renderitza documents sencers. Nomes proveeix assets d'estil, exemples i comprovacions. Els consumidors son els projectes que tenen els filtres o plantilles:

- `my-slides-vault`: consumeix `res/styles/mermaid` i `res/styles/plantuml`.
- `unaltrepaper`: hauria de consumir aquests assets des de la plantilla o els seus recursos compartits.
- `unaltrepaperalpap`: paper de demo; hauria de demostrar l'us, no ser el lloc on viuen els estils.
- `unaltraweb`: pot passar el JSON a `mmdc` i incloure snippets PlantUML en el seu pipeline.

Consulta `docs/integration.md` per a detalls.

## Comprovacions

```bash
make check
```

Opcionalment, si tens `mmdc` i `plantuml` instal.lats:

```bash
make render-examples
```
