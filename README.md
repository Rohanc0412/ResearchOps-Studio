# ResearchOps Studio

Backend production skeleton for ResearchOps: API + orchestrator + worker + Postgres (pgvector). Contracts/enforcement modules are included.

## Frontend (Dashboard)

A standalone React + Vite dashboard lives in `frontend/web`.

From repo root:

```powershell
npm --prefix frontend/web install
npm --prefix frontend/web run dev
```

Or from within `frontend/web`:

```powershell
cd frontend/web
npm install
npm run dev
```

Notes:
- Frontend uses `frontend/web/.env` for `VITE_API_BASE_URL` and `VITE_GOOGLE_CLIENT_ID`.
- Backend tuning overrides live in `backend/.env`.
- The API must allow the web origin (e.g. `http://localhost:5173`) via CORS for browser requests.

## What This Repo Does (Today)

- Exposes a small FastAPI service with run management and chat endpoints.
- Enqueues background jobs (`research.run`) into Postgres.
- Creates runs immediately from a research question (queued, current_stage=retrieve).
- Runs the research pipeline that produces report artifacts (OpenAlex + arXiv).
- Project runs (`POST /projects/{project_id}/runs`) execute the research pipeline for a question.

## Retrieval Connectors (Part 7)

- OpenAlex
- arXiv

## Prerequisites

- Docker Desktop (Compose v2)
- Python 3.11+ (optional, for running tests without Docker)

## One Command Local Run

From repo root:

```powershell
docker compose -f backend/infra/compose.yaml up --build
```

Stop and wipe local DB volume:

```powershell
docker compose -f backend/infra/compose.yaml down -v
```

## How To Trigger A Research Run (Windows PowerShell)

PowerShell's `curl` is an alias for `Invoke-WebRequest`, so use `Invoke-RestMethod`:

```powershell
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/healthz"

# Create a project (one-time)
$project = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/projects" `
  -ContentType "application/json" `
  -Body '{"name":"Demo Project"}'
$projectId = $project.id

# Create a research run
$run = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/projects/$projectId/runs" `
  -ContentType "application/json" `
  -Body '{"question":"Summarize recent work on retrieval-augmented generation","client_request_id":"demo-run-1"}'
$runId = $run.run_id

# Check status
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/runs/$runId"
```

Expected `GET /runs/{run_id}` fields:
- `status` should become `succeeded`
- `artifacts` should include the report output

## API Endpoints

### Health
- `GET /healthz` → `{ "status": "ok" }`

### Run Management
- `POST /projects/{project_id}/runs` - Create a run from a question (output_type is fixed to report)
- `GET /runs/{run_id}` - Run status + metadata (status, current_stage, timestamps, error info)
- `GET /runs/{run_id}/events` - List events as JSON or stream via SSE (see below)
- `POST /runs/{run_id}/cancel` - Request cancellation (cooperative)
- `POST /runs/{run_id}/retry` - Retry a failed or blocked run
- `GET /runs/{run_id}/artifacts` - List artifacts for run

Run creation request/response:
- Request body: `{ "question": "...", "client_request_id": "..." }` (output_type always `report`)
- Response body: `{ "run_id": "...", "status": "queued" }`
- Idempotency: reuse the same `client_request_id` to return the same `run_id`

## Architecture (Text Diagram)

```
client
  |
  v
backend/apps/api (FastAPI)
  |   \
  |    \ reads status/artifacts
  |     \
  v      v
db (Postgres + pgvector)
  ^
  |
backend/apps/workers (polls jobs table)
  |
  v
backend/apps/orchestrator (LangGraph)
  |
  v
artifacts table (dummy JSON payload)
```

## Configuration

All services load the shared repo `.env` via `backend/packages/core` settings (`pydantic-settings`).

Important env vars:
- `DATABASE_URL` (Compose sets this to Postgres service)
- `API_HOST`, `API_PORT`
- `WORKER_POLL_SECONDS`

LLM configuration (optional):
- `LLM_PROVIDER` = `hosted` (default `hosted`)
- `HOSTED_LLM_BASE_URL`, `HOSTED_LLM_API_KEY`, `HOSTED_LLM_MODEL`

