# Phase 7a Vue Frontend Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a professional Vue 3 vertical slice from login through Opportunity context, Requirement Analysis, grounded Solution generation, and Presales review while preserving Django as the authorization/business authority.

**Architecture:** Add a standalone `frontend/` Vite SPA with domain-split typed API clients, minimal Pinia authentication state, route-local server state, and an Opportunity-centered workspace. Use current direct Solution/review APIs first. Add only the narrowly required Django HTTP adapters for durable Phase 6a workflow start/status/resume and a reviewer inbox; wrappers call existing Graph/services and contain no duplicate business rules.

**Tech Stack:** Vue 3, TypeScript, Vite, Vue Router, Pinia, Axios, Element Plus, Vitest, Vue Test Utils; current Django 5.2/DRF/JWT backend.

**Spec:** `docs/superpowers/specs/2026-09-07-vue-frontend-architecture-design.md`

## Global constraints

**2026-09-08 scope amendment:** Execute Tasks 1–7 and the frontend verification portions of Task 12 only. Tasks 8–11 are explicitly deferred. Do not create Dashboard/Customer/Knowledge/inbox placeholders or backend adapters. Use the direct REST path with a user inspection step between DRAFT generation and explicit submission. Preserve Phase 6a Graph unchanged. Review is reached through assigned Opportunity workspace and Solution detail. Backend verification is Django check only when backend code is unchanged.

Authentication tokens are the sole exception to the general no-credentials-in-browser-state rule below: access token stays in Pinia memory and refresh token in sessionStorage, as explicitly approved. No provider credentials or database credentials enter the browser.

- TDD each behavior: failing test -> confirm relevant failure -> minimal implementation -> focused verification.
- Backend role, visibility, stale, review, self-review, provenance, and workflow services remain authoritative.
- Never map Django `is_staff`/`is_superuser` to a business role.
- Never store credentials, full Solution payloads, evidence corpora, or checkpoints in Pinia or browser persistence.
- Do not add Nuxt, GraphQL, micro-frontends, Redux-like layers, Celery, Redis, or a large design system.
- Preserve `.workbuddy/` and `docs/code-review-2026-08-29.md` unchanged and untracked.

---

### Task 1: Scaffold the minimal Vue application

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/index.html`
- Create: `frontend/tsconfig*.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/styles/`
- Create: `frontend/src/env.d.ts`
- Create: `frontend/src/test/setup.ts`

**Interfaces:** A Vite-built Vue 3 TypeScript SPA with Router, Pinia, Element Plus, and Vitest, but no business page shells beyond what the next tests require.

- [ ] Pin compatible versions current at implementation time; record the chosen Node/npm baseline.
- [ ] Write a smoke test that mounts the root application with test Router/Pinia and fails before the scaffold exists.
- [ ] Create the smallest Vite/Vue/TypeScript configuration and semantic theme tokens.
- [ ] Run type-check, unit test, and production build to GREEN.

### Task 2: Build typed transport and authentication

**Files:**
- Create: `frontend/src/api/http.ts`
- Create: `frontend/src/api/auth.ts`
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/stores/auth.ts`
- Create: `frontend/src/router/index.ts`
- Create: `frontend/src/views/LoginView.vue`
- Create: `frontend/src/layouts/AppShell.vue`
- Test: `frontend/src/api/__tests__/http.spec.ts`
- Test: `frontend/src/stores/__tests__/auth.spec.ts`
- Test: `frontend/src/router/__tests__/guards.spec.ts`

**Interfaces:** `login`, `refresh`, `getCurrentUser`, single-flight refresh, one-request replay, logout, and route metadata based on `admin|sales|presales`.

- [ ] Write RED tests for successful login/bootstrap, invalid login, one concurrent refresh, replay-at-most-once, refresh failure logout, and intended-route restoration.
- [ ] Write RED tests proving route guards use business `role` only and do not infer authority from technical flags.
- [ ] Implement access token in memory and refresh token in `sessionStorage` under the unchanged JWT contract.
- [ ] Normalize only transport errors; retain backend safe `code/message` and HTTP status for page behavior.
- [ ] Run auth/API/router tests and type-check to GREEN.

### Task 3: Opportunity list and role-aware application shell

**Files:**
- Create: `frontend/src/api/opportunities.ts`
- Create: `frontend/src/api/users.ts`
- Create: `frontend/src/views/DashboardView.vue`
- Create: `frontend/src/views/OpportunityListView.vue`
- Create: `frontend/src/components/opportunities/OpportunityTable.vue`
- Test: matching component/view specs.

**Interfaces:** Paginated role-filtered Opportunity list, stage/status labels, empty/error/loading states, and navigation to the workspace.

