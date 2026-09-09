# Solution Domain Model V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a versioned, structured, executable Solution domain that preserves atomic grounding, deterministic admission, proposal-only verification, durable provenance, immutable history, and review behavior while keeping all V1 records readable.

**Architecture:** Keep V1 types and payload mapping as compatibility code. Add a V2 central atomic-item registry and structured objects that reference stable item IDs, route new persistence through an authoritative `SolutionDraftRecord.schema_version`, and map durable provenance by stable claim ID rather than rendered array position. Existing admission, verifier policy, stale evaluation, review services, LangGraph orchestration, version allocation, and idempotency remain business boundaries rather than being reimplemented.

**Tech Stack:** Python 3, Django/DRF, PostgreSQL, existing LLM provider interfaces, pytest/pytest-django, Vue 3, TypeScript, Vitest, Vue Test Utils.

**Spec:** `docs/superpowers/specs/2026-09-09-solution-domain-v2-design.md`

## Global Constraints

- Probabilistic components may create only `proposal` items; deterministic code or authorized human action remains authoritative.
- Existing V1 payloads and approved historical records must not be rewritten.
- New persisted V2 records use authoritative `SolutionDraftRecord.schema_version = 2`; existing rows remain version `1`.
- Deterministic admission, proposal-only `SUPPORTED + ATOMIC` verification, one-request-per-proposal concurrency, and both provenance revalidation gates remain unchanged.
- Every substantive V2 sentence is one typed atomic item; nested structures contain item references rather than independent free-form factual prose.
- Missing timing, thresholds, architecture facts, mitigations, or scope decisions remain unresolved/omitted rather than fabricated.
- No external model call may run inside a database transaction.
- Review/stale state, immutable versioning, generation idempotency, and LangGraph checkpoint behavior remain schema-agnostic.
- Do not add a `KnowledgeChunk` foreign key to durable provenance.
- Real `salesmind` migration and real-data smoke require separate authorization.

---

## File structure

**Create**

- `apps/sales/services/solution_schema_v2.py` — V2 atomic items, nested structures, strict validation, and deterministic assembly primitives.
- `apps/sales/services/solution_prompt_v2.py` — proposal-only V2 placement prompt and message builder.
- `apps/sales/services/solution_payloads.py` — authoritative schema-version dispatch and V2 JSON mapper while preserving V1 wrappers.
- `apps/sales/tests/test_solution_schema_v2.py` — V2 domain and nested-structure contracts.
- `apps/sales/tests/test_solution_prompt_v2.py` — closed proposal placement IR and hallucination boundaries.
- `apps/sales/tests/test_solution_payload_versions.py` — V1/V2 round trips and unknown-version rejection.
- `apps/sales/tests/test_solution_v2_pipeline.py` — deterministic admission, proposal verification, revalidation, and V2 assembly.
- `apps/sales/tests/test_solution_v2_provenance.py` — stable claim-to-Fact/source persistence and stale behavior.
- `apps/sales/tests/test_solution_v2_api.py` — versioned list/detail/source-registry contracts.
- `frontend/src/components/solution/SolutionV1Renderer.vue` — extracted existing V1 display.
- `frontend/src/components/solution/SolutionV2Renderer.vue` — structured V2 renderer.
- `frontend/src/components/solution/SolutionSourceDrawer.vue` — claim-local safe source display.
- `frontend/src/test/solution-v2.spec.ts` — V1/V2 routing and V2 interaction tests.

**Modify**

