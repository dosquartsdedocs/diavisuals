#!/usr/bin/env bash
set -euo pipefail

out_dir=${1:-dist/examples}
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"
mkdir -p "$out_dir/mermaid" "$out_dir/plantuml" .cache/mermaid .cache/plantuml

if command -v mmdc >/dev/null 2>&1; then
  for src in examples/benizar/mermaid/*.mmd; do
    name=$(basename "$src" .mmd)
    style="styles/mermaid/benizar-mermaid/${name}.mmd"
    styled=".cache/mermaid/${name}.mmd"
    if [[ -f $style ]]; then
      cat "$style" "$src" > "$styled"
    else
      cp "$src" "$styled"
    fi
    mmdc -i "$styled" -o "$out_dir/mermaid/${name}.svg" -c styles/mermaid/benizar-mermaid.json >/dev/null
  done
else
  printf 'skip Mermaid render: mmdc not found\n'
fi

if command -v plantuml >/dev/null 2>&1; then
  for src in examples/benizar/plantuml/*.puml; do
    name=$(basename "$src" .puml)
    type=$name
    style="styles/plantuml/benizar-plantuml/${type}.puml"
    styled=".cache/plantuml/${name}.puml"

    if grep -qiE '^@start(gantt|salt)' "$src"; then
      cp "$src" "$styled"
    else
      awk -v base="styles/plantuml/benizar-plantuml.puml" -v typefile="$style" '
        BEGIN { inserted=0 }
        /^@start/ && inserted == 0 {
          print $0
          while ((getline line < base) > 0) print line
          close(base)
          if ((getline line < typefile) > 0) {
            print ""
            print "'"'"' type override: " typefile
            print line
            while ((getline line < typefile) > 0) print line
            close(typefile)
          }
          inserted=1
          next
        }
        { print $0 }
      ' "$src" > "$styled"
    fi

    plantuml -tsvg -o "$(pwd)/$out_dir/plantuml" "$styled" >/dev/null
  done
else
  printf 'skip PlantUML render: plantuml not found\n'
fi
