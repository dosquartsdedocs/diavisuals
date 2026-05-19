#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $0 <project-root> [link|copy]

Install diavisuals assets into a project that expects:
  res/styles/mermaid
  res/styles/plantuml

Default mode is link.
USAGE
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

project_root=${1:?project root is required}
mode=${2:-link}

if [[ $mode != "link" && $mode != "copy" ]]; then
  printf 'mode must be link or copy\n' >&2
  exit 2
fi

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
project_root=$(cd "$project_root" && pwd)

install_entry() {
  local rel=$1
  local dest_rel=$2
  local src="$repo_root/$rel"
  local dest="$project_root/$dest_rel"
  mkdir -p "$(dirname "$dest")"

  if [[ $mode == "link" ]]; then
    if [[ -d $dest && ! -L $dest ]]; then
      printf 'refusing to replace existing directory: %s\n' "$dest" >&2
      exit 3
    fi
    rm -f "$dest"
    ln -s "$src" "$dest"
  else
    if [[ -d $src ]]; then
      mkdir -p "$dest"
      cp -a "$src"/. "$dest"/
    else
      cp "$src" "$dest"
    fi
  fi
}

install_entry styles/mermaid/benizar-mermaid.json res/styles/mermaid/benizar-mermaid.json
install_entry styles/mermaid/benizar-mermaid res/styles/mermaid/benizar-mermaid
install_entry styles/plantuml/benizar-plantuml.puml res/styles/plantuml/benizar-plantuml.puml
install_entry styles/plantuml/benizar-plantuml res/styles/plantuml/benizar-plantuml

printf 'installed diavisuals assets in %s using %s mode\n' "$project_root" "$mode"