- `apps/sales/models.py` — immutable `schema_version` and nullable immutable provenance `claim_id`.
- `apps/sales/migrations/` — one narrowly scoped Sales migration after `0005`.
- `apps/sales/services/solution_schema.py` — retain V1 behavior; expose only compatibility aliases needed by the version dispatcher.
- `apps/sales/services/solution_draft.py` — select V1/V2 generation strategy and return exact V2 provenance bindings without persistence.
- `apps/sales/services/solution_grounding.py` — adapt a V2 proposal candidate to the existing one-proposal verifier packet; do not change policy.
- `apps/sales/services/solution_persistence.py` — versioned serialization, exact V2 provenance rows, schema-aware idempotency validation.
- `apps/sales/api/solution_draft_serializers.py` — expose schema discriminator and V2 source registry/mapping.
- `frontend/src/types/workflow.ts` — discriminated V1/V2 payload and safe source types.
- `frontend/src/views/SolutionDetailView.vue` — dispatch to V1/V2 renderer while retaining review actions.
- Existing Solution tests — keep V1 regressions explicit and add V2 expectations only where new persistence is exercised.

---

### Task 1: Add the authoritative schema discriminator without rewriting V1

**Files:**
- Modify: `apps/sales/models.py`
- Create: `apps/sales/migrations/0006_solution_domain_schema_version.py`
- Test: `apps/sales/tests/test_solution_persistence_models.py`
- Test: `apps/sales/tests/test_solution_payload_versions.py`

**Interfaces:**
- Produces: `SolutionDraftRecord.schema_version: int`, historical value `1`; `SolutionDraftProvenance.claim_id: str | None`.
- Preserves: existing `draft_payload`, version, review, stale, and idempotency fields.

- [ ] **Step 1: Write model RED tests**

Add tests that create an existing-style record without specifying a schema and assert version `1`, assert `schema_version` is part of the immutable identity, permit V1 provenance with `claim_id=None`, and reject blank non-null claim IDs.

```python
record = SolutionDraftRecord.objects.create(**v1_record_fields)
assert record.schema_version == 1

record.schema_version = 2
with pytest.raises(ValidationError, match="immutable"):
    record.save()
```

- [ ] **Step 2: Run the RED tests**

Run: `pytest apps/sales/tests/test_solution_persistence_models.py apps/sales/tests/test_solution_payload_versions.py -q`

Expected: FAIL because `schema_version` and `claim_id` do not exist.

- [ ] **Step 3: Implement the model fields and immutability**

Add a positive small integer `schema_version` with default `1`, a database check limiting it to `1` or `2`, add it to `_IMMUTABLE_FIELDS`, and add nullable `claim_id` with a nonblank-if-present check and `(solution_draft, claim_id)` index. Preserve the existing provenance uniqueness constraint and V1 nullable behavior.

- [ ] **Step 4: Generate and inspect one migration**

Run: `python manage.py makemigrations sales --name solution_domain_schema_version`

Inspect with: `python manage.py sqlmigrate sales 0006`

Expected: only the two fields, their checks/index, and no data rewrite of `draft_payload` or historical provenance.

- [ ] **Step 5: Run the focused model tests**

