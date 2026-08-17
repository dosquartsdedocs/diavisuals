SHELL := /usr/bin/env bash
PYTHON ?= python3
OUT_DIR ?= dist/examples
COMPAT_PROFILE ?= compat/mermaid-11.4.2-plantuml-1.2026.1.env
PROJECT ?= .
ENGINE ?= auto
FAMILY ?= benizar
FORMAT ?= svg
MCP_VENV ?= .cache/diavisuals/mcp-venv
MCP_ENV_STAMP := $(MCP_VENV)/.diavisuals-mcp-installed
MCP_PYTHON := $(MCP_VENV)/bin/python
MCP_CLI := $(MCP_VENV)/bin/diavisuals

.PHONY: help check tests test tests-mcp tests-install mcp-env docker-build-renderer docker-ensure-renderer mcp-build mcp-init mcp-check mcp-smoke mcp-down mcp-stdio render-diagram render-examples render-gallery render-gallery-local clean

help:
	@printf "Targets:\n"
	@printf "  make check            Validate style files and JSON syntax\n"
	@printf "  make tests            Run Python registry tests and shell checks\n"
	@printf "  make tests-mcp        Run MCP stdio smoke test with optional dependencies\n"
	@printf "  make tests-install    Verify editable CLI installation in .tmp\n"
	@printf "  make mcp-env          Prepare the local MCP Python environment\n"
	@printf "  make docker-build-renderer Build the Mermaid/PlantUML renderer image\n"
	@printf "  make docker-ensure-renderer Ensure the renderer image exists\n"
	@printf "  make mcp-build        Prepare the MCP optional dependencies\n"
	@printf "  make mcp-smoke        Run the MCP smoke check and render one SVG through Docker\n"
	@printf "  make mcp-down         Force-remove diavisuals renderer containers only\n"
	@printf "  make mcp-stdio        Serve the MCP through the standard stdio launcher\n"
	@printf "  make render-diagram INPUT=... OUTPUT=... Render one styled diagram through Docker\n"
	@printf "  make render-examples  Render examples when mmdc/plantuml are installed\n"
	@printf "  make render-gallery   Render README gallery through a compatibility profile\n"
	@printf "  make clean            Remove generated outputs\n"

check:
	@tools/check-style-files.sh

tests: check
	@PYTHONPATH=src $(PYTHON) -m py_compile src/diavisuals/__init__.py src/diavisuals/registry.py src/diavisuals/cli.py src/diavisuals/mcp_server.py
	@PYTHONPATH=src $(PYTHON) -m unittest discover -s tests

test: tests

tests-mcp: mcp-env
	@DIAVISUALS_MCP_SMOKE=1 "$(MCP_PYTHON)" -m unittest discover -s tests

tests-install:
	@mkdir -p .tmp
	@rm -rf .tmp/install-venv
	@$(PYTHON) -m venv .tmp/install-venv
	@.tmp/install-venv/bin/python -m pip install --upgrade pip >/dev/null
	@.tmp/install-venv/bin/python -m pip install --editable '.[mcp]' >/dev/null
	@.tmp/install-venv/bin/diavisuals --version
	@.tmp/install-venv/bin/diavisuals install-check --command .tmp/install-venv/bin/diavisuals >/dev/null
	@.tmp/install-venv/bin/diavisuals factory-manifest >/dev/null

mcp-env: $(MCP_ENV_STAMP)

$(MCP_ENV_STAMP): pyproject.toml
	@mkdir -p "$(dir $(MCP_VENV))"
	@$(PYTHON) -m venv "$(MCP_VENV)"
	@"$(MCP_PYTHON)" -m pip install --upgrade pip >/dev/null
	@"$(MCP_PYTHON)" -m pip install --editable '.[mcp]' >/dev/null
	@touch "$@"

docker-build-renderer:
	@PYTHONPATH=src python3 -m diavisuals.cli build-renderer --profile "$(COMPAT_PROFILE)" >/dev/null

docker-ensure-renderer:
	@PYTHONPATH=src python3 -m diavisuals.cli ensure-renderer --profile "$(COMPAT_PROFILE)" >/dev/null

mcp-build: docker-ensure-renderer mcp-env
	@"$(MCP_CLI)" install-check --command "$(MCP_CLI)" >/dev/null

mcp-init: mcp-build

mcp-check: check

mcp-smoke: mcp-build tests-mcp
	@"$(MCP_CLI)" --project "$(CURDIR)" render-diagram-text --text 'graph TD; A[Smoke] --> B[SVG]' --output ".cache/diavisuals/smoke/smoke.svg" --format svg --no-data >/dev/null
	@printf '%s\n' '@startuml' 'Alice -> Bob : Smoke' '@enduml' | "$(MCP_CLI)" --project "$(CURDIR)" render-diagram-text --output ".cache/diavisuals/smoke/plantuml-smoke.pdf" --format pdf --no-data >/dev/null

mcp-down:
	@containers="$$(docker container ls --all --quiet --filter 'label=io.context.mcp-factory=diavisuals')"; \
	if [[ -n "$$containers" ]]; then docker container rm --force $$containers >/dev/null; fi

mcp-stdio: mcp-env
	@"$(MCP_CLI)" --project "$(PROJECT)" mcp serve

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
