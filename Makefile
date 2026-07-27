SHELL := /usr/bin/env bash
OUT_DIR ?= dist/examples
COMPAT_PROFILE ?= compat/mermaid-11.4.2-plantuml-1.2026.1.env
PROJECT ?= .
ENGINE ?= auto
FAMILY ?= benizar
FORMAT ?= svg

.PHONY: help check tests test tests-mcp tests-install docker-build-renderer mcp-build mcp-init mcp-check mcp-smoke render-diagram render-examples render-gallery render-gallery-local clean

help:
	@printf "Targets:\n"
	@printf "  make check            Validate style files and JSON syntax\n"
	@printf "  make tests            Run Python registry tests and shell checks\n"
	@printf "  make tests-mcp        Run MCP stdio smoke test with optional dependencies\n"
	@printf "  make tests-install    Verify editable CLI installation in .tmp\n"
	@printf "  make docker-build-renderer Build the Mermaid/PlantUML renderer image\n"
	@printf "  make mcp-build        Prepare the MCP optional dependencies\n"
	@printf "  make mcp-smoke        Run the repo-owned MCP smoke check\n"
	@printf "  make render-diagram INPUT=... OUTPUT=... Render one styled diagram through Docker\n"
	@printf "  make render-examples  Render examples when mmdc/plantuml are installed\n"
	@printf "  make render-gallery   Render README gallery through a compatibility profile\n"
	@printf "  make clean            Remove generated outputs\n"

check:
	@tools/check-style-files.sh

tests: check
	@PYTHONPATH=src python3 -m py_compile src/diavisuals/__init__.py src/diavisuals/registry.py src/diavisuals/cli.py src/diavisuals/mcp_server.py
	@PYTHONPATH=src python3 -m unittest discover -s tests

test: tests

tests-mcp:
	@DIAVISUALS_MCP_SMOKE=1 uv run --extra mcp python -m unittest discover -s tests

tests-install:
	@mkdir -p .tmp
	@uv venv --clear .tmp/install-venv
	@uv pip install --python .tmp/install-venv/bin/python --editable '.[mcp]'
	@.tmp/install-venv/bin/diavisuals --version
	@.tmp/install-venv/bin/diavisuals install-check >/dev/null
	@.tmp/install-venv/bin/diavisuals factory-manifest >/dev/null

docker-build-renderer:
	@PYTHONPATH=src python3 -m diavisuals.cli build-renderer --profile "$(COMPAT_PROFILE)" >/dev/null

mcp-build: docker-build-renderer
	@uv run --extra mcp diavisuals install-check >/dev/null

mcp-init: mcp-build

mcp-check: check

mcp-smoke: tests-mcp

render-diagram:
	@test -n "$(INPUT)" || (echo "Usage: make render-diagram INPUT=<diagram> OUTPUT=<output>" >&2; exit 2)
	@test -n "$(OUTPUT)" || (echo "Usage: make render-diagram INPUT=<diagram> OUTPUT=<output>" >&2; exit 2)
	@PYTHONPATH=src python3 -m diavisuals.cli --project "$(PROJECT)" render-diagram --engine "$(ENGINE)" --family "$(FAMILY)" --profile "$(COMPAT_PROFILE)" --format "$(FORMAT)" "$(INPUT)" "$(OUTPUT)"

render-examples:
	@tools/render-examples.sh "$(OUT_DIR)"

render-gallery:
	@tools/render-gallery-docker.sh "$(COMPAT_PROFILE)"

render-gallery-local:
	@tools/render-gallery-local.sh "$(COMPAT_PROFILE)"

clean:
	@rm -rf dist .cache