Run: `pytest apps/sales/tests/test_solution_persistence_models.py apps/sales/tests/test_solution_payload_versions.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the schema boundary**

```bash
git add apps/sales/models.py apps/sales/migrations/0006_solution_domain_schema_version.py apps/sales/tests/test_solution_persistence_models.py apps/sales/tests/test_solution_payload_versions.py
git commit -m "feat: version persisted solution payload schemas"
```

### Task 2: Define the strict V2 atomic registry and nested domain

**Files:**
- Create: `apps/sales/services/solution_schema_v2.py`
- Test: `apps/sales/tests/test_solution_schema_v2.py`

**Interfaces:**
- Produces: `SolutionAtomicItem`, `SolutionItemType`, `SolutionDraftV2`, `ArchitectureV2`, `ArchitectureComponentV2`, `ImplementationPlanV2`, `ImplementationPhaseV2`, `RiskItemV2`, `AcceptanceCriterionV2`, `MilestoneV2`, `OpenQuestionV2`, and `ScopeItemV2`.
- Produces: `validate_solution_draft_v2(draft: SolutionDraftV2) -> None`.

- [ ] **Step 1: Write RED tests for atomic-item authority**

Test the exact five item types, stable item IDs, citation rules, related requirement fields, and immutable tuple-based values.

```python
item = SolutionAtomicItem(
    item_id="C0001",
    item_type=SolutionItemType.CUSTOMER_FACT,
    text="客户要求私有化部署。",
    citations=(),
    related_requirement_fields=(RequirementDimension.DEPLOYMENT_REQUIREMENT,),
)
assert item.item_type is SolutionItemType.CUSTOMER_FACT
```

Include negative cases: customer fact with enterprise citation, proposal without citation, unresolved with enterprise citation, assumption without a non-known related field, inline source token, duplicate ID, and multi-sentence structural label.

- [ ] **Step 2: Write RED tests for nested references**

Build the smallest valid V2 draft and then mutate fixtures to contain dangling item/component/phase/criterion IDs, self component dependencies, forward/cyclic phase dependencies, invalid owner-role values, and classifications inconsistent with item type.

- [ ] **Step 3: Confirm the schema tests fail**

Run: `pytest apps/sales/tests/test_solution_schema_v2.py -q`

Expected: FAIL because the V2 types do not exist.

- [ ] **Step 4: Implement frozen V2 dataclasses and closed enums**

Use frozen slotted dataclasses. Keep substantive fields as item-ID tuples. Structural names must pass a short-label validator; they must not accept paragraphs or inline source tokens.

- [ ] **Step 5: Implement whole-draft graph validation**

Build lookup maps once, validate every reference, validate classification-to-item-type rules, and require phase dependency IDs to precede the current phase. Do not repair malformed input.

- [ ] **Step 6: Run V2 schema tests**

Run: `pytest apps/sales/tests/test_solution_schema_v2.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the V2 domain contract**

```bash
git add apps/sales/services/solution_schema_v2.py apps/sales/tests/test_solution_schema_v2.py
git commit -m "feat: define structured solution domain v2"
```

### Task 3: Add versioned payload mapping and preserve V1 reads

**Files:**
- Create: `apps/sales/services/solution_payloads.py`
- Modify: `apps/sales/services/solution_persistence.py`
- Test: `apps/sales/tests/test_solution_payload_versions.py`
- Test: `apps/sales/tests/test_solution_persistence_mapping.py`

**Interfaces:**
- Produces: `SerializedSolutionDraft(schema_version: int, payload: dict)`.
- Produces: `serialize_solution_domain(draft: SolutionDraft | SolutionDraftV2) -> SerializedSolutionDraft`.
- Produces: `deserialize_solution_payload(schema_version: int, payload: object) -> SolutionDraft | SolutionDraftV2`.
- Preserves: `solution_draft_to_payload` and `solution_draft_from_payload` as V1-only compatibility functions.

- [ ] **Step 1: Write RED round-trip and dispatch tests**

Assert V1 round-trip and canonical payload are unchanged, V2 round-trip preserves every nested reference, schema version is not duplicated inside JSON, and versions other than `1` or `2` fail with a stable persistence mapping error.

```python
serialized = serialize_solution_domain(v2_draft)
assert serialized.schema_version == 2
assert "schema_version" not in serialized.payload
assert deserialize_solution_payload(2, serialized.payload) == v2_draft
```

- [ ] **Step 2: Confirm RED**

Run: `pytest apps/sales/tests/test_solution_payload_versions.py apps/sales/tests/test_solution_persistence_mapping.py -q`

Expected: FAIL at the missing version dispatcher while all unchanged V1 tests pass.

- [ ] **Step 3: Implement strict V2 JSON mapping**

Serialize tuples to lists and enums to values; parse exact key sets and call `validate_solution_draft_v2`. Do not use Python repr, pickle, dataclass module paths, provider objects, or credentials.

- [ ] **Step 4: Implement explicit dispatcher and V1 wrappers**

Use an explicit `if schema_version == 1/2` dispatch. Do not infer version from JSON keys and do not silently fall back.

- [ ] **Step 5: Run mapper tests**

Run: `pytest apps/sales/tests/test_solution_payload_versions.py apps/sales/tests/test_solution_persistence_mapping.py -q`

