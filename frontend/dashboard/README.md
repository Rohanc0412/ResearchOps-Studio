# ResearchOps Studio (Web)

Production-grade React dashboard for ResearchOps Studio.

## Setup

```powershell
cd C:\Projects\ResearchOps-Studio\frontend\dashboard
npm install
```

The frontend reads `VITE_` variables from the repo root `.env` because Vite is configured with `envDir` pointing at the repository root. Do not create a frontend-local `.env` file.

- Put non-secret frontend values such as `VITE_API_BASE_URL=/api` in [`.env`](C:/Projects/ResearchOps-Studio/.env).
- Provide secrets through Doppler when running the repo-level dev command.

Run:

```powershell
cd C:\Projects\ResearchOps-Studio
doppler run -- python scripts/dev.py
```

To run only the frontend:

```powershell
cd C:\Projects\ResearchOps-Studio\frontend\dashboard
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
