SHELL := /usr/bin/env bash
OUT_DIR ?= dist/examples

.PHONY: help check render-examples clean

help:
	@printf "Targets:\n"
	@printf "  make check            Validate style files and JSON syntax\n"
	@printf "  make render-examples  Render examples when mmdc/plantuml are installed\n"
	@printf "  make clean            Remove generated outputs\n"

check:
	@tools/check-style-files.sh

render-examples:
	@tools/render-examples.sh "$(OUT_DIR)"

clean:
	@rm -rf dist .cache
