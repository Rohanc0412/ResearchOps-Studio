# ResearchOps Studio

Backend production skeleton for ResearchOps: API + orchestrator + worker + Postgres (pgvector). Part 1 (contracts/enforcement) is included.

## Frontend (Dashboard)

A standalone React + Vite dashboard lives in `apps/web`.

```powershell
cd apps/web
npm install
npm run dev
```

Notes:
- Configure OIDC env vars in `apps/web/.env` (issuer, client id, redirect uri).
- The API must allow the web origin (e.g. `http://localhost:5173`) via CORS for browser requests.

### Local OIDC (Keycloak)

Run API + DB + Keycloak with real OIDC validation:

```powershell
docker compose -f infra/compose.yaml -f infra/compose.oidc.yaml up --build
```

Keycloak:
- Admin UI: `http://keycloak.localhost:8080` (admin/admin)
- Dev user: `dev-admin` / `dev-admin`

Issuer:
- `http://keycloak.localhost:8080/realms/researchops`

## What This Repo Does (Today)

- Exposes a small FastAPI service with run management endpoints.
- Enqueues a background job (`hello.run`) into Postgres.
- Runs a minimal LangGraph pipeline that writes a dummy artifact and marks the run succeeded.

## Prerequisites

- Docker Desktop (Compose v2)
- Python 3.11+ (optional, for running tests without Docker)

## One Command Local Run

From repo root:

```powershell
docker compose -f infra/compose.yaml up --build
```

Stop and wipe local DB volume:

```powershell
docker compose -f infra/compose.yaml down -v
```

## How To Trigger The Hello Run (Windows PowerShell)

PowerShell’s `curl` is an alias for `Invoke-WebRequest`, so use `Invoke-RestMethod`:

```powershell
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/healthz"
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/version"
$r = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/runs/hello"
$runId = $r.run_id
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/runs/$runId"
```

Expected `GET /runs/{run_id}` fields:
- `status` should become `succeeded`
- `artifacts[0].artifact_type` should be `hello`

## API Endpoints

- `GET /healthz` → `{ "status": "ok" }`
- `GET /version` → `{ "name": "...", "git_sha": "...", "build_time": "..." }`
- `POST /runs/hello` → `{ "run_id": "<uuid>" }`
- `GET /runs/{run_id}` → run status + artifact metadata

## Architecture (Text Diagram)

```
client
  |
  v
apps/api (FastAPI)
  |   \
  |    \ reads status/artifacts
  |     \
  v      v
db (Postgres + pgvector)
  ^
  |
apps/workers (polls jobs table)
  |
  v
apps/orchestrator (LangGraph)
  |
  v
artifacts table (dummy JSON payload)
```

## Configuration

All services use `packages/core` settings (`pydantic-settings`, `.env` supported).

Important env vars:
- `DATABASE_URL` (Compose sets this to Postgres service)
- `LOG_LEVEL` (default `INFO`)
- `API_HOST`, `API_PORT`
- `WORKER_POLL_SECONDS`

## Auth Overview (OIDC + JWT)

Flow:
1) Your frontend authenticates with an OIDC provider (Keycloak/Auth0/etc).
2) Frontend receives an **access token** (JWT).
3) Frontend calls the API with `Authorization: Bearer <access_token>`.

Fail-closed rules (default behavior):
- Missing/invalid token → request is rejected.
- Missing `tenant_id` claim → request is rejected.
- Cross-tenant resource access → rejected (tenant-scoped queries return `404`).

### Required Claims

- `sub` (user id) **required**
- Tenant id claim **required**:
  - preferred: `https://researchops.ai/tenant_id`
  - fallback: `tenant_id`
- Roles (optional; defaults to `viewer`):
  - `roles`
  - or `realm_access.roles`
  - or `resource_access.<client>.roles` (Keycloak style)

### Auth Environment Variables

- `AUTH_REQUIRED` (default `true`)
- `DEV_BYPASS_AUTH` (default `false`, local only)
- `OIDC_ISSUER` (required when `AUTH_REQUIRED=true` and no bypass)
- `OIDC_AUDIENCE` (required when `AUTH_REQUIRED=true` and no bypass)
- `OIDC_JWKS_CACHE_SECONDS` (default `300`)
- `OIDC_CLOCK_SKEW_SECONDS` (default `60`)

### Local Development Notes

Docker Compose sets `DEV_BYPASS_AUTH=true` for local runs, so you can call protected endpoints without a real IdP.
You can still simulate identities via headers:

- `X-Dev-User-Id: dev-user`
- `X-Dev-Tenant-Id: 00000000-0000-0000-0000-000000000001`
- `X-Dev-Roles: owner,admin,researcher,viewer`