OpenRouter example:
- `LLM_PROVIDER=hosted`
- `HOSTED_LLM_BASE_URL=https://openrouter.ai/api`
- `HOSTED_LLM_MODEL=xiaomi/mimo-v2-flash:free`
- `HOSTED_LLM_API_KEY=...`

## Auth Overview (JWT Access + Refresh)

Flow:
1) Frontend calls `POST /auth/login` with username + password.
2) API returns an **access token** (JWT) and sets a httpOnly refresh cookie.
3) Frontend calls the API with `Authorization: Bearer <access_token>`.

### Google Sign-In + MFA

- `POST /auth/google` exchanges a Google ID token for ResearchOps access/refresh tokens.
- If MFA is enabled for the user, login returns `{ mfa_required: true, mfa_token: "..." }`.
- Complete MFA with `POST /auth/mfa/verify` and the TOTP code.
- Manage MFA: `GET /auth/mfa/status`, `POST /auth/mfa/enroll/start`, `POST /auth/mfa/enroll/verify`, `POST /auth/mfa/disable`.

Fail-closed rules (default behavior):
- Missing/invalid token -> request is rejected.
- Missing `tenant_id` claim -> request is rejected.
- Cross-tenant resource access -> rejected (tenant-scoped queries return `404`).

### Required Claims

- `sub` (user id) **required**
- Tenant id claim **required**:
  - preferred: `https://researchops.ai/tenant_id`
  - fallback: `tenant_id`
- Roles (optional; defaults to `viewer`):
  - `roles`

### Auth Environment Variables

- `AUTH_REQUIRED` (default `true`)
- `DEV_BYPASS_AUTH` (default `false`, local only)
- `AUTH_JWT_SECRET` (required when `AUTH_REQUIRED=true` and no bypass)
- `AUTH_JWT_ISSUER` (default `researchops-api`)
- `AUTH_ACCESS_TOKEN_MINUTES` (default `30`)
- `AUTH_REFRESH_TOKEN_DAYS` (default `14`)
- `AUTH_REFRESH_COOKIE_NAME` (default `researchops_refresh`)
- `AUTH_REFRESH_COOKIE_SECURE` (default `false` in local, `true` elsewhere)
- `AUTH_REFRESH_COOKIE_SAMESITE` (default `lax`)
- `AUTH_REFRESH_TOKEN_SECRET` (optional; defaults to `AUTH_JWT_SECRET`)
- `AUTH_ALLOW_REGISTER` (default `true`)
- `AUTH_CLOCK_SKEW_SECONDS` (default `60`)
- `AUTH_MFA_CHALLENGE_MINUTES` (default `5`)
- `AUTH_MFA_TOTP_ISSUER` (default `ResearchOps Studio`)
- `AUTH_MFA_TOTP_PERIOD_SECONDS` (default `30`)
- `AUTH_MFA_TOTP_DIGITS` (default `6`)
- `AUTH_MFA_TOTP_WINDOW` (default `1`)
- `AUTH_GOOGLE_CLIENT_ID` (required for Google login)
- `AUTH_GOOGLE_ISSUER` (default `https://accounts.google.com`)
- `AUTH_GOOGLE_ALLOW_LINK_EXISTING` (default `true`)
- `AUTH_GOOGLE_JWKS_CACHE_SECONDS` (default `300`)

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

- Protected: `GET /me`, `POST /projects/{project_id}/runs`, `GET /runs/{run_id}`
- Public: `GET /health`, `GET /healthz`

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

`backend/packages/observability` configures structured JSON logs with correlation fields:
- `service`, `request_id`, `tenant_id`, `run_id`

## Database (Minimal, Production-Shaped)

SQLAlchemy models in `backend/db/models/`:
- `projects` (tenant-scoped workspace + last activity)
- `runs` (status/stage/budgets/errors)
- `run_events` (timeline stream)
- `sources` / `snapshots` / `snippets` / `snippet_embeddings` (immutable evidence + vector search)
- `artifacts` (blob metadata; binary data lives outside Postgres)
- `claim_map` (claim ↔ snippet enforcement storage)
- `jobs` (Postgres-backed queue, polled by worker)