Expected: PASS, including byte-for-byte V1 fixture expectations.

- [ ] **Step 6: Commit the mapper boundary**

```bash
git add apps/sales/services/solution_payloads.py apps/sales/services/solution_persistence.py apps/sales/tests/test_solution_payload_versions.py apps/sales/tests/test_solution_persistence_mapping.py
git commit -m "feat: map versioned solution domain payloads"
```

### Task 4: Build deterministic customer context, assumptions, and open questions

**Files:**
- Modify: `apps/sales/services/solution_schema_v2.py`
- Test: `apps/sales/tests/test_solution_schema_v2.py`
- Test: `apps/sales/tests/test_solution_v2_pipeline.py`

**Interfaces:**
- Produces: `build_v2_deterministic_items(analysis, admission) -> V2DeterministicContent`.
- Produces: exact customer/enterprise/unresolved/assumption items and open questions before any model output is assembled.

- [ ] **Step 1: Write RED tests for deterministic ownership**

Cover known requirement -> customer fact, non-known requirement -> unresolved item/open question, conflict preservation, admitted enterprise Fact -> enterprise item, and missing/non-admitted Fact -> unresolved rather than capability.

- [ ] **Step 2: Write RED open-question completeness tests**

Assert every unknown/unclear/conflict dimension appears exactly once, existing clarifying-question wording is preserved, known fields do not appear, and assumptions reference only non-known dimensions.

- [ ] **Step 3: Confirm RED**

Run: `pytest apps/sales/tests/test_solution_schema_v2.py apps/sales/tests/test_solution_v2_pipeline.py -q`

Expected: FAIL at the missing deterministic V2 builder.

- [ ] **Step 4: Implement deterministic item seeds**

Create immutable internal seeds that retain the originating admission claim object and exact `EnterpriseClaimProvenance` Fact IDs. Do not locate Facts by natural-language similarity.

- [ ] **Step 5: Assign canonical stable IDs**

Assign IDs after validated canonical ordering. Return an exact internal mapping from each item ID/citation label to Fact ID so persistence can consume it without re-discovery.

- [ ] **Step 6: Run deterministic V2 tests**

Run: `pytest apps/sales/tests/test_solution_schema_v2.py apps/sales/tests/test_solution_v2_pipeline.py -q`

Expected: PASS.

- [ ] **Step 7: Commit deterministic V2 assembly inputs**

```bash
git add apps/sales/services/solution_schema_v2.py apps/sales/tests/test_solution_schema_v2.py apps/sales/tests/test_solution_v2_pipeline.py
git commit -m "feat: build deterministic v2 solution context"
```

### Task 5: Add the proposal-only V2 placement IR

**Files:**
- Create: `apps/sales/services/solution_prompt_v2.py`
- Modify: `apps/sales/services/solution_schema_v2.py`
- Test: `apps/sales/tests/test_solution_prompt_v2.py`
- Test: `apps/sales/tests/test_solution_v2_pipeline.py`

**Interfaces:**
- Produces: `SolutionV2Placement`, `AtomicSolutionProposalV2`, `AtomicSolutionProposalSetV2`.
- Produces: `build_solution_v2_messages(analysis, readiness, sources, admission) -> list[LLMMessage]`.
- Produces: `parse_atomic_solution_v2_proposals(content, allowed_source_labels) -> AtomicSolutionProposalSetV2`.

- [ ] **Step 1: Write RED parser tests**

Accept only `proposals` with exact `placement`, `text`, and `citations`. Reject model-supplied item types, Facts, approval/status, timing authority, source snapshots, full sections, unknown placement values, arbitrary nested prose, duplicate keys, and citations outside admitted labels.

- [ ] **Step 2: Write RED hallucination-boundary tests**

Cover fabricated durations, performance thresholds, unsupported component responsibilities, generic risk mitigations, and prompt/evidence injection. A duration may be emitted only as a proposal candidate with admitted evidence; it cannot be marked confirmed by model output.

