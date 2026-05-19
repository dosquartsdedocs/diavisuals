#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

shopt -s nullglob
for mermaid_style in styles/mermaid/*-mermaid.json; do
  name=$(basename "$mermaid_style" .json)
  family=${name%-mermaid}
  if [[ -f "styles/plantuml/${family}-plantuml.puml" ]]; then
    printf '%s\n' "$family"
  fi
done
