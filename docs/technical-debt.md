# Technical Debt Register

## Live status ledger (2026-11-12)

`docs/code-review-2026-10-21.md` is a dated snapshot, not a live register.
Several findings in it have since been fixed, and one was re-checked and found
to be a deliberate boundary. When this table and that report disagree, the
current source code and tests are authoritative.

| ID | Issue | Status | Evidence |
| --- | --- | --- | --- |
| P1-1 | Empty `requirement linkage` disables the unresolved guard | **FIXED** | Semantic IR already used `MANAGED_LINKAGE_PLACEMENTS`; the legacy Atomic parser was the last gap. `solution_prompt_v2.py` now requires a non-empty link for the eight managed placements, and the prompt says so. 17 new tests, mutation-verified. |
| P1-2 | No global rate limiting | **FIXED** | `config/settings/base.py` declares the throttle classes and nine scoped rates; `production.py` refuses to start without them. |
| P2-1 | Optional idempotency key allows duplicate generation | **FIXED** | `solution_workflow_views.py` rejects a missing or blank `Idempotency-Key` instead of generating a server-side `uuid4()`. Three regression tests. The model field stays nullable for historical rows. |
| P2-2 | Advisory lock has no timeout | **FIXED** | `solution_persistence.py` sets `lock_timeout = '5s'`, fails closed with `SolutionPersistenceError` on timeout, and resets the session setting. Two regression tests, mutation-verified. |
| P2-3 | Non-atomic provenance revalidation could persist a false stale verdict | **FIXED** | `refresh_solution_draft_staleness` locks draft, provenance, document and fact rows in document-then-fact order inside one transaction. |
| P2-4 | No explicit request-body limit on upload | **FIXED** | `enforce_body_limit` rejects `Content-Length` beyond the business limit plus multipart overhead with 413 before parsing, so an oversized body is never spooled to disk. |
| P2-5 | Every export error reported as 503 | **FIXED** | Render and payload defects now return 422 `solution_export_invalid_payload`; only snapshot/load failures still return 503. Tests assert the renderer message never reaches the response. |
| P2-6 | Export object URL revoked too early | **FIXED** | `frontend/src/utils/download.ts` delays `revokeObjectURL`. |
| P2-7 | Refresh-token race logs out a new session | **NOT APPLICABLE** | `ROTATE_REFRESH_TOKENS = False` and the refresh endpoint has its own throttle scope; there is no rotation race in the current configuration. |
| P2-8 | JWT tokens cannot be revoked | **FIXED** | `rest_framework_simplejwt.token_blacklist` is installed and `POST /api/auth/logout/` blacklists the refresh token; the frontend calls it on every logout. A revoked token can no longer mint access tokens. Access tokens still live at most 15 minutes (SimpleJWT design), which is the documented residual window. |
| P2-9 | No document-level visibility in the knowledge base | **BOUNDED / BY DESIGN** | For an intranet, single-company deployment the knowledge base is meant to hold the company's own capability material, so all business roles may read it. Uploading customer-confidential documents is out of scope for this deployment; if that changes, document-level visibility becomes mandatory before any such upload. |
| P2-10 | Knowledge API and Admin use different permission gates | **REVIEWED / BY DESIGN** | The API exposes list/create/retrieve/reindex only; no approval endpoint exists. `IsBusinessAdmin` checks the business role, and a dedicated test proves `is_staff`/`is_superuser` cannot bypass it. Requiring `is_staff` in the API would make business authority depend on a technical flag. |
| P3-1 | Initial indexing has no crash takeover | **FIXED** | `_start_indexing` now takes over a document stuck in `PROCESSING` past `KNOWLEDGE_INDEXING_STALE_TIMEOUT_SECONDS`; a fresh run still returns `indexing_already_in_progress`, and a late old run fails closed on the run-id check. The manual Admin reset remains. |
| P3-2 | Unique-constraint conflicts return 500 | **FIXED** | The global exception handler maps `IntegrityError` to a 409 `conflict` envelope without exposing the constraint name; the two service-level handlers remain. |
| P3-3 | Oversized single file | **PARTIAL** | Step one is done: 147 lines of static prompt contracts and examples moved from `solution_prompt_v2.py` (1,762 -> 1,624 lines) into `solution_prompt_v2_text.py` (155 lines), with the original names re-imported so callers are unchanged. All seven constants were compared character-for-character against `HEAD`, and 2,332 sales tests pass. Still open: pass-message builders in the same file, plus `solution_schema_v2.py` and `solution_grounding.py` (~1,000+ lines each). |
| P3-4 | Default verifier is not independent | **FIXED** | `production.py` refuses to start unless `VERIFIER_PROVIDER`, `VERIFIER_MODEL` and `VERIFIER_BASE_URL` are explicit and the verifier pair differs from the generation provider/model. `VERIFIER_API_KEY` is not required at startup so a fresh deployment can load knowledge before credentials are injected; generation still fails closed at the provider boundary. |
| P3-5 | Stale historical review reports | **ADDRESSED HERE** | `docs/code-review-2026-08-29.md` remains protected and unmodified; this ledger supersedes the 2026-10-21 snapshot. |
| P3-6 | Uncommitted workspace changes | **FIXED** | Every fix has its own commit; the working tree contains only the protected historical report. |

