# Release Matrix

`diavisuals` release tags stay short. The engine versions and supported diagram sets are documented here, in the README badges, and in the gallery manifests.

## Current Release Target

| Release tag | Compatibility profile | Mermaid CLI | PlantUML | Families | Gallery |
| --- | --- | --- | --- | --- | --- |
| `v0.3.1` | `mermaid-11.16.0-plantuml-1.2026.1` | 11.16.0 | 1.2026.1 | `benizar` | `docs/gallery/benizar/mermaid-11.16.0-plantuml-1.2026.1/manifest.csv` |

Badges for this release:

```markdown
![release](https://img.shields.io/badge/release-v0.3.1-2a5db0)
![Mermaid CLI](https://img.shields.io/badge/Mermaid_CLI-11.16.0-ff3670)
![PlantUML](https://img.shields.io/badge/PlantUML-1.2026.1-2a5db0)
![family](https://img.shields.io/badge/family-benizar-2a5db0)
```

## Legacy Compatibility Records

`v0.2.0` used Mermaid CLI 11.4.2 and mounted the consumer workspace into the
renderer. Upgrade to `v0.3.0` for supported Node/Puppeteer dependencies,
private staging, and the hardened container boundary.

| Release | Compatibility profile | Mermaid CLI | PlantUML | Purpose |
| --- | --- | --- | --- | --- |
| `v0.2.0` | `mermaid-11.4.2-plantuml-1.2026.1` | 11.4.2 | 1.2026.1 | Records the first Docker renderer contract. |
| `v0.1.x` | `mermaid-10.9.1-plantuml-1.2020.02` | 10.9.1 | 1.2020.02 | Documents the older Ubuntu-package-based paper image. |

These profiles are record-only and cannot build a renderer from the current
checkout. They are retained so consumers can compare what changed when
upgrading engines.
