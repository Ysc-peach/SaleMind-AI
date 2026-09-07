# Phase 6a LangGraph Solution Review Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add restart-safe LangGraph orchestration around existing Solution persistence and review services without moving business rules into the graph.

**Architecture:** Add durable UUID generation idempotency to `SolutionDraftRecord`, then build a small typed `StateGraph` whose nodes reload IDs from PostgreSQL and call existing services. Compile it with the official PostgreSQL checkpointer; schema setup remains an explicit separately authorized operation for the real database.

**Tech Stack:** Python 3.12, Django 5.2, PostgreSQL 17, psycopg 3, LangGraph 1.2, `langgraph-checkpoint-postgres` 3.1, pytest.

**Spec:** `docs/superpowers/specs/2026-09-07-langgraph-solution-review-orchestration-design.md`

## Global Constraints

- LangGraph orchestrates; Django services decide and persist business truth.
- Do not reimplement Requirement Analysis, retrieval, admission, verifier, stale, permission, self-review, versioning, or review transitions.
- External model calls remain outside database transactions.
- Checkpoint state contains stable IDs/routing only and never secrets or full business payloads.
- Do not apply new Django migration or LangGraph checkpoint schema to real `salesmind` without separate authorization.
- Preserve `.workbuddy/` and `docs/code-review-2026-08-29.md` unchanged and untracked.

---

### Task 1: Dependencies and durable generation idempotency

**Files:**
- Modify: `requirements/base.txt`
- Modify: `config/settings/base.py`
- Modify: `config/settings/test.py`
- Modify: `apps/sales/models.py`
- Modify: `apps/sales/services/solution_persistence.py`
- Create: `apps/sales/migrations/0005_solutiondraftrecord_generation_idempotency.py`
- Create: `apps/sales/tests/test_solution_generation_idempotency.py`

**Interfaces:**
- Produces: `SolutionDraftRecord.generation_idempotency_key`; `generate_and_persist_solution_draft(..., idempotency_key: UUID | None)`.

- [ ] Write tests for same-key replay, provider-call suppression, input mismatch, different keys, concurrent same-key invocation, nullable legacy calls, and immutable key.
- [ ] Run the focused tests and confirm failures are caused by the missing field/API.
- [ ] Add pinned minimal dependencies and settings, the nullable unique UUID field/migration, and session advisory-lock implementation.
- [ ] Run model, migration, persistence, and idempotency tests to GREEN.

### Task 2: Typed thin-wrapper Graph

**Files:**
- Create: `apps/sales/services/solution_review_workflow.py`
- Create: `apps/sales/tests/test_solution_review_workflow.py`

**Interfaces:**
- Produces: `SolutionReviewWorkflowState`, finite stage/outcome/action enums, `build_solution_review_graph(checkpointer)`.
- Consumes: the four existing Solution persistence/review services.

- [ ] Write tests proving explicit analysis ID, service delegation, persisted IDs, minimal interrupt payload, approve/revision routing, both return outcomes, error adaptation, immutable payload, and no duplicated business checks.
- [ ] Run the focused tests and confirm RED.
- [ ] Implement the minimal graph nodes and conditional routes.
- [ ] Run workflow tests to GREEN.

### Task 3: PostgreSQL checkpoint reconstruction and replay recovery

**Files:**
- Create: `apps/sales/services/solution_workflow_checkpoint.py`
- Create: `apps/sales/tests/test_solution_review_workflow_checkpoint.py`

**Interfaces:**
- Produces: explicit PostgreSQL checkpointer context/setup helpers; restart-safe invoke/resume behavior.

- [ ] Write PostgreSQL tests proving pending Review exists before interrupt, reconstruction with the same thread identity, approve and return resume, already-committed identical decision recovery, opposed decision conflict, and database reload after resume.
- [ ] Run tests and confirm RED.
- [ ] Implement the official `PostgresSaver` integration and replay recovery using persisted Review state.
- [ ] Run checkpoint and workflow suites to GREEN.

### Task 4: Regression, review, and schema gate

**Files:**
- Review all Phase 6a changes; no new feature files unless a verified blocker requires a minimal fix.

- [ ] Run focused LangGraph/idempotency tests.
- [ ] Run Solution persistence/review regressions, Sales regressions, and Phase 5 regressions.
- [ ] Run full pytest.
- [ ] Run `manage.py check`, `makemigrations --check --dry-run`, `pip check`, and `git diff --check`.
- [ ] Review replay/idempotency, checkpoint recovery, duplicate side effects, business-rule duplication, secrets, and transaction boundaries.
- [ ] Stop before applying migration or checkpoint schema to real `salesmind`; report exact schema requirements and request authorization.
