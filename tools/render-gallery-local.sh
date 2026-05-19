#!/usr/bin/env bash
set -euo pipefail

profile=${1:-compat/mermaid-10.9.1-plantuml-1.2020.02.env}
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

if [[ ! -f $profile ]]; then
  printf 'missing compatibility profile: %s\n' "$profile" >&2
  exit 2
fi

# shellcheck disable=SC1090
source "$profile"

family=${DIAVISUALS_FAMILY:-benizar}
compat_id=${DIAVISUALS_COMPAT_ID:?DIAVISUALS_COMPAT_ID is required}
out_dir="docs/gallery/${family}/${compat_id}"

MERMAID_TYPES=${MERMAID_TYPES:-} \
MERMAID_UNSUPPORTED_TYPES=${MERMAID_UNSUPPORTED_TYPES:-} \
PLANTUML_TYPES=${PLANTUML_TYPES:-} \
PLANTUML_UNSUPPORTED_TYPES=${PLANTUML_UNSUPPORTED_TYPES:-} \
DIAVISUALS_COMPAT_ID="$compat_id" \
DIAVISUALS_FAMILY="$family" \
tools/render-examples.sh "$out_dir"
