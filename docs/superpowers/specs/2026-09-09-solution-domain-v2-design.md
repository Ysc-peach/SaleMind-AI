# Solution Domain Model V2 Design

## Status and scope

This document designs the next Solution domain version. It does not authorize implementation and does not change the current Django services, LangGraph workflow, Vue application, database schema, or historical Solution records.

The problem is structural: the current V1 domain can safely represent grounded atomic statements, but it cannot reliably represent a detailed, executable, reviewable enterprise presales technical solution. V2 therefore adds a richer deterministic envelope around the existing claim-level safety architecture. It does not solve the problem by asking the model for longer free-form prose.

V2 excludes architecture-image generation, PDF/Word export, rich-text editing, version diff, quotation/BOM, Gantt charts, electronic signatures, automatic workflow revision loops, and a customer portal.

## Evidence from the current repository

GitNexus was bound to the single indexed repository `SalesMind AI` at commit `05eb7da`, which is the current HEAD. Its graph contains 3,500 symbols, 7,197 edges, and 155 processes.

The graph and source review agree on the present boundaries:

- `SolutionDraft` in `apps/sales/services/solution_schema.py` has only `title`, `executive_summary`, five fixed `solution_sections`, and `assumptions`.
- `SolutionStatement` has a type, text, and citation labels, but no stable statement identity.
- `assemble_solution_draft` deterministically converts admitted/generated atomic claims into those five sections; its summary is a bounded selection of section statements.
- `generate_grounded_solution_draft` builds deterministic admission, asks the generation model only for proposals, verifies proposals, revalidates admission after provider calls, and then assembles the V1 domain value.
- `solution_draft_to_payload` and `solution_draft_from_payload` implement one unversioned V1 JSON shape.
- `SolutionDraftRecord.draft_payload` stores that JSON snapshot, while `SolutionDraftProvenance` identifies a cited statement by `statement_path` plus `citation_label` and preserves the Fact/document/chunk/run/hash/excerpt snapshot.
- The detail API returns the payload plus a flat provenance list. `frontend/src/views/SolutionDetailView.vue` directly iterates the V1 summary, fixed sections, assumptions, and flat sources.
- Both REST creation and LangGraph generation reach assembly through the same four-hop chain: API or `_generate_solution_node` -> `generate_and_persist_solution_draft` -> `_generate_and_persist_solution_draft` -> `generate_grounded_solution_draft` -> `assemble_solution_draft`.

GitNexus classifies changing the existing `SolutionDraft` as HIGH risk (36 impacted symbols, 17 direct) and changing `SolutionDraftRecord`, `SolutionDraftProvenance`, or `generate_grounded_solution_draft` as CRITICAL risk. That is consistent with direct imports across admission, generation, verification, persistence, API, workflow, and many regression tests. The design therefore uses versioned adapters instead of replacing V1 in place.

## Non-negotiable invariants

V2 must preserve all of the following:

- Probabilistic components propose. Deterministic program logic and authorized human decisions dispose.
- Semantic entailment is not business admissibility.
- Only current, non-stale, human-approved, provenance-valid confirmed Facts can create `enterprise_fact` content.
- Missing, unconfirmed, conflicting, proposed, rejected, stale, or provenance-invalid capability evidence cannot become an enterprise capability.
- The semantic verifier sees only model-generated proposals and remains veto-only.
- A proposal survives only when the verifier returns `SUPPORTED + ATOMIC`.
- Provider, parser, verifier, provenance, and persistence failures fail closed; no partial unverified draft is returned or persisted.
- Deterministic admission is revalidated after external calls and again at the persistence boundary.
- External model calls remain outside database transactions.
- Solution versions, their payloads, and durable provenance are immutable. Review state and stale state remain independent lifecycle projections.
- Historical V1 records remain readable and are never rewritten in place.

## Approaches considered

### A. Replace V1 in place

Expand `SolutionDraft`, change its JSON shape, and update every caller at once.

This is rejected. The existing class is directly imported by core services and tests, historical rows have no discriminator, and the current Vue renderer assumes the V1 shape. In-place replacement would make historical payloads ambiguous and create a broad cutover across safety-critical code.

### B. Versioned dual schema with a central atomic-item registry

