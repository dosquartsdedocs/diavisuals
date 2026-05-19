#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

mermaid_types=(flowchart sequence class state er gantt journey pie gitgraph quadrantchart sankey kanban timeline block treemap)
plantuml_types=(sequence class state usecase activity component deployment object mindmap wbs json yaml gantt salt files)

fail=0
require_file() {
  local path=$1
  if [[ ! -f $path ]]; then
    printf 'missing: %s\n' "$path" >&2
    fail=1
  fi
}

require_file styles/mermaid/benizar-mermaid.json
require_file styles/plantuml/benizar-plantuml.puml
require_file tokens/benizar.yml
require_file tools/style-diagram-source.sh

for type in "${mermaid_types[@]}"; do
  require_file "styles/mermaid/benizar-mermaid/${type}.mmd"
  require_file "examples/benizar/mermaid/${type}.mmd"
done

for type in "${plantuml_types[@]}"; do
  require_file "styles/plantuml/benizar-plantuml/${type}.puml"
  require_file "examples/benizar/plantuml/${type}.puml"
done

python3 -m json.tool styles/mermaid/benizar-mermaid.json >/dev/null
bash -n tools/check-style-files.sh tools/install-to-project.sh tools/render-examples.sh tools/style-diagram-source.sh

if [[ $fail -ne 0 ]]; then
  exit 1
fi

printf 'diavisuals check ok\n'
