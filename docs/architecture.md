# SalesMind AI Architecture

This document records current repository truth, not a future-state promise. It was prepared against repository HEAD `3a3624714d1b84f576a8507a86ce4f14ee25566d`; the implemented Phase 5.5j-B code baseline is `b0ff01064ff9d52da844acd527d80442a151611a`. The last recorded full-suite result for that code baseline is 1,184 passed tests. These are checkpoint values, not permanent constants.

The root `README.md` is still a Phase Two delivery document. Its AI/RAG out-of-scope section describes that historical checkpoint and does not describe the current repository.

## Product scope

SalesMind AI supports enterprise sales and presales work: customer and opportunity management, structured requirement analysis, an internal enterprise knowledge base, grounded RAG answers, and generation of provenance-controlled internal solution drafts.

The repository is a modular Django monolith. The current backend is implemented; the Vue frontend, LangGraph orchestration, solution persistence/review lifecycle, and deployment packaging are not yet complete.

## Main actors

- **Business Admin** manages shared business data and knowledge, and participates in grounding-fact review through the existing Django Admin boundary.
- **Sales** owns opportunities, captures requirements, and coordinates presales work.
- **Presales** sees assigned opportunities and uses requirement, knowledge, and solution assistance.
- **Technical Django administrators** use `is_staff`/`is_superuser` for framework administration. Those flags are not business roles.

## High-level architecture

```text
Vue 3 frontend (planned; not yet complete)
                    ↓
Django 5.2 + Django REST Framework + JWT
                    ↓
PostgreSQL + pgvector
                    ↓
Accounts / Sales / Knowledge / RAG / Solution services
                    ↓
DeepSeek proposal generation
                    ↓
Qwen semantic verifier in the current production-like configuration
```

Provider names are environment-driven. No credentials belong in repository documentation.

## Django applications and modules

- `apps/accounts/`: custom `User`, fixed business roles, Django Admin integration, JWT login/refresh/current-user APIs, and presales option lookup.
- `apps/sales/`: `Customer`, `Opportunity`, append-only `OpportunityRequirementAnalysis`, role-scoped APIs, requirement analysis, retrieval planning, deterministic solution admission, proposal generation orchestration, semantic verification, and deterministic draft assembly.
- `apps/knowledge/`: document upload/validation, parsing, chunking, embeddings, PostgreSQL vector search, safe reindexing, `EnterpriseGroundingFact`, extraction proposals, approval/rejection, and stale lifecycle.
- `apps/rag/`: grounded question answering over retrieved knowledge evidence.
- `apps/llm/`: provider contracts and factories for DeepSeek generation and an optional independent OpenAI-compatible verifier.
- `config/`: environment-specific Django settings, PostgreSQL, DRF, JWT, model-provider settings, and root routing.

## Authentication and authorization

DRF uses database-backed Simple JWT authentication and defaults to authenticated access. The database user is loaded on each request, so deactivation and role changes take effect without waiting for token expiry.

Business authorization uses `User.role` (`admin`, `sales`, or `presales`). Django's `is_staff` and `is_superuser` remain technical framework privileges and do not bypass business-role checks. Grounding-fact review through Django Admin requires both technical Admin access and the business `admin` role.

See [`business-rules.md`](business-rules.md) for the stable authorization and visibility rules.

## Customer and Opportunity domain

`Customer` is shared master data with an audit-only `created_by`; it is not owned by an individual Sales user. `Opportunity` belongs to one customer and records `sales_owner`, optional `presales_owner`, audit `created_by`, the raw requirement, commercial fields, stage, and status. Protected foreign keys preserve ownership and audit history.

Opportunity visibility is deterministic: business Admin sees all, Sales sees owned opportunities, and Presales sees assigned opportunities. Requirement-analysis history inherits the same opportunity visibility boundary.

## Knowledge and RAG architecture

Knowledge documents are validated, parsed, split into traceable chunks, embedded, and stored in PostgreSQL using `pgvector.django.VectorField`. Migration `knowledge.0001_enable_vector` enables pgvector; the knowledge models and grounding provenance are defined by later migrations.

Vector search embeds the query and performs PostgreSQL/pgvector cosine ranking. The grounded RAG service passes only retrieved evidence to the LLM and normalizes citations. Knowledge text is always treated as untrusted data.