Keep the V1 domain and mapper intact, add a V2 domain, persist an authoritative schema discriminator, and route mapping/rendering through versioned adapters. V2 stores each semantic proposition once in a central registry and lets structured Solution objects reference stable item IDs.

This is the recommended approach. It preserves claim-level admission and verification, gives provenance a stable target, prevents duplicated prose from drifting across sections, and supports gradual API/frontend adoption without mutating historical versions.

### C. Normalize every nested V2 object into database tables

Create tables for components, phases, risks, criteria, questions, and claim placements.

This is rejected for V2 first release. Solution content is already an immutable version snapshot; normalizing every presentation object would greatly expand migrations, transactions, and audit surface without improving business authority. The only relational data that must remain queryable and protected is the Solution record, review lifecycle, and durable claim-to-evidence provenance.

## Recommended domain architecture

### Central primitive: `SolutionAtomicItem`

Every factual, proposed, unresolved, or assumption-bearing sentence in V2 is stored exactly once as an immutable atomic item:

```text
SolutionAtomicItem
├── item_id                  stable within one Solution version, e.g. C0001
├── item_type                customer_fact | enterprise_fact | proposal | assumption | unresolved
├── text                     one independently reviewable proposition
├── citations[]              admitted source labels only
└── related_requirement_fields[]
```

Rules:

- `customer_fact` is produced from the selected immutable Requirement Analysis and has no enterprise citation.
- `enterprise_fact` is produced only by deterministic admission and has one or more admitted source labels.
- `proposal` is the only model-generated item type. It must have admitted source labels and pass proposal-only semantic verification.
- `unresolved` is produced deterministically from unknown, unclear, conflict, missing, or non-admissible facts and has no enterprise citation.
- `assumption` is a bounded planning constraint derived from explicit analysis gaps. It must reference one or more non-known requirement fields, cannot assert an enterprise capability, and is not a substitute for an open question.
- Text must not contain a second citation channel such as inline `S1`; citations remain structured.
- `item_id` is assigned deterministically after validated assembly in canonical order. It is not generated by the LLM and never changes within an immutable version.

The existing semantic types remain meaningful. V2 adds `assumption` to the enclosing atomic-item vocabulary without changing the fact/admission meaning of the existing four `SolutionStatementType` values. V1 types and decoders remain untouched.

### Why a registry instead of nested copies

Nested structures reference item IDs rather than copying statement objects. This provides:

- one canonical text/type/citation tuple per proposition;
- stable claim-to-evidence mapping independent of array positions;
- deterministic validation that every reference exists and is used in a semantically valid slot;
- reuse of an admitted fact in summary and detail without duplicating provenance rows by rendered position;
- simpler versioned API rendering and future section navigation.

Validation rejects unused registry items. Every summary item must also appear in at least one substantive section, so the summary cannot become a separate channel for otherwise unreviewed claims.

### V2 top-level shape

The recommended domain shape is:

```text
SolutionDraftV2
├── title
├── items[]
├── executive_summary[]                 item IDs
├── customer_context
├── proposed_solution
├── architecture
├── deployment_and_integration[]
├── implementation_plan
├── risks[]
├── acceptance_criteria[]
├── milestones[]
├── assumptions[]                       item IDs of type assumption
├── open_questions[]
└── out_of_scope[]
```

`title` and structural labels are presentation metadata. They must be short labels, not hidden factual paragraphs. All substantive assertions live in `items`.

### Section design

#### `executive_summary`

A bounded ordered list of item IDs. It may reference customer facts, enterprise facts, verified proposals, and unresolved items. It does not contain independent prose and therefore cannot create claims not present elsewhere.

#### `customer_context`

Deterministically assembled from the selected persisted analysis:

```text
CustomerContext
├── confirmed_items[]          customer_fact item IDs
├── unresolved_items[]         unresolved item IDs
└── requirement_fields[]       dimension, status, referenced item IDs
```

This makes the selected analysis visible without copying its entire JSON into the Solution record. The persisted Solution still references the exact `OpportunityRequirementAnalysis` row.

#### `proposed_solution`

```text
ProposedSolution
├── overview_items[]
└── capability_groups[]
    ├── group_id
    ├── title
    └── item_ids[]
```

