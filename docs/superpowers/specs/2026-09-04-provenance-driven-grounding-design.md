# Provenance-Driven Grounding Core Design

## Scope

Phase 5.5h replaces LLM-granted enterprise capability admission with approved, current knowledge facts. It changes only knowledge grounding and Solution Claim admission. It does not add an HTTP API, Solution persistence, review lifecycle, LangGraph, asynchronous workers, model switching, probabilistic subject merging, or a provenance graph UI.

The existing pipeline remains responsible for deterministic readiness, three retrieval intents, Top3 search per intent, round-robin evidence merge, at most eight sources, one Solution generation call, one batched semantic verification call, no retry, no rewrite, and fail-closed behavior.

## Current Repository Facts

- `KnowledgeDocument` owns uploaded knowledge and indexing state.
- `KnowledgeChunk` is replaced by `_complete_reindexing()` and therefore cannot be a durable provenance foreign key.
- successful indexing currently clears the transient `indexing_run_id`; Phase 5.5h adds `last_index_run_id` to retain the committed knowledge version.
- `generate_grounded_solution_draft()` retrieves `SolutionSource` values and currently lets the generation LLM propose every statement type.
- `verify_atomic_solution_claims()` receives claim-scoped evidence, returns relation plus atomicity, and rejects anything except `SUPPORTED + ATOMIC`.
- Django Admin currently registers the custom user only. `KnowledgeDocument` and `KnowledgeChunk` intentionally remain unregistered.
- application business roles are `admin`, `sales`, and `presales`; a business admin without Django `is_staff` cannot enter Django Admin.

## Security Invariant

Probabilistic components may propose. Deterministic code or an authorized human disposes.

An `enterprise_fact` in a final draft must have at least one matching `EnterpriseGroundingFact` that is:

- `APPROVED`;
- not stale;
- attached to the current committed document index run;
- attached to the exact retrieved chunk snapshot by ID and SHA-256 content hash; and
- `CONFIRMED_SUPPORTED` or `CONFIRMED_UNSUPPORTED`.

The semantic verifier can veto an already admitted claim. `SUPPORTED` can never create admission eligibility.

## Persistence Model

`KnowledgeDocument.last_index_run_id` stores the UUID of the most recently committed index version. It is nullable for pre-existing documents that have not yet been reindexed under this contract.

`EnterpriseGroundingFact` belongs to the knowledge app and stores:

- controlled `subject_key`;
- immutable proposed `statement`;
- `status`: `CONFIRMED_SUPPORTED`, `CONFIRMED_UNSUPPORTED`, `UNCONFIRMED`, or `CONFLICT`;
- `source_document` using `PROTECT`;
- plain integer `source_chunk_id`, never a foreign key;
- copied `source_excerpt`;
- `source_index_run_id`;
- `source_content_hash`;
- `approval_status`: `PROPOSED`, `APPROVED`, or `REJECTED`;
- nullable approval actor/time;
- stale flag/time; and
- creation time.

Database constraints keep status values valid, approval metadata consistent, and stale metadata consistent. Indexes support current approved subject lookup and document/run lifecycle operations.

## Controlled Subjects

V1 uses a small code-owned registry. Every key has a stable display label and default Solution section. Extraction output containing an unknown key is rejected. No embedding, LLM, or similarity score may merge subjects or transfer approval between subjects.

The initial registry covers the established Phase 5 regression subjects: private deployment, intranet data residency, public-network transfer, PostgreSQL, pgvector, OA, SSO, Kubernetes, Oracle, contract generation, CSV bulk export, scanned-PDF OCR, JWT authentication, and enterprise knowledge query.

## Index and Extraction Lifecycle

Indexing and reindexing commit chunks and `last_index_run_id` in their existing short database transaction. Successful reindex also marks every prior non-stale fact for that document stale in the same short commit. Failed reindex leaves the previous chunks and facts unchanged.

Fact extraction is a separate service call after a document is ready. It snapshots current chunks and the committed run ID, exits any transaction, performs one LLM call, strictly validates the response, then opens a short transaction. The transaction locks the document, verifies that the run ID is still current, and creates only `PROPOSED` facts. A malformed/provider failure creates no facts and never rolls back successful indexing.

The LLM proposes only subject, statement, status, chunk ID, and excerpt. Program code supplies the document, committed run ID, content hash, approval state, and stale state.

## Human Approval

`EnterpriseGroundingFact` is registered in Django Admin without add/delete access. Fields are read-only; admin actions approve or reject proposed facts. Fact administration additionally requires an active Django staff user with business role `admin`, so technical flags do not bypass the business role for this capability.

Approval records `approved_by` and `approved_at`. Rejection clears approval metadata. The service rejects inactive or non-admin business actors.

## Deterministic Admission

Admission evaluates facts for the chunks actually present in the merged evidence set. A fact is current only when its document is ready, its run ID equals `last_index_run_id`, its chunk ID is present, and its stored content hash equals the retrieved chunk content hash.

For each controlled subject:

- active approved `CONFIRMED_SUPPORTED` facts create positive enterprise slots;
- active approved `CONFIRMED_UNSUPPORTED` facts create negative enterprise slots;
- active approved `UNCONFIRMED` facts create unresolved slots;
- an approved `CONFLICT`, or simultaneous active supported and unsupported facts, creates one unresolved conflict slot with attention required;
- only proposed, rejected, stale, or no facts yields an `UNCONFIRMED` fallback and no enterprise slot.

No rule above is placed in an LLM prompt.

## Claim Construction and Generation

Program code constructs customer facts from known typed Requirement Analysis fields, customer unresolved items from non-known fields, enterprise facts from confirmed admission slots, and enterprise unresolved items from unconfirmed/conflict admission slots.

The generation LLM is reduced to proposing `proposal` claims. Proposal JSON retains section, text, and structured source citations. A proposal citation is admissible only when it resolves to an active approved confirmed enterprise fact. Proposals still undergo semantic and atomicity verification against full frozen customer context and their citation-scoped approved enterprise evidence.

This makes customer, enterprise, and unresolved fact identity deterministic while preserving LLM creativity for recommendations.

## Semantic Verification

The verifier judges natural entailment and atomicity only:

- `SUPPORTED`, `INSUFFICIENT`, or `CONTRADICTED` has its ordinary evidence-entailment meaning;
- `ATOMIC` or `COMPOUND` remains an independent safety decision;
- proposal support must cover the customer direction and cited enterprise capability;
- non-proposal facts arrive only after deterministic admission.

The verifier cannot approve a Fact, change status, resolve conflicts, mark a stale Fact current, or add a missing enterprise slot.

## Fail-Safe Defaults

- Missing subject Fact: `UNCONFIRMED`.
- Extraction failure: no proposed facts and therefore no confirmed admission.
- Proposed/rejected/stale Fact: no confirmed admission.
- Current approved conflict: unresolved plus attention.
- Missing/duplicate/unknown verifier result: reject the draft.
- Any deterministic admission mismatch: reject before calling the verifier.

## Testing Strategy

TDD covers model constraints, strict extraction, approval, stale lifecycle, deterministic admission, the N4 permanent regression, explicit-negative CSV/OCR, private deployment, D2, environment overclaim, A3/G1 compound claims, cross-section customer context, and the invariant that a mocked `SUPPORTED + ATOMIC` verifier cannot grant an inadmissible enterprise fact.
