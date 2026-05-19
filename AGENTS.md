# Notes for Codex agents

This repo is a shared diagram-style package. Keep changes scoped to style assets, examples, docs, and lightweight validation tools.

Do not add project-specific rendering filters here. Consumers such as `my-slides-vault`, `unaltrepaper`, or `unaltraweb` should own their build pipelines and import these assets.

Run `make check` after style changes. Run `make render-examples` only when Mermaid CLI and PlantUML are available locally.
