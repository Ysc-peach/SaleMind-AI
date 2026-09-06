# Technical Debt Register

## TD-001 — Semantic Verifier synchronous latency

### Status

`ACCEPTED / DEFERRED`

This is performance and user-experience technical debt, not a known safety-correctness defect. The current functional, safety, and fail-closed contracts have passed; latency optimization is deferred until the main SalesMind product flow is complete.

### Current architecture

```text
DeepSeek V4 Flash
→ generate proposals

each proposal
→ independent Qwen3.8-max-0902 semantic verifier request

per-draft bounded concurrency
→ default max concurrency = 2

verifier
→ veto-only

deterministic admission
→ remains business admission authority
```

### Verified baseline

Phase 5.5j-B Case 1:

```yaml
proposals:              2
verifier requests:      2
configured concurrency: 2
observed concurrency:   2

generation latency:     1.396s

verifier A:             53.159s
verifier B:             18.854s
verifier wall-clock:    53.159s

total solution latency: 55.655s
```

Both verifier requests succeeded; neither reached the 60-second timeout.

Phase 5.5j-B Case 4:

```yaml
proposals:              0
verifier requests:      0
total solution latency: 2.188s
```

### Previous findings

The following progression is retained to avoid repeating the same experiments:

```text
Old full-claim verification:
11–15 claims
→ approximately 53s / approximately 60s timeout

Proposal-only verification:
Case 1, 2 claims in one request
→ approximately 61s timeout

Single-proposal isolation:
Proposal A
→ 28.141s success

Proposal B
→ 24.208s success

Final bounded-concurrency smoke:
Proposal A
→ 53.159s success

Proposal B
→ 18.854s success

verifier wall-clock
→ 53.159s
```

Reducing the claim count improved packet structure, but Qwen verifier latency for a single request remains high and variable. Current evidence places the primary bottleneck in the external semantic-verifier/model call, not in Django or Django REST Framework request processing.

### Why deferred

1. The safety architecture is complete.
2. Unsafe final accepts are zero.
3. Provenance violations are zero.
4. Deterministic admission violations are zero.
5. Verifier failures remain fail closed.
6. The full test suite passed with 1,184 tests.
7. Further latency work currently has lower value than completing the main SalesMind business flow, LangGraph workflow, Vue frontend, and deployment.

### Revisit timing

Revisit after:

- Phase 5.6 is complete.
- The LangGraph workflow is complete.
- The Vue frontend is complete.
- End-to-end deployment and demo are complete.

Reopen earlier if:

- Frontend integration demonstrates unacceptable user experience.
- Verifier timeout rate increases.
- Concurrent users create resource pressure.
- Provider or model changes materially.

### Future optimization candidates

These are candidates for evaluation, not commitments or guaranteed fixes:

1. Benchmark a faster verifier model or provider.
2. Compare Qwen Max with faster Qwen or DeepSeek verifier candidates.
3. Slim claim-scoped customer context and prompts, but only if support correctness can be preserved.
4. Move semantic verification out of the synchronous user-request path.
5. Introduce a background verification or review workflow.
6. Revisit asynchronous I/O and provider-calling strategy.
7. Add application-wide provider concurrency or rate limiting if real multi-user load requires it.
8. Re-evaluate whether every proposal class requires the same expensive verifier.

### Safety invariants future optimization must preserve

- Deterministic admission remains authoritative.
- The verifier remains veto-only.
- Enterprise facts require approved, current provenance.
- `UNCONFIRMED`, `CONFLICT`, and missing capabilities cannot become enterprise capabilities.
- Stale facts cannot be admitted.
- Verifier errors fail closed.
- Partial, unverified drafts cannot leak.
- Return-time provenance revalidation remains active.

### Evidence and code references

- Proposal-only verification and bounded per-draft concurrency: [`apps/sales/services/solution_grounding.py`](../apps/sales/services/solution_grounding.py#L146).
- Solution orchestration, proposal-only verifier invocation, and return-time admission revalidation: [`apps/sales/services/solution_draft.py`](../apps/sales/services/solution_draft.py#L49), especially the verifier boundary at line 102 and revalidation at line 111.
- Veto-only semantic and atomicity contract plus packet serialization: [`apps/sales/services/solution_grounding_prompt.py`](../apps/sales/services/solution_grounding_prompt.py#L14) and its message builder at line 60.
- Verifier timeout, retry, output-budget, and concurrency settings: [`config/settings/base.py`](../config/settings/base.py#L104).
- Phase 5.5j-A proposal-only, fail-closed, admission-authority, and return-time revalidation regressions: [`apps/sales/tests/test_solution_proposal_only_verification.py`](../apps/sales/tests/test_solution_proposal_only_verification.py#L159), with the failure boundary at line 234, admission invariant at line 262, and revalidation at line 297.
- Phase 5.5j-B isolated-request, bounded-concurrency, ordering, and whole-draft failure regressions: [`apps/sales/tests/test_solution_proposal_bounded_concurrency.py`](../apps/sales/tests/test_solution_proposal_bounded_concurrency.py#L119), with ordering at line 155 and fail-closed cases at lines 173 and 185.
