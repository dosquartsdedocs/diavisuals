# Afegir un estil nou

Per afegir una familia nova, copia el patro de `benizar`:

1. Crea `tokens/<nom>.yml` amb colors, fonts i rols semantics.
2. Crea `styles/mermaid/<nom>-mermaid.json`.
3. Crea `styles/mermaid/<nom>-mermaid/<diagram-type>.mmd` per a cada tipus suportat.
4. Crea `styles/plantuml/<nom>-plantuml.puml`.
5. Crea `styles/plantuml/<nom>-plantuml/<diagram-type>.puml` per a cada tipus suportat.
6. Afegeix exemples en `examples/<nom>/...`.
7. Amplia `tools/check-style-files.sh` per comprovar el nou estil.
8. Executa `make check` i, si tens motors instal.lats, `make render-examples`.

Evita definir un estil nomes com a paleta global. El punt fort del repo es que cada tipus de diagrama pot tenir decisions propies: quadrants amb quatre colors contrastats, sequence diagrams amb espaiat diferent, treemaps amb series de colors, etc.
