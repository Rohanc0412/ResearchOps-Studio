# ResearchOps Studio — End-to-End Test Report

**Date:** 2026-03-27
**Tester:** Automated Playwright browser testing
**Branch:** main
**Environment:** Local development (`localhost:5173` / `localhost:8000`)
**Auth user tested:** `newuser@test.com`

---

## Environment Setup

| Component | Status | Notes |
|-----------|--------|-------|
| Frontend (Vite) | ✅ Running | `localhost:5173` |
| Backend API (FastAPI) | ✅ Running | `localhost:8000`, local Python process |
| PostgreSQL | ✅ Running | Docker container (`pgvector/pgvector:pg16`) |
| Worker service | ❌ Not running | Must be started separately; required for research runs to complete |
| LLM provider | ✅ Configured | OpenRouter (`gpt-4o-mini`) via `hosted` provider |

---

## Test Results Summary

| Area | Status | Bugs Found |
|------|--------|------------|
| Authentication | ✅ Pass | 2 minor |
| Projects | ✅ Pass | 0 |
| Chat / LLM | ✅ Pass | 1 UX |
| Research runs | ⚠️ Partial | 1 blocker (worker) |
| Artifacts | ⚠️ Partial | Cannot verify without worker |
| Evidence | ✅ Pass | 0 |
| Security / MFA | ⚠️ Partial | 3 bugs |
| Navigation / Layout | ✅ Pass | 1 minor |

---

## Detailed Findings

### 1. Authentication

**Tested:** Login, registration, logout, invalid credentials, token refresh.

**Works:**
- Login form renders at `/login` with username/email + password fields
- New account creation via "Create one" → registration form → successful sign-up
- Valid credentials → JWT stored in `localStorage` as `researchops_access_token` → redirect to `/projects`
- Logout clears auth token and redirects to `/login`
- Visiting a protected route while unauthenticated redirects to login

**Bugs:**

> 🐛 **BUG-01: Forgot password button has no implementation**
> Clicking "Forgot password?" on the login page produces no visible action. No modal, no redirect, no backend endpoint. Users who forget their password have no recovery path.

> 🐛 **BUG-02: Double 401 console error on logout**
> After logout, the app fires two failed `/api/auth/refresh` requests (HTTP 401) to the console. The token has already been cleared, but the refresh interceptor still fires twice before the redirect completes. Benign to users but indicates a race condition in the auth refresh logic.

---

### 2. Projects

**Tested:** Projects list, create project, navigate to project.

**Works:**
- `/projects` renders a list of all user projects with names and icons
- "New project" button opens a modal with name + optional description fields
- Creating a project succeeds, adds it to the list, and navigates to the new project
- Clicking an existing project in the sidebar navigates to `/projects/:projectId`

**No bugs found.**

---

### 3. Chat / LLM

**Tested:** Send message, receive response, message rendering, research arm toggle.

**Works:**
- Chat interface renders within a project at `/projects/:projectId/chats/:chatId`
- Typing a message and pressing send delivers it to the backend
- The backend calls OpenRouter (`gpt-4o-mini`) and streams a response back
- Responses are rendered as formatted markdown (bold, lists, code blocks)
- Message history persists across page navigation

**Bug:**

> 🐛 **BUG-03: "Run research report" toggle UX is ambiguous**
> The purple "Run research report" button arms the **next** chat message with `force_pipeline: true` — it is a toggle, not an immediate action. However:
> - There is no persistent visual indicator showing the pipeline is armed while composing the message
> - The button's label does not communicate that you still need to send a message
> - Users can click it and then navigate away, silently disarming it with no feedback
> **Suggestion:** Show a persistent banner or change the input placeholder to "Describe your research topic..." while the pipeline is armed.

---

### 4. Research Runs

**Tested:** Trigger pipeline, progress card display, step states.

**Works:**
- Sending a message with `force_pipeline: true` creates a run record in the database
- The `ResearchProgressCard` component appears in the chat and shows the animated pipeline UI:
  - Numbered steps with connector lines
  - Active step has halo pulse animation
  - Progress bar with shimmer animation
  - Animated letter-wave on active step label
  - "Live research progress" subtitle with blinking dot

**Blocker:**

