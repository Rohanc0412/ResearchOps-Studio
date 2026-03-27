# ResearchOps Studio — End-to-End Test Report (v2)

**Date:** 2026-03-27
**Tester:** Automated Playwright browser testing (comprehensive pass)
**Branch:** main (post bug-fix commit)
**User tested:** `demo` / `demo@demo.com`

---

## Environment

| Component | Status | Notes |
|-----------|--------|-------|
| Frontend (Vite) | ✅ Running | `localhost:5173` |
| Backend API (FastAPI) | ✅ Running | `localhost:8000` |
| PostgreSQL | ✅ Running | Docker |
| Worker service | ❌ Not running | Runs stay `queued`; pipeline never completes |
| LLM (OpenRouter) | ✅ Working | `gpt-4o-mini` via hosted provider |

---

## Summary

| Area | Result | New bugs | Fixed since v1 |
|------|--------|----------|---------------|
| Authentication | ✅ Pass | 1 minor | BUG-01 resolved (forgot password exists) |
| Projects | ✅ Pass | 1 minor | — |
| Project detail | ✅ Pass | 0 | **NEW**: Run research button now present |
| Chat / LLM | ✅ Pass | 1 minor | BUG-03 resolved (UX clearer) |
| Research runs | ✅ Pass | 0 | — |
| Artifacts | ✅ Pass | 0 | — |
| Evidence | ✅ Pass | 1 minor | — |
| Security / MFA | ✅ Pass | 0 | BUG-05/06/07 all resolved |
| Navigation | ⚠️ Issues | 2 | BUG-08 resolved (favicon present) |

---

## Area-by-Area Results

### 1. Authentication

**All flows tested:**

| Test case | Result | Notes |
|-----------|--------|-------|
| Login with valid credentials | ✅ Pass | Redirects to `/projects` |
| Login with invalid credentials | ✅ Pass | Shows "Invalid credentials" |
| Blank form submit | ✅ Pass | Browser validation prevents submit |
| Register new account | ✅ Pass | Creates account, auto-logs in |
| Register — password mismatch | ✅ Pass | "Passwords do not match." (client-side) |
| Register — password too short | ✅ Pass | "Password must be at least 8 characters." |
| Register — duplicate username/email | ⚠️ Bug | Shows generic "Sign up failed. Try again." |
| Forgot password flow | ✅ Pass | Form exists and submits; fails with "SMTP not configured" (config, not bug) |
| "Back to sign in" from forgot password | ✅ Pass | Navigation works |
| Protected route while logged out | ✅ Pass | Redirects to `/login` |
| Logout | ✅ Pass | Clears token, redirects to `/login` |
| 2× `/api/auth/refresh` on login page | ℹ️ Info | React StrictMode double-mount in dev; single call in production |

**Bug found:**

> 🐛 **BUG-A1 (Minor): Duplicate registration shows generic error**
> When registering with an already-taken username or email, the backend returns 500 (instead of 409 Conflict) and the frontend shows "Sign up failed. Try again." — gives no indication of what went wrong.
> **Fix needed:** Backend should return 409 with a clear reason; frontend should surface the `detail` field.

---

### 2. Projects

**All flows tested:**

| Test case | Result | Notes |
|-----------|--------|-------|
| Projects list renders | ✅ Pass | Table with name, date, last run |
| Create project (name only) | ✅ Pass | Appears in list and sidebar immediately |
| Create project (name + description) | ✅ Pass | Description shown in list row |
| Create button disabled when name empty | ✅ Pass | Correct |
| Search matching projects | ✅ Pass | Filters correctly |
| Search no-match state | ⚠️ Bug | Wrong empty state message |
| Navigate to project via "Open →" | ✅ Pass | Correct routing |
| Cancel create modal | ✅ Pass | Modal closes, no project created |

**Bug found:**

> 🐛 **BUG-A2 (Minor): Search empty state is misleading**
> When a search query matches no projects, the empty state shows "No projects yet / Create your first project to start research runs." — the same message used when there are genuinely no projects. It should say "No projects matching '[query]'" instead.

---

### 3. Project Detail Page

**All flows tested:**