- [ ] Write RED tests for pagination, Chinese enum labels, role-specific navigation/actions, and authoritative `403/404` handling.
- [ ] Implement the shell and list without copying Opportunity collections into Pinia.
- [ ] Show only backend-supported create/edit navigation to Sales; treat hidden controls as UX, not authorization.
- [ ] Run focused component/API tests and build.

### Task 4: Opportunity workspace and Sales-owned requirement editing

**Files:**
- Create: `frontend/src/views/OpportunityWorkspaceView.vue`
- Create: `frontend/src/components/opportunities/OpportunityOverview.vue`
- Create: `frontend/src/components/opportunities/RequirementEditor.vue`
- Modify: `frontend/src/api/opportunities.ts`
- Modify: `frontend/src/router/index.ts`
- Test: matching view/component specs.

**Interfaces:** Nested `overview`, `requirement`, `analysis`, `solutions`, and `review` routes sharing one Opportunity header/context.

- [ ] Write RED tests for tab deep links, refresh-safe loading, Sales edit controls, read-only Presales/Admin views, and backend conflict/error messages.
- [ ] Implement GET/PATCH using only allowed Opportunity fields.
- [ ] Preserve unsaved-form warnings and refetch after successful mutation.
- [ ] Run focused tests, type-check, and build.

### Task 5: Requirement Analysis history and detail

**Files:**
- Create: `frontend/src/api/analysis.ts`
- Create: `frontend/src/components/analysis/AnalysisHistory.vue`
- Create: `frontend/src/components/analysis/AnalysisDetail.vue`
- Create: `frontend/src/components/analysis/RequirementDimensionGrid.vue`
- Test: matching API/component specs.

**Interfaces:** Immutable snapshot list/detail/latest, explicit selected analysis, and POST with exactly `{}`.

- [ ] Write RED tests for all four dimension states, conflict/clarification rendering, history selection, empty history, and provider errors.
- [ ] Implement analysis generation with disabled duplicate submission and clear long-running progress.
- [ ] Keep the selected persisted `analysis_id` explicit for downstream Solution generation.
- [ ] Run focused tests and build.

### Task 6: Solution versions, structured content, and provenance

**Files:**
- Create: `frontend/src/api/solutions.ts`
- Create: `frontend/src/views/SolutionDetailView.vue`
- Create: `frontend/src/components/solutions/SolutionVersionList.vue`
- Create: `frontend/src/components/solutions/SolutionDraftRenderer.vue`
- Create: `frontend/src/components/solutions/SolutionStateBadge.vue`
- Create: `frontend/src/components/solutions/ProvenanceDrawer.vue`
- Test: matching API/component/view specs.

**Interfaces:** Generate from explicit analysis, render version history and stable `draft_payload`, expose stale reasons, and progressively disclose durable provenance.

- [ ] Write RED tests proving the exact selected analysis is posted, no latest-analysis substitution occurs, and generation/provider errors do not create optimistic fake drafts.
- [ ] Write RED tests for Solution/review/stale Chinese mappings, structured sections/citations, and safe provenance display.
- [ ] Implement detail/list fetching as route-local state and refetch after mutations.
- [ ] Do not expose content editing or deletion controls.
- [ ] Run focused tests, type-check, and build.

### Task 7: Direct review actions and audit history

**Files:**
- Create: `frontend/src/api/reviews.ts`
- Create: `frontend/src/components/reviews/ReviewTimeline.vue`
- Create: `frontend/src/components/reviews/SubmitReviewDialog.vue`
- Create: `frontend/src/components/reviews/ReviewDecisionPanel.vue`
- Modify: `frontend/src/views/SolutionDetailView.vue`
- Test: matching API/component specs.

**Interfaces:** Submit, approve, request revision, and immutable history using current direct DRF endpoints.

- [ ] Write RED tests for Sales-to-assigned-Presales submit, independent reviewer selection for a Presales-authored version, Sales cannot decide, and stale/state/self-review conflicts.
- [ ] Write RED tests requiring one return reason plus non-empty comment and visually distinguishing customer-information from technical-revision outcomes.
- [ ] Implement state-sensitive controls and always reload detail/history after a decision.
- [ ] Do not infer approval from local button completion if the refetch disagrees.
- [ ] Run focused tests and build.

### Task 8: Add minimal durable workflow HTTP adapters

**Files:**
- Create: `apps/sales/api/solution_workflow_views.py`
- Create: `apps/sales/api/solution_workflow_serializers.py`
- Modify: `apps/sales/api/urls.py`
- Test: `apps/sales/tests/test_solution_review_workflow_api.py`

**Interfaces:** Proposed endpoints (final naming follows current URL style):
- `POST /api/opportunities/{id}/solution-workflows/` with explicit `analysis_id` and optional eligible reviewer;
- `GET /api/solution-workflows/{workflow_run_id}/` for safe current business/workflow state;
- `POST /api/solution-workflows/{workflow_run_id}/resume/` with approve or exact revision decision.

