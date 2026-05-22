# contract-lint — developer tasks
# Usage: make <target>   (run `make help` for the list)

PYTHON ?= python3
VERSION ?= 0.2.0
WHEEL_GLOB := dist/*.whl

.DEFAULT_GOAL := help

.PHONY: help install test test-quick coverage typecheck build smoke spec-check release clean

help: ## Show this help
	@echo "contract-lint targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Editable install with dev extras
	$(PYTHON) -m pip install -e ".[dev]"

test: ## Run the full test suite
	$(PYTHON) -m pytest

test-quick: ## Fast subset (stop on first failure)
	$(PYTHON) -m pytest -x

coverage: ## Run tests under coverage and print a report
	$(PYTHON) -m coverage run -m pytest
	$(PYTHON) -m coverage report -m
	$(PYTHON) -m coverage html

typecheck: ## mypy --strict on the CLI module
	$(PYTHON) -m mypy --strict contract_lint_cli.py

build: ## Build wheel + sdist into dist/
	rm -rf dist
	$(PYTHON) -m build

smoke: build ## Build, install the wheel in a clean venv, and run it
	rm -rf .smoke-venv
	$(PYTHON) -m venv .smoke-venv
	.smoke-venv/bin/python -m pip install --quiet --upgrade pip
	.smoke-venv/bin/python -m pip install --quiet $(WHEEL_GLOB)
	.smoke-venv/bin/contract-lint --version
	.smoke-venv/bin/contract-lint demo
	rm -rf .smoke-venv
	@echo "smoke OK"

spec-check: ## Validate the --json/SARIF/rules output against docs/spec schemas (offline)
	$(PYTHON) -m pytest tests/test_schema_conformance.py -v

release: ## Tag and prepare a release: make release VERSION=X.Y.Z
	$(PYTHON) scripts/release.py $(VERSION)

clean: ## Remove build/test artifacts
	rm -rf dist build .pytest_cache .mypy_cache htmlcov .coverage coverage.xml
	rm -rf *.egg-info .smoke-venv
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
