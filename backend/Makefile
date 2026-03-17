.PHONY: up down logs test fmt lint run-api

up:
\tdocker compose -f deployment/compose.yaml up --build

down:
\tdocker compose -f deployment/compose.yaml down -v

logs:
\tdocker compose -f deployment/compose.yaml logs -f

test:
\tpython -m pytest

fmt:
\tpython -m black .

lint:
\tpython -m ruff check .

run-api:
\tPYTHONPATH=./services/api/src:./libs/core/src:./libs/observability/src:./libs/research_rules:./data \
\tLOG_LEVEL=$${LOG_LEVEL:-INFO} LOG_FORMAT=$${LOG_FORMAT:-pretty} \
\tpython -m researchops_api.main

