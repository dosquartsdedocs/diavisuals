#!/usr/bin/env bash
set -euo pipefail

out_dir=${1:-dist/examples}
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"
rm -rf "$out_dir/mermaid" "$out_dir/plantuml" "$out_dir/readme" "$out_dir/manifest.csv"
mkdir -p "$out_dir/mermaid" "$out_dir/plantuml" "$out_dir/readme" .cache/mermaid .cache/plantuml

family=${DIAVISUALS_FAMILY:-benizar}
mermaid_style=${MERMAID_STYLE:-${family}-mermaid}
plantuml_style=${PLANTUML_STYLE:-${family}-plantuml}
mermaid_config=${MERMAID_CONFIG:-styles/mermaid/${mermaid_style}.json}
puppeteer_config=${PUPPETEER_CONFIG:-.cache/puppeteer.json}
readme_mermaid_types=${README_MERMAID_TYPES:-flowchart kanban quadrantchart}
readme_plantuml_types=${README_PLANTUML_TYPES:-sequence files activity}

if [[ -z ${PUPPETEER_CONFIG:-} || ! -f $puppeteer_config ]]; then
  mkdir -p "$(dirname "$puppeteer_config")"
  printf '{"args":["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage","--disable-crash-reporter","--disable-crashpad"]}\n' > "$puppeteer_config"
fi

contains_type() {
  local needle=$1 haystack=${2:-}
  [[ " $haystack " == *" $needle "* ]]
}

write_manifest() {
  local engine=$1 name=$2 status=$3 output=${4:-}
  printf '%s,%s,%s,%s\n' "$engine" "$name" "$status" "$output" >> "$out_dir/manifest.csv"
}

make_plantuml_readme_source() {
  local input=$1 output=$2
  sed \
    -e 's/BackGroundColor transparent/BackGroundColor #FFFFFF/g' \
    -e 's/skinparam BackgroundColor transparent/skinparam BackgroundColor #FFFFFF/g' \
    "$input" > "$output"
}

printf 'engine,type,status,output\n' > "$out_dir/manifest.csv"

if command -v mmdc >/dev/null 2>&1; then
  for src in examples/benizar/mermaid/*.mmd; do
    name=$(basename "$src" .mmd)
    if contains_type "$name" "${MERMAID_UNSUPPORTED_TYPES:-}"; then
      write_manifest mermaid "$name" unsupported ""
      continue
    fi
    if [[ -n ${MERMAID_TYPES:-} ]] && ! contains_type "$name" "$MERMAID_TYPES"; then
      write_manifest mermaid "$name" skipped ""
      continue
    fi
    styled=".cache/mermaid/${name}.mmd"
    output="$out_dir/mermaid/${name}.svg"
    tools/style-diagram-source.sh mermaid "$mermaid_style" "$src" "$styled"
    mmdc -i "$styled" -o "$output" -c "$mermaid_config" -p "$puppeteer_config" >/dev/null
    if contains_type "$name" "$readme_mermaid_types"; then
      mmdc -i "$styled" -o "$out_dir/readme/mermaid-${name}.png" -c "$mermaid_config" -p "$puppeteer_config" --scale 1 >/dev/null
    fi
    write_manifest mermaid "$name" rendered "$output"
  done
else
  printf 'skip Mermaid render: mmdc not found\n'
fi

if command -v plantuml >/dev/null 2>&1; then
  for src in examples/benizar/plantuml/*.puml; do
    name=$(basename "$src" .puml)
    if contains_type "$name" "${PLANTUML_UNSUPPORTED_TYPES:-}"; then
      write_manifest plantuml "$name" unsupported ""
      continue
    fi
    if [[ -n ${PLANTUML_TYPES:-} ]] && ! contains_type "$name" "$PLANTUML_TYPES"; then
      write_manifest plantuml "$name" skipped ""
      continue
    fi
    styled=".cache/plantuml/${name}.puml"
    output="$out_dir/plantuml/${name}.svg"
    tools/style-diagram-source.sh plantuml "$plantuml_style" "$src" "$styled"
    plantuml -tsvg -o "$(pwd)/$out_dir/plantuml" "$styled" >/dev/null
    if [[ ! -f $output ]]; then
      printf 'missing PlantUML output: %s\n' "$output" >&2
      exit 1
    fi
    if contains_type "$name" "$readme_plantuml_types"; then
      readme_styled=".cache/plantuml/${name}.readme.puml"
      readme_raw="$out_dir/readme/${name}.readme.png"
      make_plantuml_readme_source "$styled" "$readme_styled"
      plantuml -tpng -o "$(pwd)/$out_dir/readme" "$readme_styled" >/dev/null
      if [[ ! -f $readme_raw ]]; then
        printf 'missing PlantUML README thumbnail: %s\n' "$readme_raw" >&2
        exit 1
      fi
      mv "$readme_raw" "$out_dir/readme/plantuml-${name}.png"
    fi
    write_manifest plantuml "$name" rendered "$output"
  done
else
  printf 'skip PlantUML render: plantuml not found\n'
fi
