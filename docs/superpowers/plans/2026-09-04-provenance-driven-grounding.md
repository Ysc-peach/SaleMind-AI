# Provenance-Driven Grounding Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make approved, current provenance facts the only source of enterprise-fact admission while reducing the LLM to proposal generation and semantic veto.

**Architecture:** Knowledge indexing records committed run identity; a separate strict extraction service persists only proposed facts. Django Admin approval and a deterministic admission engine create immutable fact/customer/unresolved claims, while one LLM call proposes recommendations and one batched verifier call may only veto the assembled atomic claims.

**Tech Stack:** Django 5.2 models/migrations/admin, PostgreSQL 17/pgvector, existing LLM abstraction, pytest/pytest-django.

**Spec:** `docs/superpowers/specs/2026-09-04-provenance-driven-grounding-design.md`

## Global Constraints

- Work in `codex/phase-five-presales`; do not create a worktree.
- Do not modify readiness, retrieval Top3/max8, embedding or generation model, retry behavior, or Phase 5.6 concerns.
- One generation call and one batched verification call; no rewrite, retry, or second retrieval.
- Probabilistic components propose only; deterministic code or authorized human action disposes.
- Preserve `.workbuddy/` and `docs/code-review-2026-08-29.md` unmodified and uncommitted.

---

### Task 1: Persist Versioned Enterprise Grounding Facts

**Files:**
- Modify: `apps/knowledge/models.py`
- Create: `apps/knowledge/migrations/0003_knowledge_grounding_facts.py`
- Create: `apps/knowledge/tests/test_grounding_fact_model.py`

**Interfaces:**
- Produces: `EnterpriseGroundingFact`, `EnterpriseGroundingFactStatus`, `EnterpriseGroundingFactApprovalStatus`, and `KnowledgeDocument.last_index_run_id`.

- [ ] Write database tests proving all four fact statuses, all three approval states, `PROTECT` document provenance, plain chunk snapshot ID, approval metadata consistency, and stale metadata consistency.
- [ ] Run `pytest apps/knowledge/tests/test_grounding_fact_model.py -q` and confirm RED because the model does not exist.
- [ ] Add the enums/model/constraints/indexes and generate migration `0003`.
- [ ] Run the focused test and `python manage.py makemigrations --check --dry-run`; confirm GREEN and no uncommitted migration drift.
- [ ] Review the migration for unrelated operations, then commit model, migration, tests, spec, and plan as `feat: add enterprise grounding facts`.

### Task 2: Record Index Versions and Stale Old Facts

**Files:**
- Modify: `apps/knowledge/services/indexing.py`
- Modify: `apps/knowledge/tests/test_reindexing.py`
- Modify: `apps/knowledge/tests/test_initial_indexing.py`

**Interfaces:**
- Consumes: `KnowledgeDocument.last_index_run_id`, `EnterpriseGroundingFact.is_stale/stale_at`.
- Produces: successful index run identity and successful-reindex stale transition.

- [ ] Add RED tests showing successful indexing records its run UUID, successful reindex preserves old Fact rows while replacing chunks and marks old facts stale, and failed reindex leaves facts active.
- [ ] Run the three new tests and confirm failures identify missing run persistence/stale transition.
- [ ] Set `last_index_run_id=run_id` inside successful indexing transactions and mark prior current facts stale only inside successful reindex completion.
- [ ] Run indexing/reindex focused tests; confirm GREEN and existing zero-downtime behavior remains intact.
- [ ] Review for external calls inside transactions and commit as `feat: add grounding fact stale lifecycle`.

### Task 3: Extract Proposed Facts Outside Transactions

**Files:**
- Create: `apps/knowledge/services/grounding_facts.py`
- Create: `apps/knowledge/tests/test_grounding_fact_extraction.py`

**Interfaces:**
- Produces: `extract_grounding_facts(document_id: int, *, llm_provider: LLMProvider | None = None) -> tuple[EnterpriseGroundingFact, ...]`.
- Uses: controlled subject registry and strict JSON response `{facts:[{subject_key,statement,status,source_chunk_id,source_excerpt}]}`.

- [ ] Add RED tests for valid proposals, unknown subject, malformed/extra JSON, invalid chunk/excerpt, concurrent index change, provider propagation, no approved facts on any failure, and provider execution outside `transaction.atomic()`.
- [ ] Run the focused file and confirm RED because the service is absent.
- [ ] Implement the controlled registry, safe prompt boundary, strict parser, content hashing, and short locked persistence transaction that always creates `PROPOSED` facts.
- [ ] Run focused extraction tests and confirm GREEN without network access.
- [ ] Review that no LLM output can set approval/current provenance fields; commit as `feat: propose enterprise grounding facts`.

### Task 4: Add Business-Role-Gated Admin Approval

**Files:**
- Create: `apps/knowledge/admin.py`
- Create: `apps/knowledge/services/grounding_fact_approval.py`
- Create: `apps/knowledge/tests/test_grounding_fact_admin.py`

**Interfaces:**
- Produces: `approve_grounding_facts(facts, *, actor)` and `reject_grounding_facts(facts, *, actor)` plus read-only Django Admin actions.