Successful reindexing replaces chunks, advances the document index-run identity, and marks older grounding facts stale while retaining their document, chunk-id snapshot, excerpt, content hash, and index-run provenance.

## Requirement Analysis

The requirement-analysis service produces ten fixed typed dimensions with one of `known`, `unknown`, `unclear`, or `conflict`. Analysis is based on a frozen snapshot of the Opportunity and Customer input. Persisted `OpportunityRequirementAnalysis` records are append-only and retain the source requirement/context, provider/model, contract version, conflicts, and clarifying questions.

## Solution Generation

The solution service consumes an explicit persisted requirement-analysis record. It applies deterministic readiness rules, performs requirement-derived knowledge retrieval, builds deterministic admission from current approved grounding facts, and asks the generation LLM only for atomic `proposal` claims.

Program code owns customer facts, enterprise facts, unresolved items, source eligibility, fixed section ordering, title, summary, assumptions, and final assembly. A solution draft is currently returned as a domain result; there is no persisted Solution model or review lifecycle yet. That work belongs to the next phase.

## Grounding and Verification architecture

`EnterpriseGroundingFact` separates evidence extraction from business admission:

```text
knowledge evidence → LLM fact proposal → PROPOSED
                                      ↓
                          approved human disposition
                                      ↓
                    deterministic admission eligibility
```

Only active, non-stale, manually approved facts with current, valid provenance can create an `enterprise_fact`. Confirmed positive and explicit-negative facts are admissible; unconfirmed, conflict, missing, proposed, rejected, stale, or provenance-invalid facts are not.

The semantic verifier receives only LLM-generated proposals. Each proposal is sent in an independent request, with per-draft bounded concurrency (`VERIFIER_MAX_CONCURRENCY`, default `2`). A proposal survives only with `SUPPORTED + ATOMIC`. Verifier output can veto a proposal or fail the draft, but it cannot create enterprise admission. The service rebuilds deterministic admission after external model calls to protect against reindex/approval TOCTOU changes.

See [`ai-pipeline.md`](ai-pipeline.md) for the complete flow and [`technical-debt.md`](technical-debt.md#td-001--semantic-verifier-synchronous-latency) for accepted verifier-latency debt.

## External model providers

- Embeddings use the OpenAI-compatible embedding integration; the configured/default model is `BAAI/bge-m3` with 1,024 dimensions.
- Generation uses the dedicated DeepSeek provider; the configured/default model is `deepseek-v4-flash`.
- Semantic verification can use a separately configured OpenAI-compatible provider. The current production-like checkpoint uses Qwen `qwen3.8-max-0902`, a 60-second timeout, no SDK retry, and thinking disabled.

If independent verifier settings are absent, the solution service retains the historical same-provider fallback. Provider failures are not repaired, retried, or rewritten by solution orchestration.

## Persistence

PostgreSQL is the only supported application database. It persists users, customers, opportunities, append-only requirement-analysis history, knowledge documents/chunks, vector embeddings, and grounding facts with approval and provenance metadata.

Solution drafts themselves are not persisted in the current phase. There is no solution review lifecycle, LangGraph state, Redis, Celery, or message queue in the implemented architecture.

## Current status and intentionally deferred components

| Area | Status |
| --- | --- |
| Phase 1 | Complete |
| Phase 2 | Complete |
| Phase 3 | Complete |
| Phase 3.5 | Complete |
| Phase 4 | Complete |
| Phase 5.1–5.4 | Complete |
| Phase 5.5 (through 5.5j-B) | Complete |
| Phase 5.6 | Next |
| LangGraph workflow | Planned, not implemented |
| Vue frontend | Planned, not complete |
| End-to-end deployment | Planned |

The next phase must not be inferred from this status table as authorization to implement it.

## Primary implementation references

- `config/settings/base.py`
- `apps/accounts/models.py`
- `apps/sales/models.py`
- `apps/knowledge/models.py`
- `apps/knowledge/services/indexing.py`
- `apps/knowledge/services/grounding_facts.py`
- `apps/knowledge/services/grounding_fact_approval.py`
- `apps/sales/services/requirement_analysis.py`
- `apps/sales/services/solution_admission.py`
- `apps/sales/services/solution_draft.py`
- `apps/sales/services/solution_grounding.py`
- `apps/sales/services/solution_schema.py`
