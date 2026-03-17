# Project Structure

This repository is now organized by responsibility instead of by mixed technical history.

## Top Level

- `frontend/`
  - UI workspace and dashboard app.
- `backend/`
  - API, worker, orchestration, shared Python libraries, and database package.

## Frontend

- `frontend/dashboard/`
  - Main React + Vite application.
- `frontend/package.json`
  - Workspace-level shortcuts for frontend commands.

## Backend

- `backend/services/`
  - Runnable application services.
- `backend/services/api/`
  - FastAPI application.
- `backend/services/orchestrator/`
  - Research pipeline orchestration graph and nodes.
- `backend/services/workers/`
  - Background job worker.

- `backend/libraries/`
  - Reusable Python libraries shared by services.
- `backend/libraries/core/`
  - Settings, auth, run lifecycle, shared models, tenancy.
- `backend/libraries/observability/`
  - Logging, request IDs, runtime context.
- `backend/libraries/connectors/`
  - External source connectors such as OpenAlex and arXiv.
- `backend/libraries/ingestion/`
  - Sanitization, chunking, embedding, ingestion pipeline.
- `backend/libraries/retrieval/`
  - Retrieval and snippet lookup helpers.
- `backend/libraries/llm/`
  - LLM client and response-format helpers.
- `backend/libraries/citations/`
  - Citation and enforcement facade.
- `backend/libraries/research_rules/`
  - Contracts, enforcement rules, and low-level shared utilities.

- `backend/data/`
  - Database-related code and migrations.
- `backend/data/db/`
  - Importable `db` package with models, services, Alembic, and init code.

- `backend/deployment/`
  - Local deployment assets.
- `backend/deployment/compose.yaml`
  - Docker Compose for local stack.
- `backend/deployment/docker/`
  - API/worker Dockerfiles and Postgres init scripts.

- `backend/tests/`
  - Unit and integration tests.
- `backend/scripts/`
  - Setup and verification scripts.

## Why This Layout

- `services` answers: "What can I run?"
- `libraries` answers: "What code is shared?"
- `data` answers: "Where is the database layer?"
- `deployment` answers: "How do I start the stack?"
