# ResearchOps Studio (Web)

Production-grade React dashboard for ResearchOps Studio.

## Setup

```powershell
cd frontend/web
npm install
```

Edit the shared repo `.env`:

- `VITE_API_BASE_URL` (e.g. `http://localhost:8000`)
- Recommended for local dev: set `VITE_API_BASE_URL=/api` (Vite dev proxy forwards to `http://localhost:8000`).
- `VITE_OIDC_ISSUER`
- `VITE_OIDC_CLIENT_ID`
- `VITE_OIDC_REDIRECT_URI` (must match OIDC client redirect)
- optional `VITE_OIDC_POST_LOGOUT_REDIRECT_URI`

Run:

```powershell
npm run dev
```

## Backend Endpoints Used

- `GET /me`
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

## Local OIDC (Keycloak)

Run API + DB + Keycloak with real OIDC validation:

```powershell
docker compose -f backend/infra/compose.yaml -f backend/infra/compose.oidc.yaml up --build
```

Keycloak:
- Admin UI: `http://keycloak.localhost:8080` (admin/admin)
- Dev user: `dev-admin` / `dev-admin`

Issuer:
- `http://keycloak.localhost:8080/realms/researchops`
