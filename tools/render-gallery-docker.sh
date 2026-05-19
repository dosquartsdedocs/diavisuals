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

image=${DIAVISUALS_RENDER_IMAGE:?DIAVISUALS_RENDER_IMAGE is required}
uid=$(id -u)
gid=$(id -g)

docker run --rm \
  --user "${uid}:${gid}" \
  -v "$repo_root:/workspace" \
  -w /workspace \
  "$image" \
  make render-gallery-local COMPAT_PROFILE="$profile"
