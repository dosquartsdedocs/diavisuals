#!/usr/bin/env bash
set -euo pipefail

profile=${1:-compat/mermaid-11.16.0-plantuml-1.2026.1.env}
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

profile_name=$(basename "$profile")
if [[ ! $profile_name =~ ^[A-Za-z0-9._-]+\.env$ ]]; then
  printf 'invalid compatibility profile name: %s\n' "$profile" >&2
  exit 2
fi
profile_source="$repo_root/compat/$profile_name"
if [[ ! -f $profile_source || -L $profile_source ]]; then
  printf 'missing compatibility profile: %s\n' "$profile" >&2
  exit 2
fi

# shellcheck disable=SC1090
source "$profile_source"
image=${DIAVISUALS_RENDER_IMAGE:?DIAVISUALS_RENDER_IMAGE is required}
family=${DIAVISUALS_FAMILY:-benizar}
compat_id=${DIAVISUALS_COMPAT_ID:?DIAVISUALS_COMPAT_ID is required}
if [[ $family == "." || $family == ".." || $compat_id == "." || $compat_id == ".." || ! $family =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ || ! $compat_id =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  printf 'unsafe family or compatibility id\n' >&2
  exit 2
fi
out_dir="docs/gallery/${family}/${compat_id}"
cli=${DIAVISUALS_COMMAND:-$repo_root/.venv/bin/diavisuals}

"$cli" ensure-renderer --profile "compat/$profile_name" >/dev/null

stage=$(mktemp -d)
workspace="$stage/workspace"
result="$stage/gallery"
container_started=0

remove_gallery_container() {
  local inspect_error
  if timeout --signal=TERM --kill-after=5s 30s docker container rm --force "$container_name" >/dev/null 2>&1; then
    container_started=0
    return 0
  fi
  if inspect_error=$(timeout --signal=TERM --kill-after=5s 30s docker container inspect "$container_name" 2>&1); then
    return 1
  fi
  if [[ $inspect_error == *"No such object"* || $inspect_error == *"No such container"* ]]; then
    container_started=0
    return 0
  fi
  return 1
}

cleanup() {
  status=$?
  if [[ $container_started -eq 1 ]] && ! remove_gallery_container; then
    printf 'gallery container cleanup could not be verified: %s\n' "$container_name" >&2
    status=1
  fi
  rm -rf "$stage"
  exit "$status"
}
trap cleanup EXIT

mkdir -m 0755 "$workspace"
mkdir -m 0733 "$result"
mkdir -p \
  "$workspace/compat" \
  "$workspace/docs/gallery/$family/$compat_id" \
  "$workspace/examples" \
  "$workspace/styles/mermaid" \
  "$workspace/styles/plantuml" \
  "$workspace/tools" \
  "$workspace/.cache"

cp "$profile_source" "$workspace/compat/$profile_name"
cp -a "$repo_root/examples/$family" "$workspace/examples/"
cp "$repo_root/styles/mermaid/${family}-mermaid.json" "$workspace/styles/mermaid/"
cp -a "$repo_root/styles/mermaid/${family}-mermaid" "$workspace/styles/mermaid/"
cp "$repo_root/styles/plantuml/${family}-plantuml.puml" "$workspace/styles/plantuml/"
cp -a "$repo_root/styles/plantuml/${family}-plantuml" "$workspace/styles/plantuml/"
for tool in normalize-mermaid-svg.py render-examples.sh render-gallery-local.sh resolve-style-name.sh style-diagram-source.sh; do
  cp "$repo_root/tools/$tool" "$workspace/tools/$tool"
done
chmod 0555 "$workspace/tools/"*.sh

uid=$(id -u)
gid=$(id -g)
if [[ $uid -eq 0 ]]; then
  uid=65532
  gid=65532
fi
workspace_id=$(printf '%s' "$repo_root" | sha256sum | cut -c1-12)
container_name="diavisuals-gallery-${workspace_id}-$$"

container_started=1
set +e
timeout --signal=TERM --kill-after=10s 900s docker run --rm \
  --name "$container_name" \
  --label io.context.mcp-factory=diavisuals \
  --label "io.context.mcp-factory.workspace=${workspace_id}" \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges=true \
  --user "${uid}:${gid}" \
  --memory 1g \
  --memory-swap 1g \
  --cpus 2 \
  --pids-limit 256 \
  --ulimit nofile=1024:1024 \
  --ulimit fsize=67108864:67108864 \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=512m,mode=1777 \
  --tmpfs /workspace/.cache:rw,nosuid,nodev,noexec,size=512m,mode=1777 \
  --mount "type=bind,source=${workspace},target=/workspace,readonly" \
  --mount "type=bind,source=${result},target=/workspace/${out_dir}" \
  --workdir /workspace \
  --env HOME=/tmp/home \
  --env XDG_CACHE_HOME=/tmp/cache \
  --env JAVA_TOOL_OPTIONS=-Duser.home=/tmp/home \
  --env PLANTUML_SECURITY_PROFILE=SANDBOX \
  "$image" \
  bash tools/render-gallery-local.sh "compat/$profile_name"
render_status=$?
set -e
if ! remove_gallery_container; then
  printf 'gallery container cleanup could not be verified: %s\n' "$container_name" >&2
  exit 1
fi
if [[ $render_status -ne 0 ]]; then
  printf 'gallery renderer failed with status %s\n' "$render_status" >&2
  exit "$render_status"
fi

python3 "$repo_root/tools/publish-gallery.py" "$result" "$repo_root" "$family" "$compat_id"
