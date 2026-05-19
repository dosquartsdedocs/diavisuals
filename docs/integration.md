# Integracio amb projectes

`diavisuals` no es un motor de build. Es un paquet d'estils i una eina petita per preparar fonts de diagrama. Cada consumidor conserva el seu pipeline i decideix quan cridar `mmdc`, `plantuml`, Jekyll, Pandoc o LaTeX.

## Decisio d'arquitectura

- `diavisuals` publica tokens, presets, overrides per tipus i exemples.
- `diavisuals` pot transformar una font `.mmd` o `.puml` en una font estilitzada amb `tools/style-diagram-source.sh`.
- `unaltrepaper`, `unaltraweb`, `my-slides-vault` i altres projectes renderitzen amb les seues eines pròpies.
- Els repos de documentacio no haurien de copiar fragments CSS o `skinparam` locals si el preset ja viu aci.

Aixo evita que `diavisuals` acabe sabent massa de LaTeX, Jekyll o Beamer, i manté un contracte simple: estil compartit, build local.

Els consumidors tambe haurien de declarar quin perfil de compatibilitat renderitzen, per exemple `mermaid-10.9.1-plantuml-1.2020.02`. El perfil no substitueix el pipeline local; nomes diu quines versions dels motors i quins tipus de diagrama estan comprovats visualment.

## Instal.lacio recomanada

Per a projectes de dosquartsdedocs, usa submodul:

```bash
git submodule add git@github.com:dosquartsdedocs/diavisuals.git resources/diavisuals
git submodule update --init --recursive
```

Si el projecte ja espera `res/styles/mermaid` i `res/styles/plantuml`, pots exposar els assets amb:

```bash
./resources/diavisuals/tools/install-to-project.sh . link
```

Usa `copy` nomes si el projecte no accepta symlinks.

## Helper comu

Per Mermaid, normalment passant la familia:

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

Per PlantUML:

```bash
resources/diavisuals/tools/style-diagram-source.sh \
  plantuml benizar \
  figures/architecture.puml \
  .cache/diagrams/architecture.styled.puml

plantuml -tsvg .cache/diagrams/architecture.styled.puml
```

El helper resol la familia (`benizar`) al nom intern de motor (`benizar-mermaid` o `benizar-plantuml`), detecta el tipus de diagrama i aplica l'override corresponent quan existeix.

## my-slides-vault

`my-slides-vault` ja implementa el contracte directament als filtres Lua:

```yaml
diagram_styles:
  mermaid: benizar-mermaid
  plantuml: benizar-plantuml
```

Per tant, pot migrar a `diavisuals` en dues fases:

1. Afegir `diavisuals` com a submodul.
2. Fer que `res/styles/mermaid` i `res/styles/plantuml` siguen symlinks o copies dels assets de `resources/diavisuals/styles`.

No cal moure els filtres Lua a `diavisuals`; els filtres son part del build de diapositives.

## unaltrepaper

`unaltrepaper` ha de ser el lloc on viu el suport de papers: Docker, Makefile, figures, submissio, diff i plantilles. `diavisuals` ha d'entrar com a recurs compartit, no com a codi duplicat dins de cada paper.

Contracte recomanat dins d'un paper:

```text
resources/unaltrepaper/       # factory del paper
resources/diavisuals/         # submodul compartit d'estils
figures/                      # fonts SVG, Mermaid, PlantUML del paper
```

Canvi recomanat en `unaltrepaper/scripts/build-figures.sh`:

- Acceptar `DIAVISUALS_DIR`, per defecte `/workspace/resources/diavisuals` si existeix.
- Acceptar `DIAGRAM_STYLE_FAMILY`, per defecte `benizar`.
- Acceptar `MERMAID_STYLE` i `PLANTUML_STYLE` com a overrides opcionals per motor.
- Abans de `mmdc`, generar un `.cache/*.styled.mmd` amb `style-diagram-source.sh` i usar el JSON del preset amb `--configFile`.
- Abans de `plantuml`, generar un `.cache/*.styled.puml` amb el mateix helper.

Aixi `unaltrepaperalpap` pot demostrar els diagrames, pero la logica compartida queda a `unaltrepaper` i l'estil queda a `diavisuals`.

## unaltraweb

`unaltraweb` ja té un plugin que reescriu referencies `.mmd` a `.mmd.svg` si el SVG generat existeix. Per tant, el millor encaix inicial es build-time, no browser-time.

Flux recomanat:

```text
assets/diagrams/manual-flow.mmd          # font editable
assets/diagrams/manual-flow.mmd.svg      # SVG generat amb diavisuals
```

El core o template d'`unaltraweb` hauria d'afegir un target, per exemple `make diagrams`, que faça:

```bash
for src in assets/diagrams/*.mmd; do
  name=$(basename "$src")
  resources/diavisuals/tools/style-diagram-source.sh \
    mermaid benizar-mermaid \
    "$src" \
    ".cache/diagrams/$name"
  mmdc \
    -i ".cache/diagrams/$name" \
    -o "$src.svg" \
    -c resources/diavisuals/styles/mermaid/benizar-mermaid.json
 done
```

Els blocs inline ```mermaid``` que es renderitzen al navegador poden continuar usant el tema dinamic actual de la web. `diavisuals` hauria d'aplicar-se primer als diagrames font versionats com `.mmd`, perquè son reproduibles i encaixen amb el plugin existent.

PlantUML en web pot arribar en una segona fase amb la mateixa filosofia: font versionada `.puml`, SVG generat en build, i una regla equivalent de reescriptura si cal.

## Altres projectes

Qualsevol projecte pot consumir el repo de dues maneres:

- Directament, cridant `style-diagram-source.sh` i el motor corresponent.
- Copiant o enllaçant `styles/` al lloc on el seu pipeline ja espera presets.

El criteri es sempre el mateix: estil centralitzat, render local i documentat en el consumidor.
