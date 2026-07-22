# Release Matrix

`diavisuals` release tags stay short. The engine versions and supported diagram sets are documented here, in the README badges, and in the gallery manifests.

## Current Release Target

| Release tag | Compatibility profile | Mermaid CLI | PlantUML | Families | Gallery |
| --- | --- | --- | --- | --- | --- |
| `v0.1.2` | `mermaid-11.4.2-plantuml-1.2026.1` | 11.4.2 | 1.2026.1 | `benizar` | `docs/gallery/benizar/mermaid-11.4.2-plantuml-1.2026.1/manifest.csv` |

Badges for this release:

```markdown
![release](https://img.shields.io/badge/release-v0.1.2-blue)
![Mermaid CLI](https://img.shields.io/badge/Mermaid_CLI-11.4.2-ff3670)
![PlantUML](https://img.shields.io/badge/PlantUML-1.2026.1-2a5db0)
![family](https://img.shields.io/badge/family-benizar-2a5db0)
```

## Legacy Compatibility Records

| Compatibility profile | Mermaid CLI | PlantUML | Purpose |
| --- | --- | --- | --- |
| `mermaid-10.9.1-plantuml-1.2020.02` | 10.9.1 | 1.2020.02 | Documents the older Ubuntu-package-based paper image. |

Legacy compatibility records are not release tags. They are retained so consumers can compare what changed when upgrading engines.