- [ ] Before implementation, write an approved backend API contract specifying server-generated workflow IDs, checkpointer thread identity, safe finite outcome fields, and retry/replay semantics.
- [ ] Write RED tests for authentication, Opportunity visibility, explicit analysis ownership, actor identity derived from `request.user`, and minimal non-sensitive responses.
- [ ] Write RED tests for start-to-interrupt, reconstruction/status, approve/revision resume, identical replay recovery, opposing replay conflict, and absence of payload/evidence/credential leakage.
- [ ] Implement thin wrappers around `build_solution_review_graph` and `open_solution_workflow_checkpointer`; do not duplicate service permissions or review logic.
- [ ] Run workflow API tests, existing Phase 6a tests, Sales regression, Django checks, migration check, and full pytest.

### Task 9: Add a bounded reviewer inbox API

**Files:**
- Create or extend: `apps/sales/api/solution_draft_views.py`
- Create or extend: `apps/sales/api/solution_draft_serializers.py`
- Modify: `apps/sales/api/urls.py`
- Test: `apps/sales/tests/test_solution_review_inbox_api.py`

**Interfaces:** A paginated read-only collection of Solution reviews assigned to the authenticated reviewer, with safe Solution/Opportunity summary fields and status filtering.

- [ ] Write RED tests for Presales-assigned visibility, business Admin fallback view, Sales denial, technical-flag non-bypass, pagination, and no payload/provenance overexposure.
- [ ] Implement using current role-aware query boundaries; do not change review authority.
- [ ] Run focused and Sales regressions.

### Task 10: Bind the frontend to workflow reconstruction and review inbox

**Files:**
- Create: `frontend/src/api/workflows.ts`
- Create: `frontend/src/views/ReviewInboxView.vue`
- Create: `frontend/src/components/workflow/WorkflowProgress.vue`
- Modify: `frontend/src/api/reviews.ts`
- Modify: `frontend/src/components/reviews/ReviewDecisionPanel.vue`
- Modify: `frontend/src/router/index.ts`
- Test: matching API/view/component specs.

**Interfaces:** Business-semantic workflow states only: generating, submitting, waiting, approved, customer info required, technical revision required, blocked/conflict/failed.

- [ ] Write RED tests for reload reconstruction, waiting interrupt display, resume input, conflict refresh, and terminal/handoff outcomes.
- [ ] Implement server-state refetch after start/resume; never cache checkpoint authority in Pinia.
- [ ] Keep Graph/checkpoint/thread terminology out of user-facing strings.
- [ ] Run focused tests, type-check, and build.

### Task 11: Admin Knowledge document management

**Files:**
- Create: `frontend/src/api/knowledge.ts`
- Create: `frontend/src/views/KnowledgeDocumentListView.vue`
- Create: `frontend/src/views/KnowledgeDocumentDetailView.vue`
- Create: `frontend/src/components/knowledge/KnowledgeUploadDialog.vue`
- Test: matching API/view/component specs.

**Interfaces:** Business-Admin-only list/upload/detail/reindex using current REST capabilities.

- [ ] Write RED tests for role route hiding, backend `403`, upload validation, indexing/failed states, and reindex conflicts.
- [ ] Implement only document management; do not fabricate Grounding Fact REST actions.
- [ ] Run focused tests and build.

### Task 12: End-to-end quality gate and demo path

**Files:**
- Add only bounded E2E fixtures/configuration approved for the chosen browser runner.
- Review frontend and any separately approved backend adapter changes.

- [ ] Run frontend unit/component tests, TypeScript checking, linting, and production build.
- [ ] Run the backend focused API tests, Sales regressions, full pytest, Django check, migration check, and dependency check when backend adapters are included.
- [ ] Exercise the vertical demo as Sales: login -> Opportunity -> analysis -> Solution -> submit.
- [ ] Exercise it as Presales: login -> inbox -> Solution/provenance -> approve.
- [ ] Exercise both return reasons and verify the UI sends users to the correct customer-information or technical-revision handoff.
- [ ] Verify refresh/reconstruction during pending review and authoritative conflict handling.
- [ ] Audit tokens, logs, errors, checkpoints, browser storage, and rendered provenance for sensitive-data leakage.
- [ ] Verify keyboard navigation, focus management, form labels, status color-plus-text, responsive tables, and readable loading/empty/error states.
- [ ] Run `git diff --check` and review the final change boundary before any commit.

## Deferred after Phase 7a

- Grounding Fact Vue review UI and its REST API.
- Customer browse-all/update/delete unless separately justified.
- automatic Solution revision loops and customer-question workflows.
- notifications, multi-agent UI, delivery/after-sales, and customer approval.
- verifier latency work tracked by `docs/technical-debt.md#td-001--semantic-verifier-synchronous-latency`.
