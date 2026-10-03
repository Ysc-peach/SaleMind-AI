# Real-provider benchmark reporting

Evaluation is opt-in and in-memory. Pass `BenchmarkEvaluationReport` as
`evaluation_report` to `run_real_provider_benchmark_gate`. A successful result
contains `evaluation`; an unsuccessful run re-raises the original exception
with a safe `evaluation_report` snapshot. The supplied collector remains
readable after either outcome. No prompts, provider JSON or customer text are
stored by the collector. Existing public API error contracts are unchanged.

Report these dimensions separately:

| Dimension | What it establishes |
| --- | --- |
| `provider_availability` | Observed embedding, generation and verifier provider operations succeeded or failed. A valid HTTP response does not prove contract validity. |
| `generation_contract_validity` | Core, Implementation and Assurance formal parser results; provider attempts, parser attempts, admitted claim counts and rejected-attempt categories. |
| `deterministic_admission` | Grounding/proposal checks and return-time/transactional provenance revalidation. A later revalidation failure invalidates this dimension even after Qwen completed. |
| `qwen_admission` | Parsed admissibility/atomicity verdict counts and final admission. Provider failure is `BLOCKED_PROVIDER`, not an `INADMISSIBLE` verdict. |
| `persistence` | Committed Solution and provenance outcomes, observed after the transaction exits. No extra diagnostic database query is required. |
| `final_solution_quality` | Explicit scoring of the persisted artifact, including rubric version and hard-gate results; never inferred from persistence success. |

Assembly is also reported independently. `NOT_REACHED` is not a measured failure;
`NOT_EVALUATED` is not a zero quality score. A setup/index-compatibility error
does not, by itself, prove an embedding provider outage. These counters measure
observed provider operations, not hidden SDK network attempts.

For a fresh production persistence call, provenance status comes from the
committed entries. An idempotency replay without that observation reports
provenance as `null` (unknown), rather than guessing its presence. Previously
committed records are never treated as newly generated quality evidence.

After scoring the final artifact with the frozen evaluator, explicitly call
`report.set_quality(score=..., rubric_version=..., hard_gates=...)`, then use
`report.to_dict()` for the final report. This requires successful persistence;
all hard-gate results remain visible, including failures. The result's initial
`evaluation` snapshot intentionally does not change retrospectively.

The current rubric is documented in `docs/solution-quality-rubric.md`.
Historical scores retain their original version. Offline regression success
establishes engineering behavior, not live provider availability or a higher
cross-scenario E2E success rate.