Additional changes in this cycle: object visibility now lives in
`apps/sales/services/visibility.py` (services no longer import from the API
layer), and `scripts/verify.sh` plus `.github/workflows/ci.yml` provide one
reproducible verification entrypoint.

Generation concurrency is bounded by `SOLUTION_GENERATION_MAX_CONCURRENT`
(default 2) through PostgreSQL advisory-lock slots: a fourth simultaneous
request receives 429 `workflow_capacity_reached` instead of occupying the last
worker.

Asynchronous generation is implemented behind `SOLUTION_GENERATION_ASYNC`
(default `false`). When enabled, `POST /solution-workflows/` writes a
`SolutionGenerationJob` and answers 202 with the queue state; `GET` reports
`QUEUED`/`RUNNING` until a draft exists, and `manage.py run_generation_worker`
(or the compose `worker` service) executes the run. The synchronous path is
unchanged and remains the default, so the switch is the rollback plan.

A job whose worker stopped heartbeating is now recovered on the worker's idle
tick: past `SOLUTION_GENERATION_JOB_STALE_SECONDS` (default 600) it returns to
the queue, and once `SOLUTION_GENERATION_JOB_MAX_ATTEMPTS` (default 2) is spent
it fails visibly as `workflow_worker_lost`. The lost attempt is not refunded, so
a repeatedly crashing job cannot loop forever.

Still open in this area: `heartbeat_at` is written on claim only, not refreshed
during a long run, so the stale window must stay above one generation (95-98s);
and the verifier cost per draft is unchanged.

Backup/restore is no longer unproven: a 2026-11-14 drill on the compose demo
database took a `pg_dump` plus a media archive, deliberately corrupted a row and
emptied the job table, then restored. Six snapshot values (table counts and two
content MD5s) all returned to their original values, and health, login and
business endpoints were 200 afterwards. The drill also exposed two deploy
defects that are now fixed: the media archive command was swallowed by the web
image ENTRYPOINT, and nginx cached the backend container IP so restarting `web`
produced 502 until nginx was restarted too.

Unattended operation now has two controls: the compose `backup` service takes a
database dump plus a media archive on an interval with retention pruning, and
`manage.py check_generation_health` reports queued/running counts, oldest wait
and recent failures as one JSON line with a non-zero exit code on threshold
breaches. Both were exercised against the running stack.

Still open: off-host replication remains a deployment task. `scripts/offsite-sync.ps1`
now provides the verified transfer (integrity gate, remote-target validation,
non-zero exit on failure), but the destination host and SSH key must be supplied
by the operator; without them every backup still sits on the database disk.
Alert delivery likewise depends on the operator's scheduler.

**Real provider acceptance completed on 2026-11-14.** The first run ended
`FAILED solution_draft_insufficient_approved_evidence`: the seeded demo
documents were indexed as `salesmind_demo_offline / deterministic-1024-v1`,
while the configured provider is `openai_compatible / BAAI/bge-m3`, so
`search_knowledge` filtered out every chunk. The guards stopped before any LLM
or verifier call, and no draft or provenance was written.

The full Admin knowledge workflow was then followed, without bypassing approval:
all three documents were reindexed with the real embedding provider (which
marked the 13 old facts stale by design), 13 new candidates were extracted with
the real LLM, and an authorised business admin approved the 9
`confirmed_supported` ones through `approve_grounding_facts`. The 4
`unconfirmed` candidates were left `proposed` rather than approved.

The second real generation then succeeded in 40 seconds: `202 QUEUED ->
RUNNING -> WAITING_FOR_SALES_CONFIRMATION`, producing V2 draft id 6 with 282
provenance rows, `is_stale=False` and `review_status=draft`; the queue job was
marked `succeeded` with `attempts=1`. This is one successful run on fixed demo
material with an independently configured verifier, not a quality or repeatability
claim for arbitrary customer documents (see `known-limitations.md` section 7).

## Reading this historical register at the frozen delivery baseline

At `1141281c07b2f5f92d51151fc9b2f0803814ef60`, Solution V2 uses three-pass
Semantic IR and the independent verifier display configuration is
`qwen3.8-flash`, with thinking explicitly disabled, timeout 60s, retries 0,
and per-draft concurrency 2. The measurements and Qwen Max model below are
the earlier Phase 5.5j-B record, not current Flash measurements.

Thinking propagation and bounded in-flight scheduling have since been fixed;
synchronous generation, per-claim request/token cost and unverified global
concurrency capacity remain limitations. The old latency diagnosis is not
reused as proof of today's bottleneck or as a production SLA. See
[current limitations](known-limitations.md), [current architecture](architecture.md),
and [versioned real benchmark results](real-provider-benchmark-summary.md).
Historical values below are preserved, not retrospectively recalculated.

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
