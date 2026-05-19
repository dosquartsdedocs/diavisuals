#!/usr/bin/env bash
set -euo pipefail

out_dir=${1:-dist/examples}
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"
mkdir -p "$out_dir/mermaid" "$out_dir/plantuml" .cache/mermaid .cache/plantuml

if command -v mmdc >/dev/null 2>&1; then
  for src in examples/benizar/mermaid/*.mmd; do
    name=$(basename "$src" .mmd)
    styled=".cache/mermaid/${name}.mmd"
    tools/style-diagram-source.sh mermaid benizar-mermaid "$src" "$styled"
    mmdc -i "$styled" -o "$out_dir/mermaid/${name}.svg" -c styles/mermaid/benizar-mermaid.json >/dev/null
  done
else
  printf 'skip Mermaid render: mmdc not found\n'
fi

if command -v plantuml >/dev/null 2>&1; then
  for src in examples/benizar/plantuml/*.puml; do
    name=$(basename "$src" .puml)
    styled=".cache/plantuml/${name}.puml"
    tools/style-diagram-source.sh plantuml benizar-plantuml "$src" "$styled"
    plantuml -tsvg -o "$(pwd)/$out_dir/plantuml" "$styled" >/dev/null
  done
else
  printf 'skip PlantUML render: plantuml not found\n'
fi
