# Repository Stabilization And Code Quality Design

## Goal

Raise the project's portfolio quality by making the repository reproducible, demoable, and materially easier to evaluate. The work covers build and test stability, setup and documentation clarity, visible UI polish issues, CI verification, and targeted code-quality refactors for the largest highest-impact files.

## Scope

This design covers the project through the "code quality" boundary from the earlier checklist:

- Fix frontend build failures and keep the app production-buildable.
- Fix backend test/setup reproducibility so the repository can be bootstrapped cleanly.
- Add root-level onboarding documentation and safe example environment files.
- Remove visible UI copy and encoding issues that weaken presentation quality.
- Add lightweight CI verification for core repository health signals.
- Refactor the worst oversized files into smaller focused modules without intentionally changing product behavior.

Out of scope:

- New product features.
- Broad architectural rewrites outside the directly affected areas.
- Deep performance optimization unless required to restore broken validation flows.
- Hosting/deployment beyond improving the documented local and containerized run path.

## Constraints And Success Criteria

### Constraints

- Preserve current user-visible behavior unless a behavior is clearly broken.
- Do not revert unrelated user changes.
- Prefer targeted refactors over sweeping rewrites.
- Keep the repository usable in local development on Windows and in the documented Docker flow.

### Success Criteria

- `npm run build` succeeds from `frontend/dashboard`.
- Backend tests can be installed and executed from a documented clean setup.
- The repository has a root `README.md` that explains architecture, setup, demo flow, and technical highlights.
- The repository contains one or more `.env.example` files with non-secret placeholders.
- A basic CI workflow validates core health checks.
- The worst oversized files are split into smaller modules with clearer responsibilities.
- User-facing garbled text and obvious polish defects are removed.

## Implementation Approach

The work should proceed in two phases.

### Phase 1: Stabilize And Make The Repository Legible

Fix the red-status items first so the repository becomes trustworthy:

- Frontend TypeScript/build failures.
- Backend dependency and test reproducibility issues.
- Missing project-level docs and setup artifacts.
- UI text and encoding defects.
- Basic CI coverage for build/test/lint.

This phase increases resume value fastest because it addresses the first issues a recruiter, reviewer, or interviewer would hit.

### Phase 2: Targeted Code-Quality Refactors

After validation is green or at least reproducible, refactor the largest files that most obviously signal maintainability debt:

- `backend/services/api/routes/chat.py`
- `frontend/dashboard/src/pages/ChatViewPage.tsx`
- `tests/e2e/full_suite.spec.ts`

Each split should produce smaller focused modules with narrow responsibilities and stable interfaces. Refactors should be guided by existing behavior and backed by validation rather than aesthetic preferences.

## Proposed File Structure Changes

### Documentation And Setup

- Create `README.md` at repository root.
- Create `.env.example` at repository root and, if needed, `frontend/dashboard/.env.example`.
- Create or update CI workflow files under `.github/workflows/`.

### Frontend Build And Cleanup

- Fix typing issues in `frontend/dashboard/src/api/evidence.ts`.
- Fix PDF export typing issues in `frontend/dashboard/src/features/chat/lib/reportExport.tsx`.
- Normalize garbled strings in the main user-facing pages.

### Frontend Code-Quality Split

`ChatViewPage.tsx` should be decomposed into feature-local modules such as:

- chat/run state and hydration helpers
- artifact/report hydration helpers
- message list rendering
- composer / quick action / export notification UI pieces

The page component should become a coordinator rather than the home for all chat/report logic.

### Backend Code-Quality Split

`chat.py` should be decomposed into focused modules under the chat route or app-service area, likely along these boundaries:

- request/response schemas
- streaming/SSE helpers
- quick-answer generation helpers
- consent / pending-action decision logic
- title and conversation helper functions

The route file should retain request orchestration while moving heavy utility logic into narrower modules.

### E2E Code-Quality Split

`tests/e2e/full_suite.spec.ts` should be split into multiple specs grouped by product domain:

- auth
- projects
- chat/report generation
- artifacts/evidence
- evaluation
- error and edge cases

Shared helpers and test state should move into a local support module to avoid cross-file duplication and hidden coupling.

## Data Flow And Behavioral Safety

The stabilization work should preserve the current application flows:

- frontend requests still hit the same API contracts
- backend chat routing still produces the same message and run behaviors
- E2E coverage still exercises the same major user journeys

Refactor safety should come from:

- first reproducing existing failures
- fixing failures with minimal behavior changes
- extracting code behind tested interfaces
- rerunning focused verification after each major refactor

## Error Handling

The cleanup should improve clarity rather than add speculative behavior:

- convert ambiguous setup failures into documented prerequisites
- make type and import failures explicit in docs and CI
- keep runtime fallback behavior where it already exists
- avoid silent behavior changes during refactors

## Testing And Verification Strategy

### Core Verification

- frontend: `npm run build`
- frontend lint if configured cleanly enough to be actionable
- backend: targeted `pytest` or full suite once dependency issues are resolved
- repository: CI mirrors the commands documented for local verification

### Refactor Verification

- keep or add focused tests around moved logic where coverage is weak
- run targeted tests after each split
- keep the E2E suite organized but behaviorally equivalent

## Risks

### Risk: broad scope causes regressions

Mitigation:

- stabilize first
- refactor second
- keep changes incremental

### Risk: large-file splits consume too much time

Mitigation:

- only split the most visible and highest-value files
- stop once responsibilities are clearly separated and files are materially smaller

### Risk: environment differences still block reviewers

Mitigation:

- document exact prerequisites
- add example env files
- align CI with documented commands

## Deliverables

- green frontend production build
- reproducible backend setup and test path
- root README and env examples
- CI workflow for core checks
- cleaned UI text/presentation issues
- targeted modularization of the major oversized files

## Recommended Execution Order

1. Fix frontend build failures.
2. Fix backend dependency/test reproducibility.
3. Add root docs and example env files.
4. Clean UI text/polish issues.
5. Add CI workflow.
6. Refactor `ChatViewPage.tsx`.
7. Refactor `chat.py`.
8. Split the E2E suite.
9. Run final verification and document results.
