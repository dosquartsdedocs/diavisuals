#!/usr/bin/env bash
set -euo pipefail

profile=${1:-compat/mermaid-11.4.2-plantuml-1.2026.1.env}
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

if [[ ! -f $profile ]]; then
  printf 'missing compatibility profile: %s\n' "$profile" >&2
  exit 2
fi

# shellcheck disable=SC1090
source "$profile"

image=${DIAVISUALS_RENDER_IMAGE:?DIAVISUALS_RENDER_IMAGE is required}

if ! docker image inspect "$image" >/dev/null 2>&1; then
  if [[ -z ${DIAVISUALS_RENDER_DOCKERFILE:-} ]]; then
    printf 'missing Docker image: %s\n' "$image" >&2
    printf 'the profile does not define DIAVISUALS_RENDER_DOCKERFILE, so it cannot be built automatically\n' >&2
    exit 1
  fi
  docker build \
    -f "$DIAVISUALS_RENDER_DOCKERFILE" \
    --build-arg MERMAID_CLI_VERSION="${MERMAID_CLI_VERSION:?}" \
    --build-arg PLANTUML_VERSION="${PLANTUML_VERSION:?}" \
    -t "$image" \
    .
fi

uid=$(id -u)
gid=$(id -g)

docker run --rm \
  --label io.context.mcp-factory=diavisuals \
  --user "${uid}:${gid}" \
  -e HOME=/tmp \
  -e JAVA_TOOL_OPTIONS=-Duser.home=/tmp \
  -v "$repo_root:/workspace" \
  -w /workspace \
  "$image" \
  make render-gallery-local COMPAT_PROFILE="$profile"
