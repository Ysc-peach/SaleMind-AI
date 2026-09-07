# SalesMind AI Decision Log

This is a compact ADR-style log of decisions already represented by current code, tests, migrations, or approved design. It is not a backlog.

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

**Context.** Customer and Opportunity ownership are long-lived, while authorship, reviewer assignment, and approval apply to one immutable Solution version. Phase 5.6a already stores version author provenance in `created_by` and a coarse `review_status`, but it has no reviewer relationship or review-history model.

**Why.** Conditional separation of author and approver gives self-authored technical changes an independent check without imposing mandatory second review on every AI- or Sales-initiated solution.

**Alternatives rejected.** A permanent `Opportunity.solution_reviewer`, mandatory two-stage review for every version, allowing Presales to approve their own technical revision, introducing a new reviewer business role, and using Django staff/superuser flags as business approval authority.

**Consequences.** Phase 5.6b should associate reviewer assignment and append-only review history with `SolutionDraftRecord`, not Opportunity. Existing `presales` users fill the reviewer responsibility. Approval means internal technical approval for external solution communication; it does not mean customer signature, Opportunity success, or permanent immutability.

## D-013 — Customer-information and technical-revision returns are distinct

**Decision.** Review returns use separate machine-readable reasons: `CUSTOMER_INFO_REQUIRED` and `TECHNICAL_REVISION_REQUIRED`.

**Context.** A solution can be unready because customer facts are missing or because an otherwise informed technical design needs revision. Those causes have different owners and remediation paths.

**Why.** Sales owns customer clarification, while Presales owns technical design. A single undifferentiated revision state would obscure responsibility and weaken auditability.

**Alternatives rejected.** One generic return reason, asking Sales to perform technical design, or mutating a persisted Requirement Analysis or Solution version in place.

**Consequences.** `CUSTOMER_INFO_REQUIRED` leads Sales to collect facts, create an updated immutable Requirement Analysis, stale the older Solution, and generate a new version. `TECHNICAL_REVISION_REQUIRED` leads Presales to create a revised Solution version. The existing coarse `NEEDS_REVISION` status may remain a lifecycle projection, while the durable review record preserves the exact return reason.
