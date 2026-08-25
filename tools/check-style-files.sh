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
require_file compat/mermaid-10.9.1-plantuml-1.2020.02.env
require_file compat/mermaid-11.4.2-plantuml-1.2026.1.env
require_file docker/compat-renderer.Dockerfile
require_file docs/versioning.md
require_file docs/gallery.md
require_file tools/render-gallery-docker.sh
require_file tools/render-gallery-local.sh
require_file tools/normalize-mermaid-svg.py
require_file tools/style-diagram-source.sh
require_file tools/list-style-families.sh
require_file tools/resolve-style-name.sh

for type in "${mermaid_types[@]}"; do
  require_file "styles/mermaid/benizar-mermaid/${type}.mmd"
  require_file "examples/benizar/mermaid/${type}.mmd"
done

for type in "${plantuml_types[@]}"; do
  require_file "styles/plantuml/benizar-plantuml/${type}.puml"
  require_file "examples/benizar/plantuml/${type}.puml"
done

python3 -m json.tool styles/mermaid/benizar-mermaid.json >/dev/null
bash -n tools/check-style-files.sh tools/install-to-project.sh tools/render-examples.sh tools/render-gallery-docker.sh tools/render-gallery-local.sh tools/style-diagram-source.sh tools/list-style-families.sh tools/resolve-style-name.sh compat/mermaid-10.9.1-plantuml-1.2020.02.env compat/mermaid-11.4.2-plantuml-1.2026.1.env

if [[ $fail -ne 0 ]]; then
  exit 1
fi

if [[ $(tools/resolve-style-name.sh mermaid benizar) != 'benizar-mermaid' ]]; then exit 1; fi
if [[ $(tools/resolve-style-name.sh plantuml benizar) != 'benizar-plantuml' ]]; then exit 1; fi
if ! tools/list-style-families.sh | grep -qx 'benizar'; then exit 1; fi
printf 'diavisuals check ok\n'
