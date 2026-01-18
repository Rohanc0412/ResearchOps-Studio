# ResearchOps Studio

Backend production skeleton for ResearchOps: API + orchestrator + worker + Postgres (pgvector). Part 1 (contracts/enforcement) is included.

## Frontend (Dashboard)

A standalone React + Vite dashboard lives in `apps/web`.

From repo root:

```powershell
npm --prefix apps/web install
npm run dev
```

Or from within `apps/web`:

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

### Health & Version
- `GET /healthz` → `{ "status": "ok" }`
- `GET /version` → `{ "name": "...", "git_sha": "...", "build_time": "..." }`

### Run Management
- `POST /runs/hello` → `{ "run_id": "<uuid>" }` - Enqueue a hello test run
- `GET /runs/{run_id}` → Run status + metadata (status, current_stage, timestamps, error info)
- `GET /runs/{run_id}/events` → List events as JSON or stream via SSE (see below)
- `POST /runs/{run_id}/cancel` → Request cancellation (cooperative)
- `POST /runs/{run_id}/retry` → Retry a failed or blocked run
- `GET /runs/{run_id}/artifacts` → List artifacts for run
- `GET /runs/{run_id}/claims` → List claim map entries for run

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

## Runs and Live Timeline (SSE Streaming)

ResearchOps Studio implements a production-grade run lifecycle state machine with Server-Sent Events (SSE) streaming for real-time UI updates.

### Run States

A run progresses through the following states:

- `created` → Initial state when run is created
- `queued` → Waiting for worker to pick up
- `running` → Actively executing pipeline stages
- `blocked` → Paused waiting for external input (future use)
- `failed` → Execution failed with error
- `succeeded` → Completed successfully
- `canceled` → User canceled or system stopped

State transitions are validated and enforced. Only allowed transitions can occur (e.g., you cannot go from `succeeded` back to `running`).

### Run Stages

During execution, runs progress through stages. The current stage is stored in `runs.current_stage`:

- `retrieve` → Fetching sources/evidence
- `ingest` → Processing and chunking content
- `outline` → Generating document structure
- `draft` → Writing content
- `validate` → Checking quality/constraints
- `factcheck` → Verifying claims against evidence
- `export` → Generating final artifacts

### Run Events Timeline

Every stage emits events that are persisted in the `run_events` table:

- `stage_start` - Beginning of a stage
- `stage_finish` - Completion of a stage
- `log` - Informational messages during execution
- `error` - Errors with error_code and reason
- `state` - State transitions (created→queued, running→succeeded, etc.)

Each event has:
- `event_number` - Sequential ID for SSE Last-Event-ID support
- `ts` - Timestamp
- `level` - info/warn/error
- `stage` - Which stage emitted this event
- `message` - Human-readable description
- `payload_json` - Structured metadata

### SSE Streaming API

The Run Viewer UI streams events in real-time using Server-Sent Events.

#### Basic Streaming

Stream all events for a run:

```bash
curl -N -H "Accept: text/event-stream" http://localhost:8000/runs/<RUN_ID>/events
```

Output format:
```
id: 1
event: run_event
data: {"id":1,"ts":"2026-01-17T12:00:00Z","level":"info","stage":"retrieve","event_type":"stage_start","message":"Starting stage: retrieve","payload":{}}

id: 2
event: run_event
data: {"id":2,"ts":"2026-01-17T12:00:05Z","level":"info","stage":"retrieve","event_type":"stage_finish","message":"Finished stage: retrieve","payload":{"duration":5.2}}
```

#### Reconnect-Safe Streaming (Last-Event-ID)

If the connection drops, reconnect and resume from where you left off:

```bash
# Browser automatically sends Last-Event-ID header on reconnect
# Manual example:
curl -N \
  -H "Accept: text/event-stream" \
  -H "Last-Event-ID: 10" \
  http://localhost:8000/runs/<RUN_ID>/events
```

The server will only send events with `event_number > 10`.

#### Query Parameter Alternative

You can also use `?after_id=<event_number>`:

```bash
curl -N -H "Accept: text/event-stream" \
  "http://localhost:8000/runs/<RUN_ID>/events?after_id=10"
```

This is useful when Last-Event-ID header is not available.

#### JSON Mode (No Streaming)

Get all events as JSON array:

```bash
curl http://localhost:8000/runs/<RUN_ID>/events
```

Or get events after a specific event number:

```bash
curl "http://localhost:8000/runs/<RUN_ID>/events?after_id=10"
```

### Canceling Runs

Request cancellation of a running job:

```bash
curl -X POST http://localhost:8000/runs/<RUN_ID>/cancel
```

**Cancellation behavior:**
- **Queued runs**: Immediately transition to `canceled`
- **Running runs**: Set `cancel_requested_at` timestamp for cooperative cancellation
  - Worker checks the flag between stages
  - When detected, emits a canceled event and stops execution
- **Terminal runs** (succeeded/failed/canceled): No-op, returns success

### Retrying Failed Runs

Retry a run that failed or got blocked:

```bash
curl -X POST http://localhost:8000/runs/<RUN_ID>/retry
```

**Retry behavior:**
- Only works for runs in `failed` or `blocked` status
- Increments `retry_count`
- Clears `failure_reason`, `error_code`, `finished_at`
- Resets status to `queued`
- Clears `cancel_requested_at` if set
- Re-enqueues the job for execution

### Complete Example: Create, Monitor, Cancel

```powershell
# 1. Create a run
$r = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/runs/hello"
$runId = $r.run_id

# 2. Get run status
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/runs/$runId"

# 3. Stream events in real-time (use a separate terminal)
curl.exe -N -H "Accept: text/event-stream" "http://localhost:8000/runs/$runId/events"

# 4. Cancel the run (from main terminal)
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/runs/$runId/cancel"

# 5. Check final status
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/runs/$runId"
```

### Implementation Details

**State Machine:**
- Transitions are validated using `ALLOWED_TRANSITIONS` map
- Uses database row-level locking (`SELECT FOR UPDATE`) to prevent race conditions
- All state changes emit events atomically in the same transaction

**Event Emission:**
- Every stage emits at least `stage_start` and `stage_finish`
- Failures emit `error` event with structured error_code and reason
- Idempotent: emitting `stage_start` twice for the same stage is safe

**SSE Streaming:**
- Polls database every 500ms for new events
- Uses `event_number` (sequential) for reliable cursor-based pagination
- Supports both `Last-Event-ID` header and `?after_id` query param
- Automatically closes stream after terminal state + grace period

**Concurrency:**
- Multiple clients can stream the same run simultaneously
- State transitions are serialized via row locks
- Event numbers are assigned from a PostgreSQL sequence (globally unique)

## Part 1 Contract

The Part 1 contract and enforcement config are in `SPEC.md` and `claim_policy.yaml` (strict, fail-closed).
