# Known-requirement clarification diagnostics

Approved scope: diagnose the repeated `question_targets_known_requirement` rejection without changing admission or making real provider calls.

## Design

- Keep the existing four-field contract failure object and public error unchanged.
- Enhance only the `actual` description at the real `_parse_questions` rejection branch.
- Include the validated requirement enum, its `known` status, the question JSON shape, and string character count (or `unavailable`).
- Never include question text, requirement values/evidence, raw output, or unvalidated field names.
- Keep the existing validation order, one analysis generation per request, and zero saved snapshots on failure.
- The metadata cannot recover past discarded responses or distinguish semantic subquestions without a later separately authorized observation.

## Execution

1. Add real parser fixtures in `apps/sales/tests/test_requirement_analysis_diagnostics.py` covering all ten dimensions and non-string question shapes. Run them and observe the missing diagnostic detail.
2. Add an API regression in `apps/sales/tests/test_requirement_analysis_api.py` verifying the same safe detail reaches logs, not the API response, with no snapshot or customer/opportunity mutation.
3. Modify only the diagnostic description in `apps/sales/services/requirement_analysis.py::_parse_questions`; do not modify prompt, acceptance rules, retry, provider, or persistence.
4. Run focused tests, full pytest, Django check, migration consistency, and diff checks. Preserve unrelated changes and protected paths. Do not commit or call a real provider.