Enterprise capabilities remain `enterprise_fact`; recommendations remain verified `proposal`. A customer request is never rendered as an enterprise capability. A group is omitted if none of its items survive validation and verification, so a model-supplied structural label cannot imply an unsupported capability by itself.

#### `architecture`

```text
Architecture
├── overview_items[]
└── components[]
    ├── component_id
    ├── name
    ├── responsibility_items[]
    ├── rationale_items[]
    ├── dependency_component_ids[]
    └── interface_items[]
```

Component IDs and names are structural labels. Responsibilities, rationale, and interface descriptions are atomic item references. Component dependencies reference declared component IDs and cannot point to missing/self components. Cycles are permitted because runtime component relationships can be bidirectional; the renderer must not interpret this list as an execution order.

#### `deployment_and_integration`

An ordered set of typed topic blocks such as deployment topology, environment prerequisites, identity integration, data integration, and security boundary:

```text
SolutionTopicBlock
├── block_id
├── topic
├── title
└── item_ids[]
```

`topic` comes from a closed enum; `title` is a short presentation label. Each block contains only item references. Empty blocks are omitted rather than filled with generic prose, and a label never grants or implies enterprise capability.

#### `implementation_plan`

```text
ImplementationPlan
└── phases[]
    ├── phase_id
    ├── name
    ├── objective_items[]
    ├── task_items[]
    ├── owner_roles[]
    ├── deliverable_items[]
    ├── dependency_phase_ids[]
    ├── acceptance_criterion_ids[]
    └── timing_item_id | null
```

`owner_roles` uses a small presentation vocabulary (`sales`, `presales`, `customer`, `joint`, `tbd`) and does not create application permissions. A generated assignment is a recommendation, not an authorization decision.

Phase dependencies must reference earlier declared phases, which makes the plan acyclic by construction. Objectives, tasks, and deliverables are atomic item references. If timing is not present in the selected analysis or approved evidence, the phase uses an `unresolved` timing item such as “实施周期待确认”; it must not invent “2 weeks” or “3 weeks.” A timing value can be:

- confirmed only when its referenced item is a deterministic customer or enterprise fact;
- proposed only when its item is a verified proposal;
- unresolved/TBD only when its item is `unresolved`.

The persisted classification is validated against item type so it cannot drift from the authority of the underlying item.

#### `risks`

```text
RiskItem
├── risk_id
├── condition_item_id
├── impact_item_ids[]
├── mitigation_item_ids[]
└── trigger_item_ids[]
```

Risk conditions commonly reference customer facts or unresolved items. Claimed impacts and mitigations are not exempt from grounding: they must be deterministic facts or verified proposals. When evidence supports only the condition, V2 shows the condition/open question and does not fabricate an impact or mitigation for completeness.

Evidence is not an additional free-text risk field. It is resolved from each referenced atomic item's citations through the claim-to-source mapping.

#### `acceptance_criteria`

```text
AcceptanceCriterion
├── criterion_id
├── criterion_item_id
└── classification           customer_confirmed | proposed | unresolved
```

Validation ties classification to item type:

- `customer_confirmed` requires a `customer_fact` derived from the frozen analysis;
- `proposed` requires a verified `proposal` backed by admitted evidence;
- `unresolved` requires an `unresolved` item.

No model-generated performance number becomes customer-confirmed. If a threshold such as concurrency, response time, or availability is absent, the criterion is unresolved rather than auto-filled.

#### `milestones`

Milestones are separate structural objects because they are useful for review and navigation, but they do not duplicate phase prose:

```text
Milestone
├── milestone_id
├── name
├── related_phase_ids[]
├── outcome_item_ids[]
└── timing_item_id | null
```

Timing obeys the same confirmed/proposed/TBD rule as implementation phases.

#### `assumptions`

An ordered list of `assumption` item IDs. Assumptions remain explicit, gap-bound constraints, not an escape hatch for unsupported customer or enterprise facts.

#### `open_questions`

Open questions are first-class deterministic objects:

```text
OpenQuestion
├── question_id
├── requirement_field
├── requirement_status       unknown | unclear | conflict
├── unresolved_item_id
└── question
```

