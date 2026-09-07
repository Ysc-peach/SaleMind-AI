# Solution Review Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a version-scoped, auditable Solution review workflow with safe submit, approve, and revision-return transitions.

**Architecture:** `SolutionDraftRecord.review_status` remains the coarse current-state projection. A new `SolutionReview` row records each version-specific review attempt, while a dedicated synchronous service performs role checks, stale validation, row locking, and atomic state transitions. DRF actions expose the service without permitting direct status mutation or review deletion.

**Tech Stack:** Python, Django 5.2, Django REST Framework, PostgreSQL, pytest/pytest-django.

**Spec:** `docs/business-rules.md` (D-012/D-013 are also recorded in `docs/decisions.md`).

## Global Constraints

- Business authorization uses `User.role`; `is_staff` and `is_superuser` never grant review authority.
- Solution content and completed review decisions remain immutable.
- Stale Solutions cannot be submitted or approved.
- Every transition is fail-closed and atomic; no external model call belongs in the review transaction.
- Do not apply the new migration to the real `salesmind` database without separate authorization.
- Preserve `.workbuddy/` and `docs/code-review-2026-08-29.md` unchanged and untracked.

---

### Task 1: Persist version-scoped review attempts

**Files:**
- Modify: `apps/sales/models.py`
- Create: `apps/sales/tests/test_solution_review_models.py`
- Create: `apps/sales/migrations/0004_solutionreview.py`

**Interfaces:**
- Produces: `SolutionReviewDecisionStatus` (`PENDING`, `APPROVED`, `RETURNED`), `SolutionReturnReason`, and `SolutionReview`. The distinct name preserves the existing `SolutionReviewStatus` Draft-projection enum.
- Invariant: at most one `PENDING` review per `SolutionDraftRecord`.

- [ ] **Step 1: Write failing model tests**

  Add tests that create a pending review, reject invalid status/decision-field combinations, enforce one active pending review, protect reviewer/submitted-by audit users, reject deletion, and reject changes to reviewer or any completed decision.

- [ ] **Step 2: Run the model tests and confirm RED**

  Run: `python -m pytest apps/sales/tests/test_solution_review_models.py -q`

  Expected: collection/import failure because `SolutionReview` and its enums do not exist.

- [ ] **Step 3: Add the minimal model**

  Implement `SolutionReview` with `solution_draft`, `submitted_by`, `reviewer`, `status`, `return_reason`, `comment`, `submitted_at`, and `decided_at`. Use `PROTECT` for both users, a conditional unique constraint for the pending row, check constraints for pending/approved/returned field combinations, and model guards that keep identity and completed decisions immutable.

- [ ] **Step 4: Generate and inspect the migration**

  Run: `python manage.py makemigrations sales`

  Confirm the migration creates only `SolutionReview`, its indexes, and its constraints.

- [ ] **Step 5: Run focused model tests**

  Run: `python -m pytest apps/sales/tests/test_solution_review_models.py apps/sales/tests/test_solution_persistence_models.py -q`

  Expected: PASS.

### Task 2: Add the transactional review state machine

**Files:**
- Create: `apps/sales/services/solution_review.py`
- Create: `apps/sales/tests/test_solution_review_service.py`
- Reuse: `apps/sales/services/solution_persistence.py`

**Interfaces:**
- Produces: `submit_solution_draft_for_review(solution, *, actor, reviewer=None) -> SolutionReview`.
- Produces: `approve_solution_draft(solution, *, actor, comment="") -> SolutionReview`.
- Produces: `request_solution_draft_revision(solution, *, actor, return_reason, comment) -> SolutionReview`.
- Produces stable `SolutionReviewError` subclasses/codes for permission, state, reviewer, and stale failures.

- [ ] **Step 1: Write failing submit tests**

  Cover DRAFT submission, one pending row, projection update, stale rejection, Sales-owner assignment to `presales_owner`, missing owner, unrelated users, technical-flag non-bypass, Presales default self-review of others' versions, and explicit independent reviewer for Presales-authored versions.

- [ ] **Step 2: Run submit tests and confirm RED**

  Run the submit test node(s) from `test_solution_review_service.py`; expect import failure for the new service.

- [ ] **Step 3: Implement submit in a short transaction**

  Lock the Solution row, refresh deterministic staleness, require `DRAFT`, resolve the reviewer without random assignment, validate business roles and self-review rules, create one pending `SolutionReview`, and set the projection to `PENDING_REVIEW`.

- [ ] **Step 4: Write and run failing approve/return tests**

  Cover assigned reviewer, Admin fallback, Sales/unrelated Presales rejection, self-review rejection, stale approval rejection, exact return reasons, mandatory return comment, duplicate decisions, and Solution payload immutability.

- [ ] **Step 5: Implement approve and return atomically**

  Lock Solution then current pending Review in a consistent order. Revalidate current state and permissions. Update the Review decision and Solution projection in the same transaction, leaving payload, version, and previous completed reviews unchanged.