- [ ] **Step 3: Confirm RED**

Run: `pytest apps/sales/tests/test_solution_prompt_v2.py -q`

Expected: FAIL because the V2 prompt/parser is absent.

- [ ] **Step 4: Implement the closed placement schema**

Use enums for top-level section, container kind, and field. Validate short `container_key` identifiers. Keep labels presentation-only and prohibit hidden factual paragraphs.

- [ ] **Step 5: Implement the V2 generation prompt**

State explicitly that all deterministic facts, authority classifications, sources, and final structure are program-owned; the model returns only atomic proposals. Keep all input regions untrusted.

- [ ] **Step 6: Run prompt/parser tests**

Run: `pytest apps/sales/tests/test_solution_prompt_v2.py apps/sales/tests/test_solution_schema_v2.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the V2 proposal IR**

```bash
git add apps/sales/services/solution_prompt_v2.py apps/sales/services/solution_schema_v2.py apps/sales/tests/test_solution_prompt_v2.py apps/sales/tests/test_solution_v2_pipeline.py
git commit -m "feat: generate atomic v2 solution proposals"
```

### Task 6: Integrate V2 with the existing verifier and revalidation gates

**Files:**
- Modify: `apps/sales/services/solution_draft.py`
- Modify: `apps/sales/services/solution_grounding.py`
- Modify: `apps/sales/services/solution_schema_v2.py`
- Test: `apps/sales/tests/test_solution_v2_pipeline.py`
- Test: `apps/sales/tests/test_solution_proposal_only_verification.py`
- Test: `apps/sales/tests/test_solution_proposal_bounded_concurrency.py`

**Interfaces:**
- Extends: `generate_grounded_solution_draft(..., schema_version=1)` with explicit V2 selection while preserving default V1 compatibility for direct legacy callers.
- Produces: `GroundedSolutionDraftResult.draft` as V1/V2 union plus exact V2 item-to-Fact provenance bindings.
- Reuses: `verify_atomic_solution_proposals` semantics and concurrency.

- [ ] **Step 1: Write RED pipeline tests**

Assert explicit V2 selection reaches the V2 parser/assembler, deterministic items skip verification, every generated proposal creates exactly one verifier request, placements survive concurrent completion order, and only `SUPPORTED + ATOMIC` proposals enter the assembled V2 record.

- [ ] **Step 2: Add safety RED cases**

Assert verifier `SUPPORTED` cannot grant an unconfirmed enterprise capability, requirement-only capability remains impossible, any verifier failure aborts the entire V2 draft, and no partial proposals leak.

- [ ] **Step 3: Add TOCTOU RED cases**

Invalidate Fact approval/stale/index provenance during the external call and assert the existing return-time admission rebuild rejects V2 before assembly.

- [ ] **Step 4: Confirm RED**

Run: `pytest apps/sales/tests/test_solution_v2_pipeline.py -q`

Expected: FAIL at missing V2 strategy selection.

- [ ] **Step 5: Implement a thin strategy branch**

Share readiness, retrieval, admission, provider choice, proposal verification, and return-time revalidation. Branch only at prompt/parser and deterministic final assembly. Do not copy the whole pipeline into a second function.

- [ ] **Step 6: Adapt V2 proposals to verifier packets**

Convert each proposal's text/citations to the existing semantic packet and use a canonical V2 location. Return verified proposals in original order with placement metadata. Do not add V2 business rules to the verifier prompt.

- [ ] **Step 7: Run focused and existing safety regressions**

Run: `pytest apps/sales/tests/test_solution_v2_pipeline.py apps/sales/tests/test_solution_proposal_only_verification.py apps/sales/tests/test_solution_proposal_bounded_concurrency.py apps/sales/tests/test_solution_provenance_pipeline.py -q`

Expected: PASS.

- [ ] **Step 8: Commit pipeline integration**

```bash
git add apps/sales/services/solution_draft.py apps/sales/services/solution_grounding.py apps/sales/services/solution_schema_v2.py apps/sales/tests/test_solution_v2_pipeline.py apps/sales/tests/test_solution_proposal_only_verification.py apps/sales/tests/test_solution_proposal_bounded_concurrency.py
git commit -m "feat: assemble grounded solution domain v2"
```

### Task 7: Persist V2 with exact claim-level durable provenance

**Files:**
- Modify: `apps/sales/services/solution_persistence.py`
- Modify: `apps/sales/services/solution_draft.py`
- Test: `apps/sales/tests/test_solution_v2_provenance.py`
- Test: `apps/sales/tests/test_solution_persistence_service.py`

**Interfaces:**
- Extends: `generate_and_persist_solution_draft(..., schema_version=2)`; normal API/graph calls default to new schema `2` only after this task's full focused gate passes.
- Consumes: exact V2 provenance bindings returned by generation.
- Produces: one immutable `SolutionDraftRecord(schema_version=2)` plus `SolutionDraftProvenance(claim_id=...)` rows.

- [ ] **Step 1: Write persistence RED tests**

Assert successful V2 generation stores version `2`, exact analysis ID, version sequence, item registry, and exact claim IDs. Assert a V1 explicit call still stores version `1` and remains readable.

- [ ] **Step 2: Write provenance RED tests**

Use duplicate statement text in different items and assert each item maps to its exact Fact without text matching. Assert proposal citations map through admitted label-to-Fact bindings. Assert a missing binding aborts the record and provenance transaction.

- [ ] **Step 3: Write idempotency/schema RED tests**

Same key and same inputs returns the existing record without provider calls. Reusing a key while requesting a different schema fails before the provider. Concurrent same-key calls still create one version.

- [ ] **Step 4: Confirm RED**

Run: `pytest apps/sales/tests/test_solution_v2_provenance.py apps/sales/tests/test_solution_persistence_service.py -q`

Expected: FAIL because persistence is not schema-aware.

- [ ] **Step 5: Implement schema-aware persistence**

Pass explicit schema selection to generation, call `serialize_solution_domain`, store the returned schema/payload, and include schema in idempotency input compatibility. Keep providers before `transaction.atomic()`.

- [ ] **Step 6: Replace V2 positional matching with exact bindings**

For V2, build rows directly from `(item_id, citation_label, fact_id)` bindings. Keep the current V1 `statement_path` behavior only for V1 compatibility. Use `items.<item_id>` as the V2 audit path.

- [ ] **Step 7: Verify failure atomicity and stale reuse**

Run: `pytest apps/sales/tests/test_solution_v2_provenance.py apps/sales/tests/test_solution_persistence_service.py apps/sales/tests/test_solution_persistence_models.py -q`

Expected: PASS, including insert-time drift rollback, no orphan provenance, and unchanged stale reasons.

- [ ] **Step 8: Commit durable V2 persistence**

```bash
git add apps/sales/services/solution_persistence.py apps/sales/services/solution_draft.py apps/sales/tests/test_solution_v2_provenance.py apps/sales/tests/test_solution_persistence_service.py
git commit -m "feat: persist v2 claims with durable provenance"
```

### Task 8: Expose versioned API payloads and safe claim-local sources

**Files:**
- Modify: `apps/sales/api/solution_draft_serializers.py`
- Modify: `apps/sales/api/solution_draft_views.py`
- Test: `apps/sales/tests/test_solution_v2_api.py`
- Test: `apps/sales/tests/test_solution_draft_api.py`

**Interfaces:**
- Produces list field: `schema_version`.
- Produces V2 detail fields: `draft_payload`, `source_registry`, `claim_sources`.
- Preserves: explicit `analysis_id`, existing permissions, review endpoints, safe errors, and compact list behavior.

- [ ] **Step 1: Write API RED tests**

Assert V1 and V2 list/detail discrimination, compact lists, V1 readability, V2 structured payload, deduplicated source registry, claim-local source references, unknown-version safe failure, and explicit selected analysis.

- [ ] **Step 2: Write sensitive-field RED tests**

Assert normal V2 detail output omits `source_content_hash`, `source_index_run_id`, internal grounding Fact IDs, provider raw responses, prompts, and credentials.

- [ ] **Step 3: Confirm RED**

Run: `pytest apps/sales/tests/test_solution_v2_api.py apps/sales/tests/test_solution_draft_api.py -q`

Expected: FAIL because the serializers do not expose V2 metadata/mapping.

- [ ] **Step 4: Implement schema-aware serializers**

Build one deduplicated registry per detail response from prefetched immutable provenance. Use `claim_id` keys for V2. Do not parse nested text or scan citation strings in the serializer.

- [ ] **Step 5: Preserve API error and permission boundaries**

Keep the existing view exception adapters and `SolutionDraftPermission`; do not authorize based on schema version or client UI state.

- [ ] **Step 6: Run API and review regressions**

Run: `pytest apps/sales/tests/test_solution_v2_api.py apps/sales/tests/test_solution_draft_api.py apps/sales/tests/test_solution_review_api.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the V2 API adapter**

