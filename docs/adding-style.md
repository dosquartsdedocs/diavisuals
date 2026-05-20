# Adding A New Style

To add a new family, copy the `benizar` pattern:

1. Create `tokens/<name>.yml` with colors, fonts, and semantic roles.
2. Create `styles/mermaid/<name>-mermaid.json`.
3. Create `styles/mermaid/<name>-mermaid/<diagram-type>.mmd` for each supported type.
4. Create `styles/plantuml/<name>-plantuml.puml`.
5. Create `styles/plantuml/<name>-plantuml/<diagram-type>.puml` for each supported type.
6. Add examples under `examples/<name>/...`.
7. Extend `tools/check-style-files.sh` so the new family is validated.
8. Run `make check` and, when render engines are available, `make render-gallery` or `make render-examples`.

Avoid defining a style only as a global palette. The main value of this repository is that each diagram type can make its own decisions: quadrant charts may need four contrasting colors, sequence diagrams may need different spacing, and treemaps may need a color series.
