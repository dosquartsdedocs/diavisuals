SHELL := /usr/bin/env bash
UV ?= uv
PROJECT ?= .
OUT_DIR ?= dist/examples
COMPAT_PROFILE ?= compat/mermaid-12.0.0-plantuml-1.2026.9.env
ENGINE ?= auto
FAMILY ?= benizar
FORMAT ?= svg
INPUT ?=
OUTPUT ?=
CLI := .venv/bin/diavisuals
PYTHON := .venv/bin/python
override PROJECT := $(value PROJECT)
override OUT_DIR := $(value OUT_DIR)
override COMPAT_PROFILE := $(value COMPAT_PROFILE)
override ENGINE := $(value ENGINE)
override FAMILY := $(value FAMILY)
override FORMAT := $(value FORMAT)
override INPUT := $(value INPUT)
override OUTPUT := $(value OUTPUT)
export PROJECT OUT_DIR COMPAT_PROFILE ENGINE FAMILY FORMAT INPUT OUTPUT

.PHONY: help check lint tests test tests-mcp tests-install tests-d0-published mcp-env docker-build-renderer docker-ensure-renderer docker-test mcp-build mcp-init mcp-check mcp-smoke mcp-down mcp-stdio project-check render-diagram render-examples render-gallery render-gallery-local clean

help:
	@printf "Targets:\n"
	@printf "  make check            Validate style and factory files\n"
	@printf "  make lint             Run Python lint checks\n"
	@printf "  make tests            Run deterministic host tests\n"
	@printf "  make tests-mcp        Run a real MCP stdio protocol smoke\n"
	@printf "  make tests-install    Verify wheel and sdist installations\n"
	@printf "  make tests-d0-published  Verify explicitly prepared published 0.6.0/0.7.0 D0 points\n"
	@printf "  make mcp-build        Prepare the factory environment and renderer image\n"
	@printf "  make mcp-init         Initialize the selected PROJECT cache\n"
	@printf "  make mcp-check        Validate the factory lifecycle\n"
	@printf "  make mcp-smoke        Run a minimal real workflow using the prepared MCP/renderer\n"
	@printf "  make mcp-down         Remove renderer containers for PROJECT only\n"
	@printf "  make mcp-stdio        Serve the MCP for MCP_CONSUMER_WORKSPACE (or PROJECT)\n"
	@printf "  make project-check    Check PROJECT diagrams and publish its receipt\n"
	@printf "  make render-diagram INPUT=... OUTPUT=... Render one styled diagram\n"
	@printf "  make render-gallery   Regenerate the compatibility gallery\n"

mcp-env:
	@$(UV) sync --locked --extra dev --extra mcp --quiet

check:
	@tools/check-style-files.sh

lint: mcp-env
	@$(UV) run --locked --extra dev --extra mcp ruff check src tests

tests: mcp-env check
	@$(PYTHON) -m unittest discover -s tests

test: tests

tests-mcp: mcp-env
	@$(CLI) mcp-smoke --protocol-only >/dev/null
	@DIAVISUALS_MCP_SMOKE=1 DIAVISUALS_MCP_FACTORY_ROOT="$${PWD}" $(PYTHON) -m unittest tests.test_registry.RegistryTest.test_mcp_stdio_smoke_when_enabled
	@DIAVISUALS_MCP_SMOKE=1 $(PYTHON) -m unittest tests.test_artifacts_runtime.ArtifactMCPTest
	@DIAVISUALS_MCP_SMOKE=1 $(PYTHON) -m unittest tests.test_session_mcp
	@DIAVISUALS_MCP_SMOKE=1 $(PYTHON) -m unittest tests.test_smoke.SmokeProtocolTest