| Test case | Result | Notes |
|-----------|--------|-------|
| "Run research report" button visible | ✅ Pass | **Fixed** — now present in toolbar |
| Button highlights when clicked | ✅ Pass | Accent border + background |
| Placeholder updates when armed | ✅ Pass | "Describe your research topic — a full report will run automatically…" |
| Toggle off resets placeholder | ✅ Pass | Returns to "Ask a research question…" |
| Armed state carries to ChatViewPage | ✅ Pass | Button pre-pressed, placeholder updated in chat |
| Pipeline triggers when armed + sent | ✅ Pass | Assistant responds "Starting a research run now." |
| "No sessions yet" empty state | ✅ Pass | Shows when no chats exist |
| Recent sessions list | ✅ Pass | Shows after chats created |
| "New chat" button | ✅ Pass | Creates chat and navigates |

**No bugs found.**

---

### 4. Chat View

**All flows tested:**

| Test case | Result | Notes |
|-----------|--------|-------|
| Send message, receive LLM response | ✅ Pass | ~10s response time, markdown rendered |
| Draft cleared after send | ✅ Pass | |
| Run research button in chat | ✅ Pass | Toggle works, placeholder updates |
| Arm resets after send | ✅ Pass | **Fixed** — button disarms after message sent |
| Action buttons (Add conclusion, etc.) | ✅ Pass | Fill textarea correctly |
| Model selector dropdown | ✅ Pass | All models selectable; GPT-4o Mini tested |
| Pipeline armed + action button | ⚠️ Bug | See BUG-A3 below |
| Message history preserved after navigation | ✅ Pass | Full history visible on return |

**Bug found:**

> 🐛 **BUG-A3 (Minor): Action buttons bypass pipeline-arm guard**
> If "Run research report" is armed and the user clicks an action button (e.g., "Add conclusion"), the action text fills the textarea and sending it would trigger a pipeline run with "Add conclusion" as the research topic. The check `force_pipeline: runPipelineArmed && !isAction` only guards messages prefixed with `__ACTION__:`, but action button text has no such prefix.
> **Fix:** Either add `__ACTION__:` prefix to action button text or disarm the pipeline when an action button is clicked.

---

### 5. Research Runs

**All flows tested:**

| Test case | Result | Notes |
|-----------|--------|-------|
| Pipeline triggered from project page | ✅ Pass | Assistant confirms "Starting a research run now." |
| ResearchProgressCard renders | ✅ Pass | Animated steps, halo pulse, shimmer progress bar |
| Step labels animated (wave text) | ✅ Pass | Letter-wave animation active on step 1 |
| "LIVE RESEARCH PROGRESS" with dot | ✅ Pass | Blinking dot visible |
| "PROCESSING" badge in report panel | ✅ Pass | |
| Stop run button | ✅ Pass | Cancels run, status flips to READY, card disappears |
| Run stays at step 1 (no worker) | ℹ️ Info | Expected — worker service not running |

**No bugs found** (pipeline UI fully functional; progression requires worker).

---

### 6. Artifacts

**All flows tested:**

| Test case | Result | Notes |
|-----------|--------|-------|
| Artifacts page loads for canceled run | ✅ Pass | Shows "No artifacts yet / Artifacts will appear here once a run completes." |
| Empty state message is appropriate | ✅ Pass | Correct message for canceled/incomplete run |
| Back button navigates to source chat | ✅ Pass | |
| Run ID shown in subtitle | ✅ Pass | |

**No bugs found.**

---

### 7. Evidence

**All flows tested:**

| Test case | Result | Notes |
|-----------|--------|-------|
| Route `/evidence/snippets/:id` resolves | ✅ Pass | |
| Non-existent snippet ID | ⚠️ Bug | Shows generic "API request failed (404)" |

**Bug found:**

> 🐛 **BUG-A4 (Minor): Evidence 404 shows generic error**
> Navigating to a non-existent snippet shows "Something went wrong — API request failed (404)" with no user-friendly message or navigation hint. Should say "Snippet not found" with a back link.

---

### 8. Security / MFA

**All flows tested:**

| Test case | Result | Notes |
|-----------|--------|-------|
| Security page renders | ✅ Pass | |
| MFA status shows "Not enabled" | ✅ Pass | |
| MFA status shows "Setup in progress" | ✅ Pass | Persists across sessions |
| "Enable MFA" / "Restart setup" button | ✅ Pass | Both work |
| QR code renders in enrollment form | ✅ Pass | **Fixed** — scannable QR code shown |
| Instruction text under QR code | ✅ Pass | "Scan with your authenticator app…" |
| Secret key displayed + copyable | ✅ Pass | Copy button shows checkmark on click |
| OTP URI shown | ✅ Pass | Truncated with full value on hover |
| Wrong TOTP code — error message | ✅ Pass | **Fixed** — "Invalid verification code. Please check your authenticator app and try again." |
| Input cleared after failed attempt | ✅ Pass | **Fixed** — shows placeholder after failure |
| Issuer/Account/Period metadata | ✅ Pass | All correct |

