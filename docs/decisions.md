# SalesMind AI Decision Log

This is a compact ADR-style log of decisions already represented by current code, tests, migrations, or approved design. It is not a backlog.

Historical contexts, model names and measurements below retain their original
meaning. For the frozen `1141281` V2 behavior, including Semantic IR, bounded
pass regeneration and placement-aware admissibility, use
[architecture](architecture.md) and [AI pipeline](ai-pipeline.md). The historical
`SUPPORTED` verdict vocabulary must not be substituted for current V2
`ADMISSIBLE`, and the former no-regeneration path is not the current pass contract.

## D-001 — Django and DRF application framework

**Decision.** Build SalesMind AI as a modular Django monolith with Django REST Framework APIs.

**Context.** Identity, business data, authorization, audit history, knowledge persistence, and AI orchestration share one transactional application boundary.

**Why.** Django supplies mature ORM, migrations, Admin, authentication integration, and a coherent testable service boundary; DRF provides explicit authenticated APIs.

**Alternatives rejected.** A microservice split or a different application framework was not introduced before a demonstrated operational need.

**Consequences.** Apps remain modular (`accounts`, `sales`, `knowledge`, `rag`) but deploy through one Django project and one primary database.

## D-002 — PostgreSQL and pgvector, not a separate vector database

**Decision.** Use PostgreSQL as the only application database and pgvector for vector storage/search.

**Context.** Knowledge chunks, source metadata, embeddings, business records, and provenance must remain auditable together.

**Why.** PostgreSQL provides transactional persistence and relational integrity while pgvector supplies cosine search without another stateful service.

**Alternatives rejected.** A separate vector database and SQLite fallback were not introduced.

**Consequences.** Development and tests require PostgreSQL with the vector extension; vector dimensionality and indexing migrations are explicit repository contracts.

## D-003 — Business role is separate from Django staff/superuser flags

**Decision.** Authorize business behavior with `User.role`, independently of `is_staff` and `is_superuser`.

**Context.** Django Admin access and business Admin/Sales/Presales authority solve different problems.

**Why.** Conflating them would let technical privileges bypass business visibility and ownership rules.

**Alternatives rejected.** Automatic role-to-staff mapping and superuser bypass of business APIs.

**Consequences.** Technical flags manage framework administration only. Fact approval through Django Admin requires both staff access and business Admin role.

## D-004 — Deterministic enterprise admission

**Decision.** Program code, not an LLM, decides whether enterprise evidence can create an `enterprise_fact`.

**Context.** Earlier type-aware semantic judgments mixed entailment with business admissibility and produced unstable safety outcomes.

**Why.** Approval, currentness, status, provenance, and conflict policy are discrete rules that can be enforced and tested deterministically.

**Alternatives rejected.** Full-document verifier admission, type-fit prompting, and capability-specific prompt patches.

**Consequences.** Only current approved confirmed facts can be admitted; missing/unconfirmed/conflicting facts default to unresolved regardless of verifier output.

## D-005 — Human approval boundary for grounding facts

**Decision.** Fact extraction creates `PROPOSED` records only; an authorized human approves or rejects them.

**Context.** Extraction is probabilistic and may miss, merge, or misclassify business capabilities.

**Why.** Probabilistic components may propose but cannot dispose enterprise truth.

**Alternatives rejected.** Auto-approval from model confidence and probabilistic subject merging that inherits approved status.

**Consequences.** Approval is audited with reviewer and timestamp. Proposed, rejected, or stale facts cannot authorize claims or proposals.

## D-006 — Semantic verifier is defense in depth and veto-only

**Decision.** The semantic verifier may reject generated content but may never create business admission.

**Context.** Natural-language entailment remains valuable for generated proposals, while enterprise authority is already decided deterministically.

**Why.** Separating semantic support from business admissibility prevents a verifier false positive from manufacturing an enterprise capability.

**Alternatives rejected.** Letting `SUPPORTED` override missing approval, stale state, conflict, or provenance.

**Consequences.** Verifier defects are contained unless they allow an unsupported proposal within already admitted context; all fact claims remain program-owned.

## D-007 — Deterministic claims bypass semantic verification

**Decision.** `customer_fact`, `enterprise_fact`, and `unresolved` claims do not enter the semantic verifier.

**Context.** Phase 5.5j-A confirmed those claims are constructed by deterministic admission/schema logic rather than generated freely by the LLM.

**Why.** Re-verifying deterministic claims added latency and model variability without adding a real admission boundary.

