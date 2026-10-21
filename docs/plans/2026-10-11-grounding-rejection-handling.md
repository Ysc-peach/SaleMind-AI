# Grounding rejection transport and safe diagnostics

Scope approved by the user's continuation of the diagnosed failure.

1. Add offline regressions for typed grounding failures in the real workflow/API:
   HTTP 422, terminal failed checkpoint, no Solution/Provenance/review rows,
   idempotent replay without generation, no exception causes exposed.
2. Catch only the existing `SolutionDraftGroundingError` and preserve its fixed
   code. Keep failed generation fail-closed, without new retries or repair.
3. Log existing deterministic rejection branches and parsed Qwen hard vetoes:
   index, documented placement enums, rule code, requirement field enums,
   citation count, decision/atomicity. Omit text, container keys, citations,
   source content, provider response and credentials. No inferred verdict reason.
4. Distinguish these failures and HTTP 500 from uncertain network errors in UI.
5. Run focused red/green tests, full backend/frontend suites, type check,
   Django check, migration check and diff check. Review current changes only.
6. Reload the project backend after verification, without touching PostgreSQL.

No real provider calls, production data edits, benchmark reruns, commits,
generation/guard/verifier semantics changes, budgets, schemas or retry changes.
Existing failed requests cannot retrospectively acquire missing diagnostics.
