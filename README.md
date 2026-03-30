# ResearchOps Studio

ResearchOps Studio is a research workflow application that combines a chat-first interface with a multi-stage AI pipeline for retrieval, evidence packaging, report drafting, evaluation, and artifact export.

The repository is structured as a Python backend plus a React dashboard:

- `backend/`: FastAPI API, worker/orchestrator services, SQLAlchemy models, migrations, Docker assets
- `frontend/dashboard/`: React + Vite dashboard for projects, chat, reports, evidence, artifacts, and security flows
- `tests/`: backend unit/integration coverage plus Playwright end-to-end tests

## Why This Project Matters

This is not a single-model demo. The project includes:

- a staged research pipeline with retrieval, evidence packing, drafting, evaluation, repair, and export
- multi-tenant data modeling and auth flows including MFA
- evented run progress updates
- evidence and artifact handling
- a dashboard that supports project, conversation, report, and evaluation workflows

## Architecture

### Backend

- `backend/services/api/`: FastAPI application, routes, auth middleware, app services
- `backend/services/orchestrator/`: research pipeline graph, nodes, checkpointing, embeddings, worker integration
- `backend/services/workers/`: worker process entrypoint
- `backend/data/db/`: SQLAlchemy models, repositories, Alembic migrations, DB init
- `backend/libs/`: shared core/auth/config/observability/connectors/ingestion/retrieval logic

### Frontend

- `frontend/dashboard/src/pages/`: route-level pages
- `frontend/dashboard/src/features/chat/`: chat/report-specific components and utilities
- `frontend/dashboard/src/api/`: typed client hooks and request helpers
- `frontend/dashboard/src/components/`: shared layout and UI components

### Runtime Topology

- `postgres`: primary relational store, plus pgvector support
- `api`: FastAPI app for auth, projects, chat, runs, evidence, and artifacts
- `worker`: background research pipeline execution
- `frontend`: local Vite dev server in development, static build for production

## Local Setup

### Prerequisites

- Python 3.11 or newer
- Node.js 20 or newer
- npm
- PostgreSQL with pgvector for full local runs, or SQLite for some backend tests

### 1. Clone And Install Dependencies

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cd frontend/dashboard
npm ci
cd ../..
```

### 2. Configure Environment

Copy the example files and fill in the values you need:

```powershell
Copy-Item .env.example .env
Copy-Item frontend/dashboard/.env.example frontend/dashboard/.env
```

### 3. Run The Backend

```powershell
cd backend
python -m pytest ..\tests\backend\unit\test_api_health.py -q
python -m main
```

### 4. Run The Frontend

```powershell
cd frontend/dashboard
npm run dev
```

## Docker Setup

The backend includes a compose stack for Postgres, API, and worker:

```powershell
cd backend
docker compose -f deployment/compose.yaml up --build
```

This is the fastest path if you want the API, worker, and database wired together with the documented service topology.

## Demo Flow

To evaluate the project end to end:

1. Register or sign in.
2. Create a project.
3. Start a conversation and request a research report.
4. Track pipeline progress in chat and report views.
5. Review generated report sections, artifacts, and evidence.
6. Run evaluation and inspect grounding/faithfulness outputs.

## Validation Commands

Use the same interpreter you used for installation for Python commands.

### Frontend

```powershell
cd frontend/dashboard
npm run build
npm run lint
```

### Backend

```powershell
cd backend
python -m pytest ..\tests\backend\unit\test_api_health.py -q
python -m pytest ..\tests\backend\unit\test_chat_flow.py -q
```

### Playwright Discovery

```powershell
cd frontend/dashboard
npx playwright test --list
```

## Notable Engineering Areas

- staged orchestration graph for research execution
- retrieval and ingestion of external academic sources
- grounding and faithfulness evaluation flows
- multi-tenant persistence and audit-aware auth flows
- SSE-driven progress updates and artifact hydration in the UI

## Repository Notes

- `requirements.txt` is the root install path used by Docker and the documented local setup
- backend tests are safest to run with `python -m pytest` so the active interpreter matches the installed dependencies
- `frontend/dashboard/README.md` contains frontend-specific notes; this root README is the primary onboarding document
