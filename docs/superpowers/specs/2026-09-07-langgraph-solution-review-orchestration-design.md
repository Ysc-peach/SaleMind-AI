# Phase 6a LangGraph Solution Review Orchestration Design

## Goal

Add durable orchestration for an existing persisted Requirement Analysis through Solution generation, review submission, human interruption, and one terminal approve-or-return decision. LangGraph routes the workflow; existing Django services remain the sole business authority.

## Boundaries

- The graph starts from an explicit persisted `analysis_id`; it never creates or substitutes Requirement Analysis.
- Nodes are thin wrappers around `generate_and_persist_solution_draft`, `submit_solution_draft_for_review`, `approve_solution_draft`, and `request_solution_draft_revision`.
- PostgreSQL business rows remain the source of truth. Graph checkpoints contain stable IDs and routing values only.
- The first graph ends after approval or either return reason. It does not regenerate, ask customers questions, notify users, or loop.
- Existing deterministic admission, provenance, stale, permission, self-review, verifier, versioning, and review-transition rules are not reimplemented.

## Durable generation idempotency

`SolutionDraftRecord` gains nullable immutable `generation_idempotency_key: UUID`. Non-null values are unique. Existing non-Graph calls continue to use `NULL`.

`generate_and_persist_solution_draft(..., idempotency_key=None)` uses a PostgreSQL session advisory lock derived deterministically from a non-null UUID. The lock is held without an open transaction while generation runs. After acquiring it, the service rechecks for an existing record:

- matching key and inputs: return the existing record without provider calls;
- matching key with different Opportunity, analysis, or creator: fail closed;
- absent key: generate and persist normally, storing the key.

The advisory lock closes the concurrent check/generate window without holding a database transaction across external model calls. The database uniqueness constraint is the final integrity boundary. Process termination releases the session lock.

## Graph state and outcomes

Graph state is a typed mapping containing only:

- `workflow_run_id`, `opportunity_id`, `requirement_analysis_id`, `requested_by_id`;
- optional `solution_draft_id`, `solution_version`, `solution_review_id`, `reviewer_id`;
- `workflow_stage`, `workflow_outcome`;
- optional `human_action`, `return_reason`, `comment`, and stable `error_code`.

It never stores ORM instances, Solution payload, analysis JSON, evidence, grounding provenance, provider responses, credentials, or cached permissions.

Finite outcomes are `GENERATED`, `WAITING_FOR_REVIEW`, `APPROVED`, `CUSTOMER_INFO_REQUIRED`, `TECHNICAL_REVISION_REQUIRED`, `BLOCKED`, `CONFLICT`, and `FAILED`.

## Graph

```text
START
  -> generate_solution
  -> submit_review
  -> wait_for_human (interrupt after PENDING review is committed)
  -> route_human_decision
       -> approve -> END
       -> request_revision -> END
```

The interrupt payload contains only Solution ID, Review ID, reviewer ID, and allowed actions. Resume input contains actor ID and action; revision also requires reason and comment.

## Decision replay

Before invoking a decision service, the wrapper reloads the persisted Solution and Review. An already committed identical terminal action is restored as success. An opposed action or non-identical returned decision becomes `CONFLICT` and never rewrites history. New decisions always go through the existing service.

## Checkpointing

Production compilation uses the official synchronous PostgreSQL `PostgresSaver` from `langgraph-checkpoint-postgres`; `MemorySaver` is not a production path. A dedicated `LANGGRAPH_CHECKPOINT_DATABASE_URL` supplies the connection without copying credentials into graph state or logs.

Checkpoint tables are orchestration infrastructure, not SalesMind business truth. Schema setup is explicit and is not performed during import or ordinary requests. Automated tests may create it in the test database. Real `salesmind` setup requires separate authorization.

## Failure behavior

Wrappers adapt existing typed service/provider errors into finite workflow outcomes and stable error codes. Unexpected errors propagate rather than being converted from arbitrary strings. No graph branch may bypass or duplicate service authorization. No partial draft or review decision is synthesized by the graph.

## Dependencies

Pin only `langgraph` and `langgraph-checkpoint-postgres`, retaining the existing psycopg driver with its official pool extra. Do not add the LangChain full stack, Redis, Celery, or another broker.

## Verification

TDD covers explicit analysis selection, generation idempotency and concurrency, minimal interrupt payload, PostgreSQL reconstruction/resume, service delegation, both return reasons, committed-decision replay, conflict handling, immutable Solution payload, and database-source-of-truth reloads. Final verification includes focused, Solution/review, Sales, Phase 5, full pytest, Django, migration, dependency, and diff checks.
