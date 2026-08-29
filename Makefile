# =============================================================================
# Enterprise Data & AI Integration Platform
#
#   make setup      install python dependencies
#   make build      build the local warehouse from sample data
#   make up         start the whole platform (docker compose)
#   make run        start the whole platform (no docker)
#   make smoke      end-to-end demonstration against a running stack
#   make test       run the full test suite
#   make dq         run the data quality rule catalogue
#   make lint       ruff + SQL lint + API spec validation
#   make verify     everything CI runs, locally
# =============================================================================
SHELL := /bin/bash
PY    ?= python3
export PYTHONPATH := $(CURDIR):$(CURDIR)/services

.DEFAULT_GOAL := help
.PHONY: help setup env data build up down run stop smoke test test-unit test-api test-data \
        test-ai dq lint lint-py lint-sql lint-spec verify clean logs

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Install python dependencies
	$(PY) -m pip install -r requirements-dev.txt

env: ## Create .env from the template if it does not exist
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")

data: ## Regenerate the deterministic sample dataset
	$(PY) scripts/generate_sample_data.py

build: env ## Build the local warehouse (RAW -> STAGING -> CORE -> ANALYTICS -> AI)
	WAREHOUSE_ACCESS=direct $(PY) -m local_warehouse.build --verify

up: env ## Start the platform with docker compose
	docker compose up -d --build
	@echo "experience API: http://localhost:8080/docs"

down: ## Stop the docker compose stack
	docker compose down -v

run: env ## Start the platform without docker
	./scripts/run_local.sh

stop: ## Stop the non-docker stack
	./scripts/run_local.sh stop

logs: ## Tail the non-docker logs
	tail -f .run/*.log

smoke: ## End-to-end demonstration against a running stack
	./scripts/smoke_test.sh

dq: ## Run the data quality rule catalogue
	WAREHOUSE_ACCESS=direct $(PY) -m local_warehouse.dq_runner

test: ## Run every test suite
	WAREHOUSE_ACCESS=direct $(PY) -m pytest tests -q

test-unit: ## Unit tests only
	WAREHOUSE_ACCESS=direct $(PY) -m pytest tests/unit -q

test-api: ## API contract and behaviour tests
	WAREHOUSE_ACCESS=direct $(PY) -m pytest tests/api -q

test-data: ## Warehouse and data quality tests
	WAREHOUSE_ACCESS=direct $(PY) -m pytest tests/data -q

test-ai: ## AI evaluation suite
	WAREHOUSE_ACCESS=direct $(PY) -m pytest tests/ai -q

lint: lint-py lint-sql lint-spec ## All linters

lint-py:
	$(PY) -m ruff check services local_warehouse scripts tests

lint-sql:
	$(PY) scripts/lint_sql.py

lint-spec:
	$(PY) scripts/validate_api_specs.py

verify: build lint test dq ## Everything CI runs
	@echo "verification complete"

clean: ## Remove build artefacts and the local warehouse
	rm -rf .run local_warehouse/*.duckdb local_warehouse/*.wal .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