**Alternatives rejected.** Sending the whole draft or all atomic claims to the verifier.

**Consequences.** The verifier input is proposal-only. Deterministic claims still undergo typed construction, provenance checks, and return-time revalidation.

## D-008 — One proposal per verifier request

**Decision.** Build one independent verifier packet and provider request for each proposal.

**Context.** A two-proposal Qwen request exceeded the 60-second boundary while isolated requests completed.

**Why.** Independent packets preserve claim scoping and avoid combined-request timeout behavior.

**Alternatives rejected.** Returning to a multi-proposal batch or increasing timeout/retry to mask latency.

**Consequences.** Request count scales with proposal count; any individual failure rejects the whole draft. See [TD-001](technical-debt.md#td-001--semantic-verifier-synchronous-latency).

## D-009 — Bounded per-draft verifier concurrency, default two

**Decision.** Verify independent proposal requests concurrently within one draft, bounded by `VERIFIER_MAX_CONCURRENCY` with default `2`.

**Context.** Serial isolated verification would add each external latency to user-visible wall time.

**Why.** A small configurable bound reduces wall time while keeping resource use explicit and result ordering deterministic.

**Alternatives rejected.** Unbounded threads, distributed queues, global cross-process semaphores, Redis, and Celery at this phase.

**Consequences.** Concurrency is local to one synchronous draft request. Provider latency remains accepted technical debt.

## D-010 — Fail-closed Solution Draft generation

**Decision.** Invalid structure, invalid citations, provider/verifier failures, unsupported or compound proposals, and provenance changes reject the whole draft.

**Context.** Returning a plausible but partially verified solution would hide uncertainty and weaken presales safety.

**Why.** Safety and auditability take precedence over partial availability.

**Alternatives rejected.** Retry-until-pass, model rewrite/self-correction, second retrieval, dropping failed proposals, and partial draft leakage.

**Consequences.** The service may return no draft on external failure; errors remain stable and do not expose raw provider content.

## D-011 — Return-time provenance revalidation for TOCTOU protection

**Decision.** Rebuild deterministic admission after external generation/verification and require it to equal the pre-call admission.

**Context.** Approved facts can become stale or otherwise invalid while an external model request is in flight.

**Why.** Pre-call validation alone cannot protect the return boundary from concurrent reindex or approval changes.

**Alternatives rejected.** Long database transactions across model calls, database locks held during network waits, and trusting the original snapshot without revalidation.

**Consequences.** Model calls remain outside long transactions; any admission change causes fail-closed return even if the verifier says `SUPPORTED`.

## D-012 — Version-scoped technical review with conditional independence

**Decision.** Technical approval belongs to a specific Solution version. The Presales Owner may approve a version initiated by AI, Sales, or another author, but a Presales Owner who creates or technically revises a version must not approve that same version. Another existing `presales` user acts as Solution Reviewer when independent review is required; business `admin` remains the fallback authority.

**Context.** Customer and Opportunity ownership are long-lived, while authorship, reviewer assignment, and approval apply to one immutable Solution version. `SolutionDraftRecord.created_by` records the version author, and `SolutionReview` records each reviewer assignment and decision.

**Why.** Conditional separation of author and approver gives self-authored technical changes an independent check without imposing mandatory second review on every AI- or Sales-initiated solution.

**Alternatives rejected.** A permanent `Opportunity.solution_reviewer`, mandatory two-stage review for every version, allowing Presales to approve their own technical revision, introducing a new reviewer business role, and using Django staff/superuser flags as business approval authority.

**Consequences.** Reviewer assignment and append-only review history are associated with `SolutionDraftRecord`, not Opportunity. Existing `presales` users fill the reviewer responsibility. Self-review is prohibited even for business Admin authors. Approval means internal technical approval for external solution communication; it does not mean customer signature, Opportunity success, or permanent freshness.

## D-013 — Customer-information and technical-revision returns are distinct

**Decision.** Review returns use separate machine-readable reasons: `CUSTOMER_INFO_REQUIRED` and `TECHNICAL_REVISION_REQUIRED`.

**Context.** A solution can be unready because customer facts are missing or because an otherwise informed technical design needs revision. Those causes have different owners and remediation paths.

**Why.** Sales owns customer clarification, while Presales owns technical design. A single undifferentiated revision state would obscure responsibility and weaken auditability.

**Alternatives rejected.** One generic return reason, asking Sales to perform technical design, or mutating a persisted Requirement Analysis or Solution version in place.

**Consequences.** `CUSTOMER_INFO_REQUIRED` leads Sales to collect facts, create an updated immutable Requirement Analysis, stale the older Solution, and generate a new version. `TECHNICAL_REVISION_REQUIRED` leads Presales to create a revised Solution version. `NEEDS_REVISION` is the current lifecycle projection, while the durable review record preserves the exact return reason.

## D-014 — Immutable versioned Solution persistence with durable provenance

**Decision.** Persist each successful Solution as a new immutable `SolutionDraftRecord` version linked to one explicit Opportunity and one explicit `OpportunityRequirementAnalysis`, with citation history stored in `SolutionDraftProvenance` snapshots.

**Context.** The in-memory `SolutionDraft` domain result was insufficient for history, review, or audit after knowledge reindexing. Requirement analyses and knowledge chunks have independent lifecycles, so persistence must retain exact generation inputs without copying the full analysis or depending on replaceable chunk rows.

**Why.** Per-Opportunity versions preserve history; the explicit analysis foreign key prevents silent latest-snapshot substitution; durable Fact/document and chunk/index/hash/excerpt snapshots preserve evidence auditability after reindexing.

**Alternatives rejected.** Mutating one Solution row in place, copying Requirement Analysis JSON into every Solution, defaulting to the latest analysis, foreign-keying provenance to replaceable `KnowledgeChunk`, and writing ORM records inside external model calls.

**Consequences.** `generate_grounded_solution_draft` remains read-only. `generate_and_persist_solution_draft` invokes it outside a transaction, then performs final provenance validation, Opportunity locking, version allocation, and atomic record/provenance insertion in a short transaction. Migration `sales.0003_solution_draft_persistence` is applied in the real `salesmind` database.

## D-015 — Transactional review state projection with immutable version history

**Decision.** Keep `SolutionDraftRecord.review_status` as the current state projection and preserve every version-scoped review attempt as a separate `SolutionReview`. Keep stale state independent from review state.

**Context.** Submit, approve, and return are concurrent business actions, while historical approvals must remain auditable even if requirements or grounding provenance later change.

**Why.** A transactional projection makes current API state efficient, while protected, immutable review records preserve who submitted, who reviewed, the decision, reason, comment, and timestamps. Separating stale and review axes distinguishes historical approval from current factual fitness.

**Alternatives rejected.** Directly patching review status, overwriting one mutable review row, deleting review history, coupling stale to `NEEDS_REVISION`, allowing self-review, and using Django staff/superuser flags as review authority.

**Consequences.** The implemented service state machine is `DRAFT → PENDING_REVIEW → APPROVED` or `NEEDS_REVISION`. It uses short transactions, row locks, one-active-pending-review enforcement, action-specific permissions, self-review prohibition, and approval-time stale revalidation. Migration `sales.0004_solutionreview` is applied in the real `salesmind` database.

## D-016 — Durable LangGraph orchestration over authoritative Django services

**Decision.** Use LangGraph only to route the bounded Solution workflow from an explicit analysis through generation/persistence, review submission, durable human interrupt, and approve-or-return resume. Keep Django services and PostgreSQL business tables authoritative. Use the official PostgreSQL checkpointer, and make generation replay durable through a nullable unique UUID idempotency key protected by a PostgreSQL session advisory lock.

**Context.** Human review must survive process reconstruction, while crashes can occur after a business transaction commits but before a graph checkpoint is written. A graph-only Solution ID cannot prevent duplicate provider calls or versions in that window, and checkpoint state must not be allowed to override a committed review decision.

**Why.** Stable database identities let the graph reconstruct current facts on every node. Durable generation idempotency closes the generation/checkpoint crash window without holding a transaction across external model calls. Replay recovery closes the decision/checkpoint window while preserving immutable review history.

**Alternatives rejected.** Reimplementing permissions or review transitions in graph nodes, storing full ORM objects or business payloads in checkpoints, using `MemorySaver` for production, holding database transactions across provider calls, relying only on `state.solution_draft_id`, and automatically looping returned reviews into analysis or regeneration.

**Consequences.** The graph has five thin nodes and terminal/handoff outcomes for `CUSTOMER_INFO_REQUIRED` and `TECHNICAL_REVISION_REQUIRED`. Same-key generation replay returns the existing Solution version; matching committed decisions recover; conflicting replay fails closed. Migration `sales.0005_solutiondraftrecord_generation_idempotency` and the official PostgresSaver schema are applied in the real `salesmind` database. Redis, Celery, multi-agent orchestration, and automatic revision loops remain outside Phase 6a.
