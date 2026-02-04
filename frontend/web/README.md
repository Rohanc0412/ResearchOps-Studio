# ResearchOps Studio (Web)

Production-grade React dashboard for ResearchOps Studio.

## Setup

```powershell
cd frontend/web
npm install
```

Edit `frontend/web/.env`:

- `VITE_API_BASE_URL` (e.g. `http://localhost:8000`)
- Recommended for local dev: set `VITE_API_BASE_URL=/api` (Vite dev proxy forwards to `http://localhost:8000`).

Run:

```powershell
npm run dev
```

## Backend Endpoints Used

- `GET /me`
- `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/register` (optional)
- `GET /projects`, `POST /projects`, `GET /projects/{project_id}`, `PATCH /projects/{project_id}`
- `POST /projects/{project_id}/runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/events` (SSE via authenticated fetch stream)
- `POST /runs/{run_id}/cancel`, `POST /runs/{run_id}/retry`
- `GET /runs/{run_id}/artifacts`
- `GET /artifacts/{artifact_id}/download`
- `GET /snippets/{snippet_id}`
- optional `GET /sources/{source_id}`

## CORS Note

The API must allow the web origin (e.g. `http://localhost:5173`) via CORS for browser requests.