They are assembled from `build_solution_unresolved_items`, analysis conflicts, and the selected analysis's clarifying questions. Every non-known requirement field must have an open-question representation; known fields must not. This aligns the Solution with `CUSTOMER_INFO_REQUIRED` without implementing an automatic revision loop. A review return can direct Sales back to these questions, but Phase V2 does not modify the review state machine.

#### `out_of_scope`

Each scope exclusion references one atomic item and has a validated classification (`customer_confirmed`, `proposed`, or `unresolved`). The model cannot silently turn missing information into a contractual exclusion.

## Generation and assembly

### Keep deterministic content deterministic

The following continue to be created by Python from the selected analysis and admission:

- customer facts and unresolved requirement items;
- enterprise facts and their exact Fact identities;
- allowed proposal source labels;
- assumption/open-question mappings;
- item IDs, source mappings, title, section order, and final V2 envelope.

### Model output remains a small proposal IR

The generation model should not return a complete `SolutionDraftV2`. It returns only independently verifiable proposals plus bounded placement metadata:

```json
{
  "proposals": [
    {
      "placement": {
        "section": "architecture",
        "container_kind": "component",
        "container_key": "knowledge_service",
        "field": "responsibilities"
      },
      "text": "将已批准的企业知识检索能力用于员工资料查询。",
      "citations": ["S1"]
    }
  ]
}
```

Placement values come from closed enums and validated identifiers. Container labels cannot carry substantive sentences. The model cannot emit `item_type`, approval/status fields, source snapshots, acceptance classification, timing authority, or final payload structure.

The implementation may add V2 proposal placement types alongside `AtomicSolutionClaim`; it must not broaden V1 `SolutionSectionKey` in place. A small adapter turns each validated V2 proposal into the existing verifier packet shape. The verifier evaluates text, cited evidence, customer context, relation, and atomicity exactly as today.

### Final assembly order

```text
selected immutable Requirement Analysis
  -> retrieval and existing deterministic admission
  -> deterministic V2 customer/enterprise/unresolved items
  -> proposal-only generation IR
  -> one proposal per verifier request, bounded concurrency
  -> SUPPORTED + ATOMIC proposals only
  -> return-time admission revalidation
  -> deterministic V2 structure and item IDs
  -> short persistence transaction and insert-time revalidation
```

No nested V2 field bypasses this path.

## Grounding and verifier compatibility

The admission engine, Fact lifecycle, current-index checks, and verifier policy do not need a rewrite.

Required adapters:

- Proposal placement is separated from semantic verification. The verifier packet location may use the proposed canonical item/placement path, but the verifier still receives one proposal only.
- Deterministic items never enter the semantic verifier.
- The result adapter preserves original proposal order and placement after concurrent verification.
- V2 parsing rejects any unsupported free-form field before verification.
- Return-time admission equality remains the gate before V2 assembly.

The compatibility functions that verify a fully assembled V1 draft may remain for V1 tests/callers; V2 production generation continues to call the proposal-only boundary.

## Durable provenance redesign

### Current capability and limitation

The existing provenance row preserves the correct durable evidence snapshot and deliberately avoids a `KnowledgeChunk` foreign key. That remains correct. However, `statement_path` is positional and V1 persistence finds enterprise statements by section/type/text/citations. Nested V2 arrays and reusable summary references make positional paths too fragile as the primary identity.

### V2 design

Add a nullable immutable `claim_id` (named after the existing audit concept, even though it can identify an assumption/unresolved item) to `SolutionDraftProvenance`:

- V1 historical rows keep `claim_id = NULL` and continue to use `statement_path`.
- Every cited V2 item must have a non-null `claim_id` matching an item in the V2 payload.
- `statement_path` remains as a human-readable canonical audit path such as `items.C0007`; it is not the join key used by V2 rendering.
- Persistence maps exact admission provenance to the assembled item during deterministic assembly. It must not rediscover a Fact through fuzzy text matching.
- Fact/document `PROTECT` semantics and chunk/run/hash/excerpt snapshots remain unchanged.

The API derives two presentation structures from immutable provenance rows:

```text
source_registry
  S1 -> document title/id and safe source excerpt

claim_sources
  C0007 -> [S1]
```

