SHELL := /usr/bin/env bash
OUT_DIR ?= dist/examples
COMPAT_PROFILE ?= compat/mermaid-11.4.2-plantuml-1.2026.1.env

.PHONY: help check tests test tests-mcp tests-install render-examples render-gallery render-gallery-local clean

help:
	@printf "Targets:\n"
	@printf "  make check            Validate style files and JSON syntax\n"
	@printf "  make tests            Run Python registry tests and shell checks\n"
	@printf "  make tests-mcp        Run MCP stdio smoke test with optional dependencies\n"
	@printf "  make tests-install    Verify editable CLI installation in .tmp\n"
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
	@uv pip install --python .tmp/install-venv/bin/python --editable .
	@.tmp/install-venv/bin/diavisuals --version
	@.tmp/install-venv/bin/diavisuals factory-manifest >/dev/null

render-examples:
	@tools/render-examples.sh "$(OUT_DIR)"

render-gallery:
	@tools/render-gallery-docker.sh "$(COMPAT_PROFILE)"

render-gallery-local:
	@tools/render-gallery-local.sh "$(COMPAT_PROFILE)"

clean:
	@rm -rf dist .cache
