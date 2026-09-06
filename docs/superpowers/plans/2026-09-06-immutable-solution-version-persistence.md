# Phase 5.6a Immutable Solution Version Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist validated Solution Drafts as immutable per-Opportunity versions with durable, reindex-safe provenance and minimal role-scoped APIs.

**Architecture:** Keep the existing generator read-only, expose its exact deterministic admission in the internal result, and add a short-transaction persistence wrapper. Store domain payloads through an explicit mapper and store citation-to-Fact provenance without a KnowledgeChunk foreign key.

**Tech Stack:** Django 5.2 ORM/migrations, Django REST Framework, PostgreSQL, pytest/pytest-django.

**Spec:** `docs/superpowers/specs/2026-09-06-immutable-solution-version-persistence-design.md`

## Global Constraints

- Do not apply the new migration to the real `salesmind` database without separate authorization.
- Do not change generation, retrieval, admission, verifier, approval, indexing, or Requirement Analysis semantics.
- External provider calls remain outside database transactions.
- Preserve `.workbuddy/` and `docs/code-review-2026-08-29.md` unchanged and untracked.

---

### Task 1: Persistence models and migration

**Files:**
- Modify: `apps/sales/models.py`
- Create: `apps/sales/migrations/0003_*.py`
- Test: `apps/sales/tests/test_solution_persistence_models.py`

- [ ] Add RED tests for model fields, constraints, immutability, independent status/stale metadata, and no KnowledgeChunk FK.
- [ ] Confirm RED.
- [ ] Implement `SolutionDraftRecord`, `SolutionDraftProvenance`, enums, constraints, and migration.
- [ ] Run focused model and migration tests.

### Task 2: Stable domain payload mapper

**Files:**
- Create: `apps/sales/services/solution_persistence.py`
- Test: `apps/sales/tests/test_solution_persistence.py`

- [ ] Add RED round-trip and malformed-payload tests.
- [ ] Confirm RED.
- [ ] Implement strict domain-to-JSON and JSON-to-domain mapping.
- [ ] Run focused mapper tests.

### Task 3: Exact provenance handoff and atomic persistence

**Files:**
- Modify: `apps/sales/services/solution_draft.py`
- Modify: `apps/sales/services/solution_persistence.py`
- Test: `apps/sales/tests/test_solution_persistence.py`

- [ ] Add RED tests for exact selected analysis, version sequences, blocked/provider/verifier failures, insert-time revalidation, durable citation mapping, rollback, and concurrency.
- [ ] Confirm RED.
- [ ] Minimally expose the exact `GroundingAdmission` in generated internal results.
- [ ] Implement the read-only generation wrapper followed by locked short-transaction persistence.
- [ ] Run focused persistence and existing solution tests.

### Task 4: Deterministic stale lifecycle

**Files:**
- Modify: `apps/sales/services/solution_persistence.py`
- Test: `apps/sales/tests/test_solution_staleness.py`

- [ ] Add RED tests for newer analysis, old-analysis generation, invalid Fact state, and invalid source provenance.
- [ ] Confirm RED.
- [ ] Implement deterministic stale evaluation/update independent of review status.
- [ ] Run focused stale tests.

### Task 5: Minimal role-scoped API

**Files:**
- Create: `apps/sales/api/solution_draft_serializers.py`
- Create: `apps/sales/api/solution_draft_views.py`
- Modify: `apps/sales/api/urls.py`
- Modify: `apps/sales/api/permissions.py`
- Test: `apps/sales/tests/test_solution_persistence_api.py`

- [ ] Add RED tests for create/list/detail contracts, explicit analysis ownership, all allowed roles, unrelated-role exclusion, technical-flag non-bypass, and no content mutation/delete routes.
- [ ] Confirm RED.
- [ ] Implement serializers, permission, views, routes, and safe error adaptation.
- [ ] Run focused API tests.

### Task 6: Regression and completion gates

**Files:**
- Review all changed files and migration.

- [ ] Run focused Phase 5.6a tests.
- [ ] Run sales, affected knowledge/provenance, Phase 5, and full pytest suites.
- [ ] Run Django check, migration consistency check, pip check, and diff check.
- [ ] Use GitNexus change/impact analysis and independently review safety invariants.
- [ ] Report the unapplied real-database migration and stop before Phase 5.6b.
