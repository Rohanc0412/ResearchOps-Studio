.PHONY: up down logs test fmt lint

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

