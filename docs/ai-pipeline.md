# SalesMind AI AI Pipeline

## Core principle

> Probabilistic components propose. Deterministic program logic or approved human action disposes.

Semantic entailment is not business admissibility. A model can judge whether supplied text entails a proposal, but it cannot decide whether an enterprise capability is approved, current, or allowed into a solution.

## Knowledge preparation lane

Knowledge preparation is separate from a Solution Draft request:

```text
KnowledgeDocument upload
        ↓
validation and parsing
        ↓
traceable chunking
        ↓
BAAI/bge-m3 embedding
        ↓
PostgreSQL + pgvector index
        ↓
document READY with completed index-run ID
        ↓
fact extraction LLM (outside the indexing transaction)
        ↓
EnterpriseGroundingFact PROPOSED
        ↓
authorized human approve/reject
        ↓
APPROVED facts become candidates for deterministic admission
```

The extraction LLM proposes `subject_key`, statement, status, and source mapping. It cannot approve. Persistence rechecks the document run and chunk snapshot in a short transaction before writing proposals.

Successful reindexing replaces chunks, marks old facts stale, and preserves the old fact's document reference, chunk-ID snapshot, excerpt, content hash, and index-run ID for audit. New extraction produces new `PROPOSED` facts; admission resumes only after explicit approval.

Primary references: `apps/knowledge/services/indexing.py`, `apps/knowledge/services/grounding_facts.py`, `apps/knowledge/services/grounding_fact_approval.py`, and `apps/knowledge/models.py`.

## Requirement Analysis lane

```text
Customer + Opportunity structured fields + raw requirement
        ↓
frozen RequirementAnalysisInput
        ↓
DeepSeek requirement analysis
        ↓
strict ten-dimension validation
        ↓
append-only OpportunityRequirementAnalysis snapshot
```

The analysis service classifies each dimension as `known`, `unknown`, `unclear`, or `conflict`. It analyzes requirements only; it does not retrieve enterprise knowledge or produce solutions.

## Grounded Solution Draft request path

The current production path is centered on `generate_grounded_solution_draft` in `apps/sales/services/solution_draft.py`:

```text
Opportunity raw requirement
        ↓
persisted Requirement Analysis
        ↓
frozen analysis snapshot loaded by ID
        ↓
deterministic readiness check
        ↓
requirement-derived retrieval intents
        ↓
BAAI/bge-m3 query embedding
        ↓
PostgreSQL + pgvector retrieval
        ↓
retrieved, labelled SolutionSource evidence
        ↓
EnterpriseGroundingFact currentness/provenance match
        ↓
deterministic admission
        ├── customer_fact
        ├── enterprise_fact
        └── unresolved
        ↓
allowed customer context + approved supported enterprise evidence
        ↓
DeepSeek proposal generation
        ↓
strict proposal-only Atomic IR parser
        ↓
one proposal per semantic-verifier request
        ↓
bounded per-draft concurrency (default 2)
        ↓
Qwen semantic verifier
        ↓
SUPPORTED + ATOMIC only
        ↓
return-time deterministic admission revalidation
        ↓
deterministic SolutionDraft assembly and return
```

Readiness-blocked and no-evidence paths return before generation and verification. Structurally invalid generated output never reaches the verifier. Zero generated proposals skip the verifier.

## Deterministic admission

`build_solution_admission` cross-checks retrieved source identities with database grounding facts. `_is_active_approved_fact` enforces approval, stale state, document readiness, current index run, and content-hash equality.

The admission result contains:

- deterministic claims;
- enterprise decisions by controlled subject;
- exact enterprise claim-to-Fact provenance;
- source labels that confirmed-supported enterprise evidence permits proposals to cite.

Opposed approved positive/negative facts resolve to `CONFLICT`; absence resolves to `UNCONFIRMED`. Neither creates an enterprise fact.

## Claim ownership

