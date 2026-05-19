SHELL := /usr/bin/env bash
OUT_DIR ?= dist/examples
COMPAT_PROFILE ?= compat/mermaid-10.9.1-plantuml-1.2020.02.env

.PHONY: help check render-examples render-gallery render-gallery-local clean

help:
	@printf "Targets:\n"
	@printf "  make check            Validate style files and JSON syntax\n"
	@printf "  make render-examples  Render examples when mmdc/plantuml are installed\n"
	@printf "  make render-gallery   Render README gallery through a compatibility profile\n"
	@printf "  make clean            Remove generated outputs\n"

check:
	@tools/check-style-files.sh

render-examples:
	@tools/render-examples.sh "$(OUT_DIR)"

render-gallery:
	@tools/render-gallery-docker.sh "$(COMPAT_PROFILE)"

render-gallery-local:
	@tools/render-gallery-local.sh "$(COMPAT_PROFILE)"

clean:
	@rm -rf dist .cache
