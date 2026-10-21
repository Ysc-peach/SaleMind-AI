# Citation input boundary repair

The approved scope is to clarify authorized citation inputs, stop V2 generation
when retrieved evidence authorizes no proposal citations, and preserve safe
formal-parser rejection metadata. No provider calls or commits are part of this
change. Existing worktree changes and protected paths remain untouched.

## Design

- The current admission service remains the sole authority for allowed IDs.
- For V2, an empty admission allowlist fails before generation or verification.
  A data-free error code reaches the workflow and a fixed actionable UI message.
  Legacy V1 behavior remains unchanged.
- All three Semantic IR requests carry the exact allowlist. Canonical examples
  use a real allowed ID, without renumbering sources or modifying model output.
  An example illustrates syntax, not support for its example recommendation.
- Citation logs forward only already-sanitized subtype/allowed/offending IDs
  from the actual parser rejection. No payload, raw exception, or new validator.
- Existing parser strictness, two-attempt maximum, guards, Qwen, approval and
  return-time/persistence provenance checks remain unchanged.

## Implementation and verification

1. Add failing tests in `test_solution_generation_failure_logging.py` for safe
   citation metadata; minimally extend the existing logger in `solution_draft.py`.
2. Add request-boundary tests in `test_solution_semantic_ir_v2.py` for sparse
   allowlists across all passes and examples accepted by the formal parsers.
   Update only prompt input/example construction in `solution_prompt_v2.py`.
3. Add early-stop/service and real-workflow tests for zero admitted citations,
   zero provider calls and zero Solution/Provenance rows. Add a fixed frontend
   message test. Introduce a data-free drafting error and specific workflow
  mapping, leaving persistence implementation unchanged.
   A failed idempotent HTTP replay must retain its safe message and request key,
   rather than navigate to a null Solution ID. No automatic resubmission.
4. Run focused tests, frontend tests/type-check, full pytest, Django check,
   migration consistency and diff checks. Review the scoped patch; stop without
   live model calls, PostgreSQL maintenance, or a commit.