Local pgvector is enabled via `backend/infra/docker/postgres/init/001_pgvector.sql`.

## Database and Memory Model (Part 4)

This schema is the UI truth layer for:
- Projects list + last activity
- Runs list + run viewer (status, stages, budgets, failure reasons)
- Live run events timeline
- Evidence (sources → immutable snapshots → citeable snippets + embeddings)
- Artifacts listing + download metadata (`blob_ref`)
- Claim maps for citation enforcement/debugging

Quickstart (local):
1) Start Postgres (Compose): `docker compose -f backend/infra/compose.yaml up --build`
2) `cd backend`
3) Set env vars: `DATABASE_URL` (Postgres) + auth vars as needed
4) Run migrations: `python -m alembic -c alembic.ini upgrade head`
5) Start API (PowerShell): `$env:PYTHONPATH="apps/api/src;packages/core/src;packages/observability/src;packages/citations/src;packages/llm/src;db"; python -m researchops_api.main`

Useful commands:
- Upgrade: `python -m alembic -c alembic.ini upgrade head`
- New revision (future): `python -m alembic -c alembic.ini revision -m "..." --autogenerate`

Tenant safety:
- Every tenant-owned table includes `tenant_id` and all queries are tenant-scoped.

Notes:
- `pgvector` extension is required (`CREATE EXTENSION IF NOT EXISTS vector`).
- Snapshots/artifacts store references (e.g. S3/local path) via `blob_ref` plus integrity hashes; blobs are not stored in Postgres.

## Repo Layout

- `frontend/web` React + Vite dashboard
- `backend/apps/api/src/researchops_api` FastAPI service
- `backend/apps/orchestrator/src/researchops_orchestrator` LangGraph research pipeline
- `backend/apps/workers/src/researchops_workers` job worker loop
- `backend/packages/core/src/researchops_core` shared models/constants/settings
- `backend/packages/observability/src/researchops_observability` logging + middleware
- `backend/packages/citations/src/researchops_citations` facade for Part 1 enforcement
- `backend/db/` database models + init
- `backend/infra/` Docker compose + Dockerfiles
- `backend/tests/unit` unit tests
- `backend/tests/integration` end-to-end run test (in-process)
- `backend/tests/golden` golden JSON fixtures for Part 1

## Dev Commands

- `make -C backend up` (Compose up)
- `make -C backend test` (pytest)
- `make -C backend fmt` (black)
- `make -C backend lint` (ruff)

## Running Tests Without Docker

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest
```

## Troubleshooting

- Postgres init races: schema creation uses a Postgres advisory lock (`backend/db/init_db.py`) so `api` and `worker` can start together safely.
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
- `run.created` - Run record created
- `run.queued` - Run queued for execution

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
# 1. Create a project
$project = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/projects" `
  -ContentType "application/json" `
  -Body '{"name":"Demo Project"}'
$projectId = $project.id

# 2. Create a run
$run = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/projects/$projectId/runs" `
  -ContentType "application/json" `
  -Body '{"question":"Summarize recent work on retrieval-augmented generation","client_request_id":"demo-run-1"}'
$runId = $run.run_id

# 3. Get run status
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/runs/$runId"

# 4. Stream events in real-time (use a separate terminal)
curl.exe -N -H "Accept: text/event-stream" "http://localhost:8000/runs/$runId/events"

# 5. Cancel the run (from main terminal)
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/runs/$runId/cancel"

# 6. Check final status
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/runs/$runId"
```

### Implementation Details

**State Machine:**
- Transitions are validated using `ALLOWED_TRANSITIONS` map
- Uses database row-level locking (`SELECT FOR UPDATE`) to prevent race conditions
- All state changes emit events atomically in the same transaction

**Event Emission:**
- Every stage emits at least `stage_start` and `stage_finish`
- Run setup emits `run.created` and `run.queued`
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

## Pipeline Spec (v3, in progress)

This README is the source of truth for the current pipeline behavior.

Stage 1 (Run setup):
- Creates a run immediately from a question
- Sets `status=queued` and `current_stage=retrieve`
- Output type is fixed to `report`
- Emits `run.created` and `run.queued` events
- Returns `{ "run_id": "...", "status": "queued" }`
