.PHONY: up down logs test fmt lint run-api

up:
\tdocker compose -f infra/compose.yaml up --build

down:
\tdocker compose -f infra/compose.yaml down -v

logs:
\tdocker compose -f infra/compose.yaml logs -f

test:
\tpython -m pytest

fmt:
\tpython -m black .

lint:
\tpython -m ruff check .

run-api:
\tPYTHONPATH=./apps/api/src:./packages/core/src:./packages/observability/src:./db \
\tLOG_LEVEL=$${LOG_LEVEL:-INFO} LOG_FORMAT=$${LOG_FORMAT:-pretty} \
\tpython -m researchops_api.main