The registry deduplicates repeated source snapshots for display. The database still retains exact `EnterpriseGroundingFact` identity for every claim/evidence link. Ordinary business responses omit content hashes, index-run IDs, internal grounding IDs, credentials, and provider responses; those audit values stay in the protected persistence layer.

No new normalized source table is required for the first V2 release.

## Persistence and backward compatibility

### Authoritative schema discriminator

Add `schema_version` to `SolutionDraftRecord` as an immutable positive small integer:

- existing rows are backfilled/defaulted to `1` without changing their payload;
- V1 mappers read and write version `1`;
- new V2 generation explicitly writes version `2`;
- the column, not the JSON body, is authoritative;
- unknown versions fail closed with a stable mapping/API error.

A database column is preferred over a JSON-only field because list APIs, renderer selection, migrations, audit queries, and validation must identify the payload without parsing an untrusted JSON shape. The version must not be duplicated inside `draft_payload`, which would create two authorities.

`schema_version` joins `_IMMUTABLE_FIELDS`. No historical approved draft is converted, regenerated, or rewritten.

### Versioned mapper boundary

Preserve `solution_draft_to_payload` and `solution_draft_from_payload` as explicit V1 compatibility wrappers. Add a versioned adapter with an unambiguous contract, conceptually:

```python
serialize_solution_domain(draft) -> tuple[int, dict]
deserialize_solution_payload(schema_version: int, payload: object) -> SolutionDraft | SolutionDraftV2
```

V2 has its own strict mapper and round-trip tests. The persistence service stores the schema returned by the serializer. Review, stale evaluation, version allocation, and idempotency do not inspect or mutate the nested payload.

### Migration

One Sales migration is required to:

1. add `SolutionDraftRecord.schema_version` with historical value `1`;
2. add nullable `SolutionDraftProvenance.claim_id`;
3. add a check that `schema_version` is one of the implemented versions (`1` or `2`); a future schema version must extend this constraint before it can be persisted;
4. add a nonblank-if-present check and `(solution_draft, claim_id)` index for V2 provenance lookup;
5. include `schema_version` in the record's immutable field contract at application level.

The migration must not transform `draft_payload` or rewrite provenance rows. Applying it to the real `salesmind` database requires separate authorization after automated verification.

## API contract

### List

Add `schema_version` to Solution list and detail metadata. Lists remain compact and do not include payload or provenance.

### Detail

The detail response is version-aware:

```text
id, opportunity, analysis_id, version, schema_version, title,
review_status, is_stale, stale_reasons, created_by, created_at,
draft_payload,
source_registry,
claim_sources
```

- V1 returns its original payload and remains readable through the V1 renderer. Its existing provenance representation can remain during compatibility, but no historical row is rewritten.
- V2 returns the central item registry and structured section references plus deduplicated public source data.
- Internal source hash/run/Fact identifiers remain server-side audit data rather than normal business UI fields.
- Create still requires explicit `analysis_id`; the server does not silently choose latest.

No update/delete endpoint is added. Review APIs and permissions remain unchanged.

## Frontend impact design

The current V1 renderer must remain available. A future renderer dispatches on `schema_version`:

- `1` -> current statement/section renderer;
- `2` -> V2 renderer with section navigation, architecture components, implementation phases, risks, acceptance criteria, milestones, open questions, and out-of-scope sections;
- unknown -> safe unsupported-version state, not a blank page or guessed rendering.

The V2 view should provide:

- section navigation for long plans;
- a sticky version/review/stale summary;
- item-type badges that distinguish confirmed customer facts, confirmed enterprise facts, verified proposals, assumptions, and unresolved items;
- claim-local source links using `claim_sources`, with source details expanded from `source_registry`;
- open questions prominently aligned with “需要补充客户信息”;
- no display of content hashes, index-run IDs, internal grounding IDs, provider output, or credentials.

This design does not require rich-text editing or a generic JSON renderer.

## LangGraph boundary

LangGraph is not modified for V2 design. `_generate_solution_node` calls `generate_and_persist_solution_draft` and stores only Solution ID/version. If the persistence service continues to return `SolutionDraftRecord`, the node contract and checkpoint state do not need to change.