tests-install: mcp-env
	@rm -rf .tmp/install-wheel .tmp/install-sdist dist
	@$(UV) build
	@$(UV) venv --python 3.10 .tmp/install-wheel >/dev/null
	@$(UV) pip install --python .tmp/install-wheel/bin/python dist/*.whl 'mcp==2.3.0' >/dev/null
	@set -euo pipefail; consumer="$$(mktemp -d)"; trap 'rm -rf "$$consumer"' EXIT; \
	mkdir -p "$$consumer/assets/diagrams"; \
	printf 'flowchart LR\n  A --> B\n' >"$$consumer/assets/diagrams/install.mmd"; \
	printf '<svg xmlns="http://www.w3.org/2000/svg"/>\n' >"$$consumer/assets/diagrams/install.mmd.svg"; \
	.tmp/install-wheel/bin/diavisuals --project "$$consumer" init >/dev/null; \
	.tmp/install-wheel/bin/diavisuals --project "$$consumer" project-check >/dev/null; \
	test -f "$$consumer/.unaltraweb/receipts/diavisuals.json"; \
	.tmp/install-wheel/bin/diavisuals factory-check >/dev/null; \
	if [[ "$${DIAVISUALS_DOCKER_SMOKE:-0}" == 1 ]]; then .tmp/install-wheel/bin/diavisuals mcp-smoke >/dev/null; \
	else .tmp/install-wheel/bin/diavisuals mcp-smoke --protocol-only >/dev/null; fi
	@DIAVISUALS_INSTALLED=1 DIAVISUALS_MCP_SMOKE=1 DIAVISUALS_W1_EVIDENCE="$${DIAVISUALS_W1_EVIDENCE:+$${DIAVISUALS_W1_EVIDENCE}/wheel}" .tmp/install-wheel/bin/python -m unittest tests.test_artifacts tests.test_artifacts_runtime tests.test_runtime_selection tests.test_runtime_selection_docker tests.test_session tests.test_session_mcp tests.test_d0_acceptance tests.test_job_storage tests.test_job_storage_docker tests.test_smoke
	@$(UV) venv --python 3.10 .tmp/install-sdist >/dev/null
	@$(UV) pip install --python .tmp/install-sdist/bin/python dist/*.tar.gz 'mcp==2.3.0' >/dev/null
	@set -euo pipefail; consumer="$$(mktemp -d)"; trap 'rm -rf "$$consumer"' EXIT; \
	mkdir -p "$$consumer/assets/diagrams"; \
	printf '@startuml\nAlice -> Bob\n@enduml\n' >"$$consumer/assets/diagrams/install.puml"; \
	printf '<svg xmlns="http://www.w3.org/2000/svg"/>\n' >"$$consumer/assets/diagrams/install.puml.svg"; \
	.tmp/install-sdist/bin/diavisuals --project "$$consumer" init >/dev/null; \
	.tmp/install-sdist/bin/diavisuals --project "$$consumer" project-check >/dev/null; \
	test -f "$$consumer/.unaltraweb/receipts/diavisuals.json"; \
	.tmp/install-sdist/bin/diavisuals factory-check >/dev/null; \
	if [[ "$${DIAVISUALS_DOCKER_SMOKE:-0}" == 1 ]]; then .tmp/install-sdist/bin/diavisuals mcp-smoke >/dev/null; \
	else .tmp/install-sdist/bin/diavisuals mcp-smoke --protocol-only >/dev/null; fi
	@DIAVISUALS_INSTALLED=1 DIAVISUALS_MCP_SMOKE=1 DIAVISUALS_W1_EVIDENCE="$${DIAVISUALS_W1_EVIDENCE:+$${DIAVISUALS_W1_EVIDENCE}/sdist}" .tmp/install-sdist/bin/python -m unittest tests.test_artifacts tests.test_artifacts_runtime tests.test_runtime_selection tests.test_runtime_selection_docker tests.test_session tests.test_session_mcp tests.test_d0_acceptance tests.test_job_storage tests.test_job_storage_docker tests.test_smoke

docker-build-renderer: mcp-env
	@$(CLI) build-renderer --profile "$${COMPAT_PROFILE}" >/dev/null

docker-ensure-renderer: mcp-env
	@$(CLI) ensure-renderer --profile "$${COMPAT_PROFILE}" >/dev/null

mcp-build: docker-ensure-renderer mcp-env
	@$(CLI) install-check --command "$${PWD}/$(CLI)" >/dev/null
	@$(CLI) factory-check >/dev/null

mcp-init: mcp-env
	@$(CLI) --project "$${PROJECT}" init >/dev/null

mcp-check: check
	@$(CLI) lifecycle-check --command "$${PWD}/$(CLI)" >/dev/null

docker-test: docker-ensure-renderer
	@DIAVISUALS_DOCKER_SMOKE=1 DIAVISUALS_MCP_SMOKE=1 DIAVISUALS_W1_DOCKER=1 $(PYTHON) -m unittest tests.test_docker_smoke tests.test_artifacts_runtime tests.test_runtime_selection_docker tests.test_d0_acceptance tests.test_job_storage_docker tests.test_smoke.SmokeDockerTest

mcp-smoke:
	@test -x "$(CLI)" || { printf 'Prepare Diavisuals first: make mcp-build\n' >&2; exit 2; }
	@"$(CLI)" mcp-smoke

tests-d0-published: mcp-env
	@DIAVISUALS_D0_PUBLISHED=1 $(PYTHON) -m unittest tests.test_d0_published

mcp-down:
	@$(CLI) --project "$${PROJECT}" down >/dev/null

mcp-stdio:
	@exec bash scripts/mcp-stdio-launcher "$${PWD}/$(CLI)"

project-check:
	@$(CLI) --project "$${PROJECT}" project-check

render-diagram:
	@test -n "$${INPUT}" || (printf 'Usage: make render-diagram INPUT=<diagram> OUTPUT=<output>\n' >&2; exit 2)
	@test -n "$${OUTPUT}" || (printf 'Usage: make render-diagram INPUT=<diagram> OUTPUT=<output>\n' >&2; exit 2)
	@$(CLI) --project "$${PROJECT}" render-diagram --engine "$${ENGINE}" --family "$${FAMILY}" --profile "$${COMPAT_PROFILE}" --format "$${FORMAT}" "$${INPUT}" "$${OUTPUT}"

render-examples:
	@tools/render-examples.sh "$${OUT_DIR}"

render-gallery: mcp-env
	@tools/render-gallery-docker.sh "$${COMPAT_PROFILE}"

render-gallery-local:
	@tools/render-gallery-local.sh "$${COMPAT_PROFILE}"

clean:
	@rm -rf dist .cache .tmp