### RBAC Roles

- `viewer`: read-only (cannot start runs)
- `researcher`: can start runs and export artifacts
- `admin`: researcher privileges + admin-only endpoints
- `owner`: full access

Enforced server-side in code (never trust the client).

### Protected Endpoints

- Protected: `GET /me`, `GET /tenants/current`, `POST /runs/hello`, `GET /runs/{run_id}`, `GET /auth/jwks-status`
- Public: `GET /health`, `GET /healthz`, `GET /version`

## Audit Logs

Sensitive operations write to `audit_logs` within the same DB transaction.

Recorded fields include:
- who: `actor_user_id`
- tenant: `tenant_id`
- what: `action`, `target_type`, `target_id`
- context: `ip`, `user_agent`, `request_id`, `created_at`, `metadata`

Example query (Postgres):

```sql
SELECT created_at, actor_user_id, action, target_type, target_id, metadata
FROM audit_logs
WHERE tenant_id = '00000000-0000-0000-0000-000000000001'
ORDER BY created_at DESC
LIMIT 50;
```

## Logging

`packages/observability` configures structured JSON logs with correlation fields:
- `service`, `request_id`, `tenant_id`, `run_id`

## Database (Minimal, Production-Shaped)

SQLAlchemy models in `db/models/`:
- `projects` (tenant-scoped workspace + last activity)
- `runs` (status/stage/budgets/errors)
- `run_events` (timeline stream)
- `sources` / `snapshots` / `snippets` / `snippet_embeddings` (immutable evidence + vector search)
- `artifacts` (blob metadata; binary data lives outside Postgres)
- `claim_map` (claim ↔ snippet enforcement storage)
- `jobs` (Postgres-backed queue, polled by worker)

Local pgvector is enabled via `infra/docker/postgres/init/001_pgvector.sql`.

## Database and Memory Model (Part 4)

This schema is the UI truth layer for:
- Projects list + last activity
- Runs list + run viewer (status, stages, budgets, failure reasons)
- Live run events timeline
- Evidence (sources → immutable snapshots → citeable snippets + embeddings)
- Artifacts listing + download metadata (`blob_ref`)
- Claim maps for citation enforcement/debugging

Quickstart (local):
1) Start Postgres (Compose): `docker compose -f infra/compose.yaml up --build`
2) Set env vars: `DATABASE_URL` (Postgres) + auth vars as needed
3) Run migrations: `python -m alembic -c alembic.ini upgrade head`
4) Start API (PowerShell): `$env:PYTHONPATH="apps/api/src;packages/core/src;packages/observability/src;packages/citations/src;."; python -m researchops_api.main`

Useful commands:
- Upgrade: `python -m alembic -c alembic.ini upgrade head`
- New revision (future): `python -m alembic -c alembic.ini revision -m "..." --autogenerate`

Tenant safety:
- Every tenant-owned table includes `tenant_id` and all queries are tenant-scoped.

Notes:
- `pgvector` extension is required (`CREATE EXTENSION IF NOT EXISTS vector`).
- Snapshots/artifacts store references (e.g. S3/local path) via `blob_ref` plus integrity hashes; blobs are not stored in Postgres.

## Repo Layout

- `apps/api/src/researchops_api` FastAPI service
- `apps/orchestrator/src/researchops_orchestrator` LangGraph hello pipeline
- `apps/workers/src/researchops_workers` job worker loop
- `packages/core/src/researchops_core` shared models/constants/settings
- `packages/observability/src/researchops_observability` logging + middleware
- `packages/citations/src/researchops_citations` facade for Part 1 enforcement
- `db/` database models + init
- `infra/` Docker compose + Dockerfiles
- `tests/unit` unit tests
- `tests/integration` end-to-end “hello run” test (in-process)
- `tests/golden` golden JSON fixtures for Part 1

## Dev Commands

- `make up` (Compose up)
- `make test` (pytest)
- `make fmt` (black)
- `make lint` (ruff)

## Running Tests Without Docker

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest
```

## Troubleshooting

- Postgres init races: schema creation uses a Postgres advisory lock (`db/init_db.py`) so `api` and `worker` can start together safely.
- PowerShell script execution blocked: run scripts with `powershell -NoProfile -ExecutionPolicy Bypass -File ...`.
- Line endings: `.gitattributes` is configured so `core.autocrlf=true` works on Windows without noisy diffs.

## Part 1 Contract

The Part 1 contract and enforcement config are in `SPEC.md` and `claim_policy.yaml` (strict, fail-closed).