**No bugs found. All v1 MFA issues resolved.**

---

### 9. Navigation & Layout

**All flows tested:**

| Test case | Result | Notes |
|-----------|--------|-------|
| Favicon in browser tab | ✅ Pass | **Fixed** — purple search icon visible |
| Sidebar collapse | ✅ Pass | Icon-only mode |
| Sidebar expand | ✅ Pass | Labels restored |
| All routes navigate correctly | ✅ Pass | |
| Unknown route (`/nonexistent`) | ⚠️ Bug | Bare error, no layout |
| Invalid project ID (valid route) | ⚠️ Bug | Generic 404 message, 6 console errors |
| `v0.1` version label | ✅ Pass | Shown in sidebar footer |

**Bugs found:**

> 🐛 **BUG-A5 (Medium): Unknown route shows bare 404 with no layout**
> Navigating to an unknown path (e.g., `/foobar`) shows a raw "Error 404 — Not Found" alert with no sidebar, header, or navigation options. Users have no way to return to the app without using the browser back button or manually editing the URL.
> **Fix:** Add a catch-all route that renders a proper 404 page inside the app layout with a "Go to projects" link.

> 🐛 **BUG-A6 (Minor): Invalid resource ID triggers 6 console errors**
> Navigating to a valid route with a non-existent UUID (e.g., `/projects/00000000-…`) fires 6 identical API requests (3 pairs from React StrictMode). This is a dev-mode artifact, but the underlying issue is that the page makes multiple API calls for the same resource without deduplication or caching.

---

## Consolidated Bug List

| ID | Severity | Area | Description | Status |
|----|----------|------|-------------|--------|
| BUG-A1 | Minor | Auth | Duplicate registration shows generic error instead of "username taken" | 🔴 New |
| BUG-A2 | Minor | Projects | Search empty state says "No projects yet" when projects exist but don't match | 🔴 New |
| BUG-A3 | Minor | Chat | Action buttons bypass pipeline-arm guard, can accidentally trigger research run | 🔴 New |
| BUG-A4 | Minor | Evidence | Non-existent snippet shows generic "API request failed (404)" | 🔴 New |
| BUG-A5 | Medium | Navigation | Unknown route renders bare 404 without app layout or navigation | 🔴 New |
| BUG-A6 | Minor | Navigation | Invalid resource URL fires 6 duplicate API requests in dev | 🔴 New |

### All v1 Bugs — Status Update

| ID | Description | Status |
|----|-------------|--------|
| BUG-01 | "Forgot password" not implemented | ✅ Was already implemented (SMTP not configured is config, not code) |
| BUG-02 | Double 401 on logout | ✅ Fixed (`loggingOutRef` guard); remaining 2 errors are React StrictMode on new page load |
| BUG-03 | Run research report UX unclear | ✅ Fixed — placeholder updates, arm resets after send |
| BUG-04 | Worker not in dev startup | ⚠️ Still pending — requires documentation/Makefile entry |
| BUG-05 | No QR code for MFA | ✅ Fixed — QR code renders |
| BUG-06 | Generic MFA error message | ✅ Fixed — friendly message shown |
| BUG-07 | MFA input not cleared on failure | ✅ Fixed — clears after failed attempt |
| BUG-08 | Missing favicon | ✅ Fixed — purple search icon SVG favicon |

---

## What Works Well (Confirmed This Session)

- Full authentication cycle: register → login → use app → logout → re-login
- Project creation with description
- Research run trigger from project page with arm state carrying through to chat
- LLM chat responses (OpenRouter, multiple models) with markdown rendering
- Research pipeline trigger, progress card animations (wave text, halo, shimmer), stop/cancel
- MFA enrollment UI: QR code, secret copy, friendly error, input auto-clear
- Sidebar collapse/expand, sidebar navigation, version label
- All primary routes navigate without crashes

## Remaining Issues (Prioritized)

1. **BUG-04** — Worker not in dev startup: no single command to start the full stack
2. **BUG-A5** — Unknown route shows unstyled 404 with no navigation
3. **BUG-A1** — Duplicate registration gives no useful feedback
4. **BUG-A3** — Action buttons can accidentally arm pipeline
5. **BUG-A2** — Search empty state shows wrong message
6. **BUG-A4** — Evidence 404 shows generic error
7. **BUG-A6** — Invalid resource URLs fire 6 console errors (dev-mode only)