```bash
git add apps/sales/api/solution_draft_serializers.py apps/sales/api/solution_draft_views.py apps/sales/tests/test_solution_v2_api.py apps/sales/tests/test_solution_draft_api.py
git commit -m "feat: expose versioned solution detail payloads"
```

### Task 9: Add the Vue V2 renderer while keeping V1 visible

**Files:**
- Modify: `frontend/src/types/workflow.ts`
- Create: `frontend/src/components/solution/SolutionV1Renderer.vue`
- Create: `frontend/src/components/solution/SolutionV2Renderer.vue`
- Create: `frontend/src/components/solution/SolutionSourceDrawer.vue`
- Modify: `frontend/src/views/SolutionDetailView.vue`
- Create: `frontend/src/test/solution-v2.spec.ts`
- Modify: `frontend/src/test/workflow.spec.ts`

**Interfaces:**
- Consumes: `schema_version`, V1/V2 `draft_payload`, `source_registry`, and `claim_sources`.
- Preserves: submit/approve/return actions, role UX, stale display, and review history.

- [ ] **Step 1: Write renderer RED tests**

Assert schema `1` renders current content, schema `2` renders section navigation/components/phases/risks/criteria/open questions/out-of-scope, unknown versions show a safe unsupported state, and no generic JSON dump appears.

