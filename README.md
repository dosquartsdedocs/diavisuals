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

En un projecte consumidor:

```bash
git submodule add git@github.com:dosquartsdedocs/diavisuals.git resources/diavisuals
```

Per preparar una font Mermaid estilitzada:

```bash
resources/diavisuals/tools/style-diagram-source.sh \
  mermaid benizar-mermaid \
  figures/pipeline.mmd \
  .cache/figures/pipeline.styled.mmd
```

I per renderitzar-la:

```bash
mmdc \
  -i .cache/figures/pipeline.styled.mmd \
  -o figures/pipeline.pdf \
  -c resources/diavisuals/styles/mermaid/benizar-mermaid.json
```

Per PlantUML:

```bash
resources/diavisuals/tools/style-diagram-source.sh \
  plantuml benizar-plantuml \
  figures/architecture.puml \
  .cache/figures/architecture.styled.puml
plantuml -tpdf .cache/figures/architecture.styled.puml
```

Consulta `docs/integration.md` per a la decisio d'us en `unaltrepaper`, `unaltraweb` i `my-slides-vault`.

## Compatibilitat

Aquest repo no renderitza documents sencers. Nomes proveeix assets d'estil, exemples i comprovacions. Els consumidors son els projectes que tenen els filtres o plantilles:

- `my-slides-vault`: diapositives i filtres Lua.
- `unaltrepaper`: papers, submissio, revisions i latexdiff.
- `unaltrepaperalpap`: paper de demo.
- `unaltraweb`: manuals i webs que poden prerenderitzar `.mmd` a `.svg`.

## Comprovacions

```bash
make check
```

Opcionalment, si tens `mmdc` i `plantuml` instal.lats:

```bash
make render-examples
```