- [ ] **Step 6: Run service tests**

  Run: `python -m pytest apps/sales/tests/test_solution_review_service.py -q`

  Expected: PASS.

### Task 3: Prove database concurrency behavior

**Files:**
- Create: `apps/sales/tests/test_solution_review_concurrency.py`
- Modify only if required by RED: `apps/sales/services/solution_review.py`

**Interfaces:**
- Consumes the three Task 2 service functions.
- Proves one pending review and one terminal decision under concurrent calls.

- [ ] **Step 1: Add transactional concurrent tests**

  Use pytest-django transaction-enabled tests and separate thread connections to submit twice and to race approve against return. Assert one successful transition, one stable service failure, one review row, and a matching final projection/review decision.

- [ ] **Step 2: Run concurrency tests and confirm RED or expose the race**

  Run: `python -m pytest apps/sales/tests/test_solution_review_concurrency.py -q`

- [ ] **Step 3: Make the minimal locking/constraint correction**

  Preserve the lock order `SolutionDraftRecord` then pending `SolutionReview`; rely on the partial unique constraint as the database backstop.

- [ ] **Step 4: Re-run concurrency and service tests**

  Expected: PASS without retry loops.

### Task 4: Expose submit, approve, return, and history APIs

**Files:**
- Modify: `apps/sales/api/solution_draft_serializers.py`
- Modify: `apps/sales/api/solution_draft_views.py`
- Modify: `apps/sales/api/urls.py`
- Create: `apps/sales/tests/test_solution_review_api.py`

**Interfaces:**
- Adds `POST /solution-drafts/{id}/submit/`.
- Adds `POST /solution-drafts/{id}/approve/`.
- Adds `POST /solution-drafts/{id}/request-revision/`.
- Adds `GET /solution-drafts/{id}/reviews/`.

- [ ] **Step 1: Write failing API tests**

  Assert route behavior, strict request payloads, stable safe error envelopes, Opportunity visibility as 404, action authorization as 403, readable ordered history, and 405 for review update/delete and direct Solution status mutation.

- [ ] **Step 2: Run API tests and confirm RED**

  Run: `python -m pytest apps/sales/tests/test_solution_review_api.py -q`

  Expected: route reversals or requests fail because endpoints do not exist.

- [ ] **Step 3: Implement strict serializers and view actions**

  Resolve ordinary visibility through `visible_opportunities_for`; additionally allow an explicitly assigned active Presales reviewer to access only that assigned Solution version. Delegate all transitions to the service, map permission/state failures to the existing DRF conventions, and serialize review history without exposing credentials or provider data.

- [ ] **Step 4: Re-run API tests**

  Expected: PASS.

### Task 5: Preserve stale and historical semantics

**Files:**
- Modify: `apps/sales/tests/test_solution_review_service.py`
- Modify only if RED requires it: `apps/sales/services/solution_review.py`

**Interfaces:**
- Keeps approved review history when the Solution later becomes stale.
- Keeps `review_status=APPROVED` independent from `is_stale=True`.

- [ ] **Step 1: Add failing historical-state tests**

  Approve a Solution, create a newer Requirement Analysis or invalidate grounding provenance, refresh staleness, and assert the approval projection and completed review remain unchanged while stale metadata updates.

- [ ] **Step 2: Run the tests and confirm expected RED if behavior is missing**

- [ ] **Step 3: Apply only the minimal correction required**

  Do not reset review status from stale evaluation and do not mutate completed reviews.

- [ ] **Step 4: Run all Phase 5.6b focused tests**

  Run: `python -m pytest apps/sales/tests/test_solution_review_models.py apps/sales/tests/test_solution_review_service.py apps/sales/tests/test_solution_review_concurrency.py apps/sales/tests/test_solution_review_api.py -q`

### Task 6: Verify regressions and review the implementation

**Files:**
- Review all Phase 5.6b changed files.

**Interfaces:**
- Confirms Phase 5.6b does not alter grounding, generation, immutable Solution content, or Phase 5.6a migration state.

- [ ] **Step 1: Run sales and Phase 5 regressions**

  Run the Sales suite and the repository's established Phase 5 selection.

- [ ] **Step 2: Run the full test suite**

  Run: `python -m pytest -q`

- [ ] **Step 3: Run quality gates**

  Run `python manage.py check`, `python manage.py makemigrations --check --dry-run`, `python -m pip check`, and `git diff --check`.

- [ ] **Step 4: Perform a source review**

  Check business-role authorization, self-review, stale approval, lock order, conditional uniqueness, terminal review immutability, safe API errors, and absence of update/delete endpoints.

- [ ] **Step 5: Commit the focused implementation**

  Stage only the plan, model, migration, service, API, and Phase 5.6b tests. Commit with a focused Phase 5.6b message. Do not apply migration `0004` to the real `salesmind` database.
