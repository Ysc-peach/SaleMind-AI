# Phase 5.6a Immutable Solution Version Persistence Design

## Scope

Phase 5.6a persists a successfully generated, validated `SolutionDraft` as an immutable per-Opportunity version together with durable grounding provenance. It adds create, list, and detail APIs only. Review transitions and review history remain out of scope.

## Boundaries

- The existing domain `services.solution_schema.SolutionDraft` remains distinct from the ORM `SolutionDraftRecord`.
- The caller supplies one explicit persisted `OpportunityRequirementAnalysis`; no latest-analysis lookup occurs during generation.
- `generate_grounded_solution_draft` remains read-only and keeps all external model calls outside database transactions.
- A separate application service persists only a generated result, inside a short transaction that locks the Opportunity, revalidates admission/provenance, allocates the next version, and atomically inserts the record and provenance rows.
- Durable provenance comes from `GroundingAdmission.enterprise_provenance` and retrieved source snapshots. It is never inferred by matching natural-language text after generation.

## Persistence model

`SolutionDraftRecord` stores the explicit Opportunity and Requirement Analysis, a per-Opportunity monotonically increasing version, stable JSON draft payload, safe generation metadata, review status, independent stale metadata, creator, and creation time. Content identity fields are immutable after insertion. Phase 5.6a creates records only in `DRAFT` status and exposes no update or delete API.

`SolutionDraftProvenance` maps each cited statement path and citation label to the exact approved `EnterpriseGroundingFact` and immutable source document/chunk/run/hash/excerpt snapshot. It deliberately has no ForeignKey to `KnowledgeChunk`, because reindexing replaces chunks. Fact and document references use `PROTECT`.

## Version allocation and failure atomicity

The persistence transaction locks the Opportunity row before calculating `MAX(version) + 1`. A database uniqueness constraint on `(opportunity, version)` is the final invariant. The generation phase runs before this transaction. Any blocked or failed generation, invalid admission, insert-time provenance change, or persistence exception creates neither a record nor provenance rows.

## Stale semantics

Staleness is independent from review status and uses machine-readable reasons:

- `NEWER_REQUIREMENT_ANALYSIS`
- `GROUNDING_FACT_INVALID`
- `GROUNDING_PROVENANCE_INVALID`

A newer persisted analysis makes a draft stale, including a draft deliberately generated from older history. A cited Fact that becomes stale/non-approved/non-confirmed, or whose document/run/chunk/hash snapshot no longer validates, makes the draft stale. Staleness is decided by deterministic services; no LLM participates.

## API and authorization

- `POST /api/opportunities/{opportunity_id}/solution-drafts/` with explicit `analysis_id`
- `GET /api/opportunities/{opportunity_id}/solution-drafts/`
- `GET /api/solution-drafts/{solution_id}/`

Business Admin, the Opportunity's Sales owner, and assigned Presales owner may generate and view. Django staff/superuser flags do not bypass business visibility. List responses omit the full payload/provenance; detail includes both.

## Safety invariants

Deterministic enterprise admission, proposal-only veto verification, bounded verifier concurrency, approval/currentness checks, fail-closed behavior, and return-time admission revalidation remain unchanged. Persisting a result adds another deterministic revalidation boundary and never grants business admission.