- [ ] **Step 2: Write source UX RED tests**

Click a V2 item source link and assert only its referenced safe sources appear. Assert hashes, index-run IDs, grounding IDs, and provider responses are absent.

- [ ] **Step 3: Confirm RED**

Run from `frontend`: `npm test -- --run src/test/solution-v2.spec.ts src/test/workflow.spec.ts`

Expected: FAIL because no versioned renderer exists.

- [ ] **Step 4: Add discriminated TypeScript types**

Use `schema_version: 1 | 2` as the discriminator and exhaustive renderer selection. Do not use `any` or infer the version from payload keys.

- [ ] **Step 5: Extract the V1 renderer without changing its behavior**

Move current summary/sections/assumptions rendering into `SolutionV1Renderer.vue`. Keep the review panel and actions in `SolutionDetailView.vue`.

- [ ] **Step 6: Implement the V2 structured renderer**

Render long content with section navigation and a sticky version/review/stale summary. Resolve every item through the central registry and show type badges. Omit empty optional sections instead of inventing copy.

- [ ] **Step 7: Implement claim-local safe sources**

Resolve `claim_sources[item_id]` against `source_registry`; show document label/title and excerpt on demand. Keep internal audit fields absent.

- [ ] **Step 8: Run frontend gates**

Run from `frontend`:

```bash
npm test
npm run type-check
npm run build
```

Expected: all PASS.

- [ ] **Step 9: Commit the V2 renderer**