- [ ] Add RED tests proving proposed facts cannot self-approve, active business-admin staff can approve/reject, approval actor/time are recorded, sales/presales/technical-superuser roles cannot approve facts, and add/delete/direct edits are unavailable.
- [ ] Run the focused tests and confirm RED because approval/admin boundaries are absent.
- [ ] Implement short transactional approval services and read-only Fact admin actions; leave document/chunk admin registration unchanged.
- [ ] Run focused admin/approval tests and existing account admin tests; confirm GREEN.
- [ ] Review business role checks and commit as `feat: add grounding fact approval`.

### Task 5: Build Deterministic Admission and Fact Claims

**Files:**
- Create: `apps/sales/services/solution_admission.py`
- Create: `apps/sales/tests/test_solution_admission.py`

**Interfaces:**
- Produces: immutable `GroundingAdmission`, `EnterpriseAdmissionDecision`, and `build_solution_admission(analysis, sources)`.
- Produces deterministic `customer_fact`, `enterprise_fact`, and `unresolved` `AtomicSolutionClaim` values.

- [ ] Add RED table tests for confirmed supported/unsupported, unconfirmed, explicit/derived conflict, proposed, rejected, stale, wrong run/hash, and missing subject fallback.
- [ ] Add RED invariant tests that every admitted enterprise claim traces to a current approved confirmed Fact and that N4 subjects never become enterprise facts without such a Fact.
- [ ] Run focused admission tests and confirm RED because the engine is absent.
- [ ] Implement code-owned status mapping, source/run/hash checks, conflict resolution, and deterministic claim templates without prompt rules or lexical NLP.
- [ ] Run focused tests and confirm GREEN, including CSV/OCR/private-deployment/D2/missing regressions.
- [ ] Review fail-safe defaults and commit as `feat: add deterministic grounding admission`.

### Task 6: Generate Only Proposals and Enforce Admission Before Verification

**Files:**
- Modify: `apps/sales/services/solution_schema.py`
- Modify: `apps/sales/services/solution_prompt.py`
- Modify: `apps/sales/services/solution_draft.py`
- Modify: `apps/sales/tests/solution_fakes.py`
- Create: `apps/sales/tests/test_solution_provenance_pipeline.py`
- Modify: existing `apps/sales/tests/test_solution_*.py` files only where the intentionally changed generation envelope requires it.

**Interfaces:**
- Produces: strict proposal-only generation IR and combination with deterministic admitted claims.
- Consumes: `build_solution_admission()` before the LLM and passes only admitted claims to `verify_atomic_solution_claims()`.

- [ ] Add RED tests that LLM output cannot create enterprise/customer/unresolved claims, proposal citations must resolve to approved current confirmed Facts, and verifier `SUPPORTED + ATOMIC` cannot grant N4/D2 enterprise admission.
- [ ] Run the new pipeline tests and confirm RED against the current all-types generation IR.
- [ ] Add strict proposal parsing, provide the LLM only allowed proposal sources/customer context, combine proposals with program-built claims, and reject deterministic admission errors before verifier construction/call.
- [ ] Update fakes at the changed generation boundary and run all Solution tests to GREEN.
- [ ] Review call ordering and commit as `refactor: generate solutions from approved grounding facts`.

### Task 7: Narrow the Verifier to Entailment and Atomicity

**Files:**
- Modify: `apps/sales/services/solution_grounding_prompt.py`
- Modify: `apps/sales/services/solution_grounding.py`
- Modify: `apps/sales/tests/test_solution_atomic_grounding.py`
- Modify: `apps/sales/tests/test_solution_pipeline_hardening.py`
- Modify: other grounding verifier contract tests that assert the superseded business-admission role.

**Interfaces:**
- Keeps: strict batched `{location,relation,atomicity}` response and complete location coverage.
- Removes: verifier responsibility for approval status, staleness, conflict disposal, and statement-type business eligibility.

- [ ] Add RED regressions proving exact unconfirmed text is naturally entailed when already admitted as unresolved, explicit-negative facts are entailed, compound A3/G1 claims are rejected, and unsupported proposals remain insufficient.
- [ ] Run focused verifier tests and confirm failures identify the old type-admission contract.
- [ ] Narrow prompt and packet construction to semantic entailment/atomicity while preserving citation-scoped evidence and full customer context for proposals.
- [ ] Run all grounding tests and confirm GREEN with no verifier grant path.
- [ ] Review fail-closed parsing and commit as `refactor: narrow solution semantic verifier`.

### Task 8: Full Safety Verification and Review

**Files:**
- Modify tests only if review exposes a demonstrated missing safety invariant; write a failing regression before any production fix.

**Interfaces:**
- Verifies the complete Phase 5.5h implementation; produces no new feature.

- [ ] Run Fact model/migration, extraction, approval, admission, reindex/stale, and Solution pipeline focused suites.
- [ ] Run combined Phase 5 regressions and full pytest.
- [ ] Run `python manage.py makemigrations --check --dry-run`, `python manage.py check`, `pip check`, and `git diff --check`.
- [ ] Independently review every probability-to-admission path, reindex lifecycle, provenance survival, transaction boundary, and the five required YES assertions.
- [ ] For each real blocker, write RED, apply the minimal fix, rerun affected focused suites, then repeat full verification.
- [ ] Commit any final test-only invariant coverage as `test: cover provenance grounding safety invariants`; do not create an empty commit.
- [ ] Report commits, migration, tests, review, five YES answers, Git state, and stop before real smoke.
