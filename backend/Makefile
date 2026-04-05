.PHONY: up up-doppler down logs test fmt lint run-api run-worker dev

up:
	docker compose -f deployment/compose.yaml up --build

up-doppler:
	doppler run -- docker compose -f deployment/compose.yaml up --build

down:
	docker compose -f deployment/compose.yaml down -v

logs:
	docker compose -f deployment/compose.yaml logs -f

test:
	python -m pytest

fmt:
	python -m black .

lint:
	python -m ruff check .

run-api:
	PYTHONPATH=./services/api:./libs:./libs/research_rules:./data \
	LOG_LEVEL=$${LOG_LEVEL:-INFO} LOG_FORMAT=$${LOG_FORMAT:-pretty} \
	python -m main

run-worker:
	PYTHONPATH=./services/workers:./services/orchestrator:./libs:./libs/research_rules:./data \
	LOG_LEVEL=$${LOG_LEVEL:-INFO} LOG_FORMAT=$${LOG_FORMAT:-pretty} \
	python -m main

dev:
	doppler run -- python ../scripts/dev.py