At most, future graph/UI status responses may expose `schema_version` by reading the business record; it must not copy the V2 payload into checkpoint state. Generation idempotency, PostgresSaver, review submission, interrupt/resume, decision replay, and conflict recovery remain unchanged.

The known future workflow alignment change—Sales inspecting a generated draft before submit—must be designed after V2 stabilizes. It is not bundled with the domain migration.

## Existing-system impact matrix

| Area | Impact | Required change | Risk notes |
| --- | --- | --- | --- |
| `solution_schema.py` V1 types/parser | Unchanged | Preserve as version-1 compatibility code | Direct mutation has HIGH graph impact |
| New V2 domain schema | Schema change | Add isolated V2 types, strict validators, deterministic assembler | High-risk new contract; keep substantive text atomic |
| Generation prompt/parser | Schema change | Proposal-only V2 placement IR; closed placement vocabulary | High risk for malformed/unsupported output |
| Deterministic admission | Unchanged | Reuse current facts, decisions, allowed labels, and exact provenance | Must not learn V2 UI/business sections |
| Semantic verifier | Adapter change | Adapt V2 proposals to existing one-proposal packet and restore placement after PASS | Verifier authority and concurrency unchanged |
| Retrieval/readiness | Unchanged | Reuse current explicit-analysis and source path | No new RAG or ranking |
| `GroundedSolutionDraftResult` | Adapter change | Allow the generated domain result to carry V1 or V2 plus exact assembled provenance bindings | Never persist inside generation |
| Persistence mapper | Schema change | Versioned serializer/decoder registry; retain V1 wrappers | GitNexus reports HIGH blast radius |
| `SolutionDraftRecord` | Migration required | Add immutable authoritative `schema_version` | CRITICAL graph impact; preserve history/idempotency/versioning |
| `SolutionDraftProvenance` | Migration required | Add nullable stable `claim_id`; keep snapshots and `statement_path` | CRITICAL graph impact; no `KnowledgeChunk` FK |
| Stale evaluator | Unchanged | Continue validating persisted Fact/document/chunk/run/hash snapshots | Must remain payload-schema agnostic |
| Review workflow | Unchanged | Continue treating payload as immutable and status/stale independently | No new transitions |
| REST serializers/views | Adapter change | Expose schema version and V2 source registry/mapping | Preserve explicit `analysis_id` and safe errors |
| LangGraph generate node | Unchanged contract | Continue receiving record ID/version from persistence | No V2 payload in graph state |
| Vue `SolutionDetailView` | Adapter change later | Versioned renderer and claim-local evidence UI | Keep V1 renderer and role/review actions |
| Tests/evaluation fixtures | Schema-aware extension | Keep all V1 safety regressions; add V2 fixtures and contracts | Do not replace V1 fixtures wholesale |

## High-risk boundaries

1. **Generation IR versus final schema.** Letting the model emit the whole V2 payload would reintroduce model ownership of facts, statuses, timing authority, and structure.
2. **Claim identity and provenance.** Positional paths or post-generation text matching are insufficient for nested reusable items. V2 must carry deterministic item identity from assembly into persistence.
3. **Version dispatch.** An unversioned decoder could misread historical JSON or silently accept future shapes. The database column must be authoritative.
4. **Completeness pressure.** Architecture, risk, timing, and acceptance fields can tempt the model to fabricate content. Empty/omitted and unresolved/TBD are valid outcomes.
5. **Dual rendering.** V1 records must remain readable while V2 is introduced. API and Vue must dispatch explicitly and fail safely on unknown versions.

## RED test contract

### V2 structure and atomicity

1. A canonical V2 payload round-trips domain -> JSON-compatible payload -> domain without semantic loss.
2. Unknown/missing/extra top-level or nested keys are rejected.
3. Duplicate, malformed, or dangling item/component/phase/risk/criterion/milestone/question IDs are rejected.
4. Every substantive nested field is an item reference; free-form factual paragraphs in structural objects are rejected.
5. An item containing multiple independently verifiable propositions is rejected by the existing verifier when it is a proposal.
6. Summary and section reuse reference one item rather than duplicating its text/citations.

### Authority and hallucination boundaries

