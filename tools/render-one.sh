#!/usr/bin/env bash
set -euo pipefail

engine=${1:?engine is required}
style_name=${2:?style name is required}
output_format=${3:?output format is required}

case "$engine" in
  mermaid)
    input=/diavisuals/input/source.mmd
    styled=/tmp/work/styled.mmd
    ;;
  plantuml)
    input=/diavisuals/input/source.puml
    styled=/tmp/work/styled.puml
    ;;
  *)
    printf 'unsupported diagram engine: %s\n' "$engine" >&2
    exit 2
    ;;
esac

case "$output_format" in
  svg|png|pdf) ;;
  *)
    printf 'unsupported output format: %s\n' "$output_format" >&2
    exit 2
    ;;
esac

umask 077
mkdir -p /tmp/home /tmp/cache /tmp/work
bash /diavisuals/tools/style-diagram-source.sh "$engine" "$style_name" "$input" "$styled"

if [[ $engine == mermaid ]]; then
  puppeteer_config=/tmp/work/puppeteer.json
  printf '%s\n' '{"args":["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage","--disable-crash-reporter","--disable-crashpad"]}' > "$puppeteer_config"
  command=(
    mmdc
    -i "$styled"
    -o "/output/artifact.${output_format}"
    -c "/diavisuals/styles/mermaid/${style_name}.json"
    -p "$puppeteer_config"
  )
  if [[ $output_format == pdf ]]; then
    command+=(--pdfFit)
  fi
  "${command[@]}"
  if [[ $output_format == svg ]]; then
    python3 /diavisuals/tools/normalize-mermaid-svg.py "/output/artifact.${output_format}"
  fi
else
  plantuml "-t${output_format}" -o /output "$styled"
  expected="/output/styled.${output_format}"
  if [[ ! -f $expected ]]; then
    printf 'PlantUML did not create the expected artifact: %s\n' "$expected" >&2
    exit 1
  fi
  mv "$expected" "/output/artifact.${output_format}"
fi

# Rootless Docker and userns-remap translate container ownership; the private
# host staging directory remains inaccessible while the artifact stays readable.
chmod 0644 "/output/artifact.${output_format}"