```bash
git add frontend/src/types/workflow.ts frontend/src/components/solution frontend/src/views/SolutionDetailView.vue frontend/src/test/solution-v2.spec.ts frontend/src/test/workflow.spec.ts
git commit -m "feat: render structured solution domain v2"
```

### Task 10: Prove legacy, safety, review, and LangGraph compatibility

**Files:**
- Modify only failing tests or the smallest responsible V2 adapter; do not weaken assertions.
- Test: `apps/sales/tests/test_solution_admission.py`
- Test: `apps/sales/tests/test_solution_provenance_pipeline.py`
- Test: `apps/sales/tests/test_solution_proposal_only_verification.py`
- Test: `apps/sales/tests/test_solution_proposal_bounded_concurrency.py`
- Test: `apps/sales/tests/test_solution_persistence_service.py`
- Test: `apps/sales/tests/test_solution_review_service.py`
- Test: `apps/sales/tests/test_solution_review_workflow.py`

**Interfaces:**
- Verifies: no changes to business authority, replay/idempotency, review, stale, or checkpoint state.

- [ ] **Step 1: Run focused V2 suites**

Run:

```bash
pytest apps/sales/tests/test_solution_schema_v2.py apps/sales/tests/test_solution_prompt_v2.py apps/sales/tests/test_solution_payload_versions.py apps/sales/tests/test_solution_v2_pipeline.py apps/sales/tests/test_solution_v2_provenance.py apps/sales/tests/test_solution_v2_api.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the safety and persistence suites**

Run:

```bash
pytest apps/sales/tests/test_solution_admission.py apps/sales/tests/test_solution_provenance_pipeline.py apps/sales/tests/test_solution_proposal_only_verification.py apps/sales/tests/test_solution_proposal_bounded_concurrency.py apps/sales/tests/test_solution_persistence_mapping.py apps/sales/tests/test_solution_persistence_service.py -q
```

Expected: PASS with all unsafe-admission and fail-closed invariants unchanged.

- [ ] **Step 3: Run review and LangGraph suites**

Run:

```bash
pytest apps/sales/tests/test_solution_review_models.py apps/sales/tests/test_solution_review_service.py apps/sales/tests/test_solution_review_api.py apps/sales/tests/test_solution_review_concurrency.py apps/sales/tests/test_solution_review_workflow.py -q
```

Expected: PASS; graph state remains IDs/routing only and same-key replay returns one version.

- [ ] **Step 4: Run the full backend suite**

Run: `pytest`

Expected: zero failures/errors.

- [ ] **Step 5: Run framework and repository gates**

Run:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
pip check
git diff --check
```

Expected: all commands exit successfully and no migration beyond the reviewed `0006` is generated.

- [ ] **Step 6: Perform independent source review**

Review the final diff for: unsupported prose paths, proposal-only verifier input, exact item-to-Fact binding, no transaction across provider calls, V1 decoder preservation, unknown-version failure, stale/review schema independence, idempotency schema matching, no payload in LangGraph checkpoints, safe API sources, and immutable content.

- [ ] **Step 7: Commit any review-only correction separately**

If the review finds a real defect, first add a reproducing RED test, apply the smallest fix, rerun affected and full gates, then commit with a message describing the invariant. If no defect is found, create no extra commit.

- [ ] **Step 8: Stop before the real database gate**

Report the migration file, automated evidence, and current real database status. Do not apply `sales.0006` or run a real V2 smoke until separately authorized.

---

## Implementation sequencing rationale

The schema discriminator and V1 preservation come first because every later layer needs an unambiguous compatibility boundary. The pure V2 domain and mapper are established before provider changes. Deterministic content is then built before proposal generation, preventing the prompt from becoming the owner of final structure. Verifier integration precedes persistence so only validated artifacts can reach the database. API and Vue changes happen only after the persisted contract is stable. The final gate explicitly re-runs Phase 5/5.6/6 safety paths because GitNexus identifies the generation and persistence boundaries as HIGH/CRITICAL blast-radius code.