> ⛔ **BUG-04: Worker service not running — runs never complete**
> The worker service (`backend/services/worker/`) is responsible for consuming queued runs and executing the research pipeline (retrieval → outline → claims → evaluation). It must be started as a separate process and is **not** included in the standard dev startup path.
> During testing, triggered runs remained in `queued` status indefinitely. The progress card stayed frozen at Step 1 (Retrieval).
> **Impact:** The end-to-end research flow — the core product feature — cannot be tested without the worker running.
> **To fix for local dev:** Document a single startup command (e.g., `make dev` or a `Procfile`) that starts the API, worker, and frontend together.

---

### 5. Artifacts

**Tested:** Navigate to `/runs/:runId/artifacts`.

**Works:**
- The page route resolves and renders correctly
- The page layout (title, back navigation) renders

**Cannot verify:**
- Artifact content (report, sources, citations) cannot be verified without a completed run (worker not running)

---

### 6. Evidence / Snippets

**Tested:** Navigate to `/evidence/snippets/:snippetId`.

**Works:**
- The route resolves and page renders correctly
- The snippet viewer layout renders

**Note:** Could not verify snippet content without a completed research run to generate evidence.

---

### 7. Security / MFA

**Tested:** MFA enable flow, wrong code submission, error display.

**Works:**
- `/security` page renders with "Authenticator app (TOTP)" section
- Clicking "Enable MFA" shows the enrollment panel with:
  - Secret key (copyable)
  - OTP URI
  - Issuer, account, period metadata
  - Verification code input

**Bugs:**

> 🐛 **BUG-05: No QR code for MFA setup**
> The TOTP enrollment panel shows the secret key and OTP URI as plain text, but does not render a QR code. The vast majority of TOTP authenticator apps (Google Authenticator, Authy, 1Password, etc.) are primarily designed for QR code scanning. Manual secret entry is an error-prone fallback. A QR code rendered from the OTP URI would significantly improve usability.

> 🐛 **BUG-06: MFA error message is generic**
> Submitting an incorrect TOTP code shows: `"Security error — API request failed (401)"`. This raw HTTP error leaks implementation detail and provides no actionable guidance.
> **Expected:** `"Invalid code. Please check your authenticator app and try again."`

> 🐛 **BUG-07: Verification code input not cleared after failed attempt**
> After a failed TOTP verification, the wrong code (`999999`) remains in the input field. The user must manually clear it before entering the correct code. The input should be cleared and focused automatically after a failed attempt.

---

### 8. Navigation & Layout

**Tested:** Sidebar collapse/expand, routing between pages.

**Works:**
- Sidebar collapses to icon-only mode; expands back to full labels
- All navigation links route correctly
- The `v0.1` version label displays at the sidebar footer
- Page titles update correctly in the browser tab

**Minor issue:**

> 🐛 **BUG-08: No favicon**
> The browser tab shows the default browser icon. A favicon has not been configured. Cosmetic, but noticeable.

---

## Console Warnings (non-critical)

| Warning | Source | Severity |
|---------|--------|----------|
| `React Router Future Flag Warning` (v7 behavior changes) | `react-router-dom` | Low — technical debt, no user impact |
| `Download the React DevTools` info message | React | Informational only |

---

## Bug Summary

| ID | Severity | Area | Description |
|----|----------|------|-------------|
| BUG-01 | Medium | Auth | "Forgot password" has no implementation |
| BUG-02 | Low | Auth | Double 401 error on logout (console only) |
| BUG-03 | Medium | Chat | "Run research report" toggle UX is unclear |
| BUG-04 | **Critical** | Worker | Worker not in dev startup; runs never complete |
| BUG-05 | Medium | MFA | No QR code for TOTP enrollment |
| BUG-06 | Medium | MFA | Generic error message on wrong TOTP code |
| BUG-07 | Low | MFA | Input not cleared after failed TOTP attempt |
| BUG-08 | Low | UI | Missing favicon |

---

## Recommendations (Priority Order)

1. **Add the worker to the dev startup** — Create a `Makefile`, `Procfile`, or `docker-compose` entry that starts the API + worker + frontend with one command. The research pipeline is the core feature and is untestable without the worker.
2. **Implement "Forgot password"** — Even a basic email-based reset flow prevents account lockouts for real users.
3. **Add QR code to MFA setup** — Use a library like `qrcode` (backend) or `react-qr-code` (frontend) to render the OTP URI as a scannable QR code.
4. **Improve error messages** — Map common API error codes (401, 422, 500) to human-readable messages in the relevant UI flows, especially MFA and auth.
5. **Clarify the research arm UX** — Make it visually obvious when the next send will trigger a research run (persistent banner or changed placeholder text).
6. **Add a favicon** — Simple `public/favicon.ico` or SVG favicon.
