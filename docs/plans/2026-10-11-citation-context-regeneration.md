# Citation context and bounded contract regeneration

Approved scope: the user's continuation of the two-part adjustment proposal.
Work in the existing dirty workspace to preserve and verify the running project;
do not copy away or revert earlier user changes. No provider calls or commits.

## 1. Context projection (test first)

- Files: `apps/sales/services/solution_prompt_v2.py`,
  `apps/sales/tests/test_solution_generation_context_retry.py`.
- Separate unresolved and non-supported enterprise claims into a generation-only
  boundary block without citation IDs. Classify enterprise claims using existing
  admission decisions/provenance, not source label membership: one source can
  contain both positive and negative facts. Retain boundary text and types.
- Keep customer facts and supported facts, exact sparse allowlist and admitted
  evidence; do not mutate admission, stored claims or provenance.
- Test all three real message builders and same-source positive/negative facts.

## 2. Existing second attempt (test first)

- Files: `apps/sales/services/solution_draft.py`, same test file.
- After a formal contract rejection only, append one bounded user message to the
  original messages describing the parser's safe category/path/expected/actual.
  Redact unknown keys and malformed IDs; never include raw output or causes.
- Reuse the safe formal diagnostic projection for logs and feedback. Ask for a
  complete new valid response; prohibit automatic ID substitution or invented
  evidence. Leave first-call messages and original input untouched.
- Preserve exactly two maximum generation attempts, provider-error behavior,
  output limits and strict parsing of both attempts. Test actual Core,
  Implementation and Assurance parsers, provider failure and repeat rejection.

## 3. Verification

- Run the new tests RED before production edits, then GREEN with affected suites.
- Run full offline pytest, Django check, migration consistency and diff check.
- Review scoped additions independently; fix only confirmed scoped defects.
- After verification, reload only the verified project backend process and check
  HTTP availability; do not trigger generation.
- No model evaluation, data updates, database service changes, schema/budget/
  verifier/guard/persistence changes. Real success still requires a separately
  authorized real generation; these changes do not guarantee model compliance.
