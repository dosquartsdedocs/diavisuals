# diavisuals

`diavisuals` centralitza els estils visuals de diagrames de dosquartsdedocs. La idea es deixar de copiar petits ajustos de Mermaid i PlantUML dins de cada projecte i tenir un contracte compartit per a diapositives, papers, webs i documentacio tecnica.

El primer estil complet es `benizar`, basat en el treball existent de `my-slides-vault`. El repo esta preparat per a mes families, com `tonidomo` o `urv`, seguint la convencio `<familia>-mermaid` i `<familia>-plantuml`.

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

Consulta `docs/integration.md` per a la decisio d'us en `unaltrepaper`, `unaltraweb` i `my-slides-vault`, i `docs/style-families.md` per al contracte de families (`benizar`, `urv`, `tonidomo`, etc.).

## Galeria renderitzada

La galeria seguent es genera amb el perfil `mermaid-10.9.1-plantuml-1.2020.02`: Mermaid CLI 10.9.1 i PlantUML 1.2020.02. Aixo fa visible quins exemples renderitzen amb les versions que consumeix actualment el pipeline Docker de papers. El manifest complet esta en [`docs/gallery/benizar/mermaid-10.9.1-plantuml-1.2020.02/manifest.csv`](docs/gallery/benizar/mermaid-10.9.1-plantuml-1.2020.02/manifest.csv).

| Mermaid flowchart | Mermaid quadrant | Mermaid state |
| --- | --- | --- |
| <img src="docs/gallery/benizar/mermaid-10.9.1-plantuml-1.2020.02/mermaid/flowchart.svg" width="240"> | <img src="docs/gallery/benizar/mermaid-10.9.1-plantuml-1.2020.02/mermaid/quadrantchart.svg" width="240"> | <img src="docs/gallery/benizar/mermaid-10.9.1-plantuml-1.2020.02/mermaid/state.svg" width="240"> |

| PlantUML sequence | PlantUML class | PlantUML WBS |
| --- | --- | --- |
| <img src="docs/gallery/benizar/mermaid-10.9.1-plantuml-1.2020.02/plantuml/sequence.svg" width="240"> | <img src="docs/gallery/benizar/mermaid-10.9.1-plantuml-1.2020.02/plantuml/class.svg" width="240"> | <img src="docs/gallery/benizar/mermaid-10.9.1-plantuml-1.2020.02/plantuml/wbs.svg" width="240"> |

Regenera-la amb:

```bash
make render-gallery
```

## Perfils de compatibilitat

Els fitxers de `compat/` defineixen quines versions de Mermaid i PlantUML formen part d'una garantia de renderitzat. Els projectes fills poden fixar un commit o tag de `diavisuals` i declarar quin perfil suporten. Si una versio nova del motor afegeix `block`, `kanban`, `treemap`, `@startjson` o altres tipus, s'ha d'afegir un perfil nou en lloc de canviar el significat de l'anterior.

Consulta `docs/versioning.md` per a la politica de versions i `docs/supported-diagrams.md` per al mapa de tipus.

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