7. Customer facts come only from the explicit persisted analysis.
8. Enterprise facts come only from deterministic admission and retain exact Fact identity.
9. Only proposals enter the semantic verifier; deterministic items skip it.
10. `SUPPORTED` cannot create an enterprise fact or reclassify unresolved content.
11. Assumptions require non-known related fields and cannot carry enterprise capability citations.
12. Missing timing produces unresolved/TBD, never a fabricated duration.
13. A proposed duration requires a proposal item and verifier PASS; it cannot serialize as confirmed.
14. A missing performance threshold produces an unresolved acceptance criterion.
15. Acceptance classification inconsistent with its item type is rejected.
16. Risk impact/mitigation text without a deterministic or verified item is rejected.

### Nested object validation

17. Architecture components validate unique IDs, existing dependencies, no self-dependency, and item-type-compatible fields.
18. Implementation phases validate stable IDs, earlier-phase dependencies, controlled owner-role values, referenced criteria, and timing authority.
19. Risks validate condition, impact, mitigation, trigger references, and reject dangling items.
20. Milestones validate referenced phases/outcomes and timing authority.
21. Out-of-scope classification must match customer fact, proposal, or unresolved item authority.
22. Empty optional structures remain valid and are not padded by generic model prose.

### Open questions

23. Every analysis dimension with `unknown`, `unclear`, or `conflict` maps to an open question and unresolved item.
24. Known dimensions do not create open questions.
25. Existing clarifying-question text and conflict status survive mapping exactly.
26. `CUSTOMER_INFO_REQUIRED` review history remains independent but can be displayed alongside V2 open questions.

### Provenance and persistence

27. Every cited V2 item maps by stable `claim_id` to exact admitted Fact provenance.
28. A citation without a durable Fact/source snapshot aborts persistence atomically.
29. One source used by multiple claims is deduplicated in `source_registry` while claim mappings remain distinct.
30. Reindex/chunk replacement preserves the historical document/chunk ID/run/hash/excerpt snapshot; no `KnowledgeChunk` FK is added.
31. Insert-time provenance change creates neither Solution nor provenance rows.
32. V2 payload and provenance remain immutable after insertion.

### Backward compatibility and API

33. Existing V1 rows are read with `schema_version=1` and their payloads remain byte-for-byte unchanged by migration.
34. V1 mapper and V1 API serialization retain current behavior.
35. New V2 records persist `schema_version=2` and round-trip through only the V2 mapper.
36. Unknown schema versions fail closed.
37. List/detail responses expose `schema_version`; list remains compact.
38. V2 detail returns central items, structured sections, deduplicated safe source registry, and claim-source mapping.
39. Normal detail output does not expose hashes, index-run IDs, internal Fact IDs, provider responses, or credentials.
40. The create API still passes exactly the requested `analysis_id` and never substitutes latest.

### Existing safety/lifecycle compatibility

41. Proposed, rejected, stale, unconfirmed, conflicting, missing, and provenance-invalid Facts still cannot create enterprise capability content.
42. Proposal verifier failure, timeout, malformed output, insufficient support, or compound output still fails the whole draft without partial leakage.
43. One proposal still equals one verifier request; configured bounded concurrency and output order remain unchanged.
44. Return-time and insert-time provenance revalidation remain active for V2.
45. Stale reasons and review state remain independent and schema-agnostic.
46. Submit/approve/return rules, self-review prohibition, audit immutability, and review history remain unchanged.
47. A stale approved V2 record retains historical approval while becoming stale.

### LangGraph and frontend compatibility

48. LangGraph generation stores the same Solution record ID/version and does not add V2 payload/evidence to checkpoint state.
49. Same-key replay returns the same V2 record without another provider call/version.
50. Process reconstruction, approve/return replay recovery, and conflicting replay behavior remain unchanged.
51. Vue routes V1 and V2 records to different renderers and safely rejects unknown versions.
52. V2 item source links resolve locally through `claim_sources`/`source_registry` and never require scanning the flat provenance list.

## Completion gates for a future implementation

Implementation is complete only when focused V2 tests, all existing Solution grounding/verifier/persistence/review/LangGraph regressions, the frontend suite, full pytest, Django checks, migration checks, dependency checks, TypeScript checks, production build, and diff checks pass. Any real `salesmind` migration or real-data smoke requires separate authorization.
