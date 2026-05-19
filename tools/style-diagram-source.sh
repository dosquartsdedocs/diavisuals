#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $0 <mermaid|plantuml> <style-name> <input> <output>

Create a styled diagram source by applying the diavisuals base style and, when
available, the type-specific override. The caller remains responsible for
rendering the output with mmdc or plantuml.
USAGE
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

engine=${1:?engine is required}
style_name=${2:?style name is required}
input=${3:?input path is required}
output=${4:?output path is required}

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p "$(dirname "$output")"

first_meaningful_line() {
  sed -e '/^[[:space:]]*$/d' -e '/^[[:space:]]*%%/d' "$1" | head -n 1
}

normalize_mermaid_type() {
  local token=$1
  token=$(printf '%s' "$token" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9_-]//g')
  case "$token" in
    graph|flowchart*) printf 'flowchart' ;;
    sequencediagram*) printf 'sequence' ;;
    classdiagram*) printf 'class' ;;
    statediagram*) printf 'state' ;;
    erdiagram*) printf 'er' ;;
    gitgraph*) printf 'gitgraph' ;;
    quadrantchart*) printf 'quadrantchart' ;;
    sankey*) printf 'sankey' ;;
    treemap*) printf 'treemap' ;;
    pie*) printf 'pie' ;;
    journey*) printf 'journey' ;;
    kanban*) printf 'kanban' ;;
    timeline*) printf 'timeline' ;;
    block*) printf 'block' ;;
    gantt*) printf 'gantt' ;;
    *) printf '%s' "$token" ;;
  esac
}

mermaid_type() {
  local line token
  line=$(first_meaningful_line "$1" || true)
  token=$(printf '%s' "$line" | awk '{print $1}')
  normalize_mermaid_type "$token"
}

normalize_plantuml_type() {
  local token=$1
  token=$(printf '%s' "$token" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9_-]//g')
  case "$token" in
    statediagram) printf 'state' ;;
    activitydiagram) printf 'activity' ;;
    deploymentdiagram) printf 'deployment' ;;
    *) printf '%s' "$token" ;;
  esac
}

plantuml_type() {
  local lower token
  lower=$(tr '[:upper:]' '[:lower:]' < "$1")
  token=$(printf '%s' "$lower" | sed -nE 's/^[[:space:]]*@start([a-z0-9_-]+).*/\1/p' | head -n 1)
  if [[ -n $token && $token != uml ]]; then
    normalize_plantuml_type "$token"
    return
  fi
  if printf '%s' "$lower" | grep -Eq '^[[:space:]]*(participant|autonumber)[[:space:]]+'; then printf 'sequence'; return; fi
  if printf '%s' "$lower" | grep -Eq '^[[:space:]]*usecase[[:space:]]+'; then printf 'usecase'; return; fi
  if printf '%s' "$lower" | grep -Eq '^[[:space:]]*(class|interface|enum)[[:space:]]+'; then printf 'class'; return; fi
  if printf '%s' "$lower" | grep -Eq '^[[:space:]]*object[[:space:]]+'; then printf 'object'; return; fi
  if printf '%s' "$lower" | grep -Eq '^[[:space:]]*component[[:space:]]+'; then printf 'component'; return; fi
  if printf '%s' "$lower" | grep -Eq '^[[:space:]]*state[[:space:]]+|\[\*\][[:space:]]*-->'; then printf 'state'; return; fi
  if printf '%s' "$lower" | grep -Eq '^[[:space:]]*(node|cloud)[[:space:]]+'; then printf 'deployment'; return; fi
  if printf '%s' "$lower" | grep -Eq '^[[:space:]]*:[^;]+;'; then printf 'activity'; return; fi
  printf 'uml'
}

case "$engine" in
  mermaid)
    type_key=$(mermaid_type "$input")
    type_style="$repo_root/styles/mermaid/$style_name/$type_key.mmd"
    if [[ -f $type_style ]]; then
      cat "$type_style" "$input" > "$output"
    else
      cp "$input" "$output"
    fi
    ;;
  plantuml)
    base_style="$repo_root/styles/plantuml/$style_name.puml"
    type_key=$(plantuml_type "$input")
    type_style="$repo_root/styles/plantuml/$style_name/$type_key.puml"

    if [[ ! -f $base_style ]] || grep -qiE '^@start(gantt|salt)' "$input"; then
      cp "$input" "$output"
      exit 0
    fi

    awk -v base="$base_style" -v typefile="$type_style" '
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
    ' "$input" > "$output"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