| Claim/output | Creator | Inputs and authority | LLM freedom |
| --- | --- | --- | --- |
| `customer_fact` | Deterministic admission | `known` frozen Requirement Analysis fields | None |
| `enterprise_fact` | Deterministic admission | Current, approved, provenance-valid confirmed Fact | None |
| `unresolved` | Deterministic admission/schema | Non-known customer dimensions; unconfirmed/conflicting enterprise subjects | None |
| `proposal` | DeepSeek generation | Known customer direction plus only approved supported enterprise evidence | Wording/recommendation within allowed support |
| Fixed sections/title/summary/assumptions | Deterministic schema assembly | Verified/admitted claims and analysis gaps | None |

The LLM output schema is deliberately small: `{"proposals": [{"section", "text", "citations"}]}`. It cannot output statement type, enterprise facts, customer facts, unresolved items, final section envelopes, approval decisions, or source metadata.

## Proposal-only semantic verification

`verify_atomic_solution_proposals` receives only generated `proposal` claims. It builds claim-scoped customer context and cited enterprise evidence, then sends every proposal in an independent verifier request. A thread pool bounds concurrent requests within one draft to `VERIFIER_MAX_CONCURRENCY` (default `2`) while preserving original proposal order in the result.

The Qwen verifier returns exactly one relation and atomicity result per request:

- relation: `SUPPORTED`, `INSUFFICIENT`, or `CONTRADICTED`;
- atomicity: `ATOMIC` or `COMPOUND`.

Only `SUPPORTED + ATOMIC` passes. The verifier performs semantic entailment, contradiction detection, proposal support checking, and atomicity checking. It does not decide Fact approval, stale/current state, provenance validity, conflict policy, unconfirmed policy, or enterprise admission.

Any provider error, timeout, malformed response, unsupported result, or compound result fails the whole draft. No partial verified draft is returned. See [TD-001](technical-debt.md#td-001--semantic-verifier-synchronous-latency) for the accepted synchronous-latency debt.

## Return-time provenance revalidation

External generation and verification calls happen after the first deterministic admission decision. Before assembly, `generate_grounded_solution_draft` calls `build_solution_admission` again and requires exact equality with the first result.

If reindexing, stale marking, approval changes, source content, or another provenance condition changes during model calls, the request fails closed. A verifier `SUPPORTED` result cannot override this TOCTOU boundary.

## Provider boundaries

- **Embedding:** OpenAI-compatible embedding provider, configured/default model `BAAI/bge-m3`, 1,024 dimensions.
- **Generation:** DeepSeek provider, configured/default model `deepseek-v4-flash`.
- **Verifier:** independently configurable OpenAI-compatible provider; current production-like checkpoint uses Qwen `qwen3.8-max-0902` with 60-second timeout, zero retries, thinking disabled, and per-draft max concurrency `2`.

Provider configuration is environment-driven. API keys, tokens, database credentials, and prompt payloads containing real business data must never be copied into project-memory documents.

## Security and reliability boundaries

- Requirement text, knowledge evidence, generated proposals, and verifier packets are untrusted data at model boundaries.
- Enterprise evidence given to generation and verification is constrained by deterministic admission and citations.
- Customer requirements never prove enterprise capability.
- Explicit-negative approved evidence may produce a negative enterprise fact but cannot authorize a positive capability proposal.
- The verifier is defense in depth and veto-only.
- No orchestration retry, rewrite, or second retrieval occurs.
- Draft persistence, review workflow, LangGraph orchestration, and frontend behavior are deferred.

## Main code and regression references

- `apps/sales/services/requirement_analysis.py`
- `apps/sales/services/requirement_analysis_history.py`
- `apps/sales/services/solution_readiness.py`
- `apps/sales/services/solution_retrieval.py`
- `apps/sales/services/solution_admission.py`
- `apps/sales/services/solution_prompt.py`
- `apps/sales/services/solution_schema.py`
- `apps/sales/services/solution_grounding.py`
- `apps/sales/services/solution_grounding_prompt.py`
- `apps/sales/services/solution_draft.py`
- `apps/sales/tests/test_solution_admission.py`
- `apps/sales/tests/test_solution_provenance_pipeline.py`
- `apps/sales/tests/test_solution_proposal_only_verification.py`
- `apps/sales/tests/test_solution_proposal_bounded_concurrency.py`
