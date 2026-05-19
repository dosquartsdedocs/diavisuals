# Versions i compatibilitat

`diavisuals` versiona dues coses que no sempre avancen al mateix ritme:

- El contracte d'estil del repo: tokens, presets, snippets per tipus i exemples.
- Els motors que renderitzen els diagrames: Mermaid CLI i PlantUML.

Per evitar ambiguitats, cada render reproduible usa un perfil en `compat/`.
El nom del perfil inclou les versions dels motors, per exemple:

```text
compat/mermaid-10.9.1-plantuml-1.2020.02.env
```

Un projecte consumidor pot dir quin perfil suporta sense copiar estils. Per
exemple, `unaltrepaper` pot documentar que la seua imatge Docker actual suporta
`mermaid-10.9.1-plantuml-1.2020.02`, mentre que `unaltraweb` podria adoptar un
perfil Mermaid mes nou quan el seu build ho permeta.

## Regla de releases

- Un canvi nomes visual dins del mateix contracte pot ser una release menor de
  `diavisuals`.
- Un canvi que afegeix o elimina tipus de diagrama suportats ha de crear o
  actualitzar el perfil de compatibilitat corresponent.
- Un canvi de versio Mermaid o PlantUML ha de crear un perfil nou, no
  sobreescriure l'anterior.
- Els projectes fills haurien de fixar un commit o tag de `diavisuals` i indicar
  quin perfil renderitzen en CI o en Docker.

## Galeria

La galeria versionada viu en:

```text
docs/gallery/<family>/<compat-id>/
```

Es regenera amb:

```bash
make render-gallery
```

El target usa Docker per evitar dependre de les eines instal.lades a la maquina
local. Dins del contenidor s'executa `make render-gallery-local`, que crida
`tools/render-examples.sh` amb el perfil carregat.
