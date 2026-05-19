# Integracio amb projectes

## Recomanacio

Afegir `diavisuals` com a submodul o subtree i exposar els assets al lloc on el projecte ja busca estils.

```bash
git submodule add <url-del-repo-diavisuals> resources/diavisuals
./resources/diavisuals/tools/install-to-project.sh . link
```

El mode `link` crea enllacos simbolics cap a:

```text
res/styles/mermaid/benizar-mermaid.json
res/styles/mermaid/benizar-mermaid/
res/styles/plantuml/benizar-plantuml.puml
res/styles/plantuml/benizar-plantuml/
```

Si el projecte no vol symlinks, usa `copy`:

```bash
./resources/diavisuals/tools/install-to-project.sh . copy
```

## my-slides-vault

`my-slides-vault` ja implementa el contracte:

```yaml
diagram_styles:
  mermaid: benizar-mermaid
  plantuml: benizar-plantuml
```

Els filtres busquen primer el preset base i despres un override per tipus. Per exemple, un `quadrantChart` carrega `benizar-mermaid.json` i `benizar-mermaid/quadrantchart.mmd`.

## unaltrepaper

`unaltrepaper` hauria de tenir el codi compartit de renderitzat i plantilla. Els estils poden entrar com a submodul o com a dependencia de recursos, pero no haurien de viure dins d'un paper concret.

Contracte recomanat:

```text
resources/diavisuals/          # submodul o subtree
resources/styles/mermaid/      # symlinks o copia del paquet
resources/styles/plantuml/     # symlinks o copia del paquet
```

El paper pot exposar:

```yaml
diagram_styles:
  mermaid: benizar-mermaid
  plantuml: benizar-plantuml
```

## unaltrepaperalpap

Aquest repo hauria de demostrar l'us dels estils, les revisions i el latexdiff. No hauria de ser font d'estils compartits. Si necessita exemples de diagrames, els pot referenciar com a consumidors normals.

## unaltraweb i altres webs

Mermaid pot usar el JSON directament:

```bash
mmdc -i diagram.mmd -o diagram.svg -c resources/diavisuals/styles/mermaid/benizar-mermaid.json
```

Per aplicar overrides de tipus cal prependeix el snippet adequat abans de renderitzar:

```bash
cat resources/diavisuals/styles/mermaid/benizar-mermaid/flowchart.mmd diagram.mmd > .cache/diagram.styled.mmd
mmdc -i .cache/diagram.styled.mmd -o diagram.svg -c resources/diavisuals/styles/mermaid/benizar-mermaid.json
```

PlantUML pot incloure el preset base dins del diagrama generat o el pipeline pot injectar-lo despres de `@startuml`.
