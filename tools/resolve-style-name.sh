#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $0 <mermaid|plantuml> <family-or-engine-style>

Resolve a human style family such as 'benizar' to the engine-specific style
name used by diavisuals, for example 'benizar-mermaid' or 'benizar-plantuml'.
Explicit engine style names are also accepted.
USAGE
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

engine=${1:?engine is required}
style=${2:?style family or engine style is required}
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

case "$engine" in
  mermaid)
    candidates=("$style" "${style%-mermaid}-mermaid")
    for candidate in "${candidates[@]}"; do
      if [[ -f "$repo_root/styles/mermaid/${candidate}.json" ]]; then
        printf '%s\n' "$candidate"
        exit 0
      fi
    done
    ;;
  plantuml)
    candidates=("$style" "${style%-plantuml}-plantuml")
    for candidate in "${candidates[@]}"; do
      if [[ -f "$repo_root/styles/plantuml/${candidate}.puml" ]]; then
        printf '%s\n' "$candidate"
        exit 0
      fi
    done
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

printf 'Unknown %s style or family: %s\n' "$engine" "$style" >&2
printf 'Supported families:\n' >&2
"$repo_root/tools/list-style-families.sh" >&2 || true
exit 1
