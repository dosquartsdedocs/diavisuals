# Style Families

A style family is the user-facing name shared by all diagram engines. For
example, `benizar` resolves to:

```text
styles/mermaid/benizar-mermaid.json
styles/mermaid/benizar-mermaid/<diagram-type>.mmd
styles/plantuml/benizar-plantuml.puml
styles/plantuml/benizar-plantuml/<diagram-type>.puml
```

A family is considered supported when both the Mermaid base JSON and the
PlantUML base snippet exist.

List supported families:

```bash
tools/list-style-families.sh
```

Resolve a family for one engine:

```bash
tools/resolve-style-name.sh mermaid benizar   # benizar-mermaid
tools/resolve-style-name.sh plantuml benizar  # benizar-plantuml
```

Explicit engine style names are still accepted:

```bash
tools/resolve-style-name.sh mermaid benizar-mermaid
tools/resolve-style-name.sh plantuml benizar-plantuml
```

## Adding A Family

To add `urv`, create at least:

```text
styles/mermaid/urv-mermaid.json
styles/plantuml/urv-plantuml.puml
```

Then add type overrides as needed:

```text
styles/mermaid/urv-mermaid/quadrantchart.mmd
styles/plantuml/urv-plantuml/sequence.puml
```

Run:

```bash
make check
```

Consumer projects should normally configure only the family name:

```yaml
diagram_styles:
  family: urv
```

They may still override one engine when needed:

```yaml
diagram_styles:
  family: urv
  mermaid: urv-mermaid
  plantuml: benizar-plantuml
```
