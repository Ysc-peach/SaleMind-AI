# SalesMind AI

SalesMind AI is an enterprise presales and solution-assistance system built as a modular Django application.

## Source of truth

Use this order when facts disagree:

1. Current source code and migrations
2. Automated tests
3. `docs/architecture.md`
4. `docs/business-rules.md`
5. `docs/ai-pipeline.md`
6. `docs/decisions.md`
7. `docs/technical-debt.md`
8. Existing specs and implementation plans

Chat history is context only and never overrides the repository.

## Before substantial changes

For cross-file changes, refactors, debugging, call-chain analysis, impact analysis, or architecture work, use GitNexus `query`, `context`, `trace`, and `impact` when useful. GitNexus is navigation and analysis assistance; current source and tests remain final truth. Simple, local edits do not require GitNexus.

## Project safety rules

- Business `role` is independent from Django `is_staff` and `is_superuser`; technical flags never grant business Admin authority.
- LLMs must not grant enterprise business admission. Probabilistic components may propose; deterministic code or approved human action disposes.
- The semantic verifier remains veto-only.
- Never bypass grounding provenance, approval, current-index, or stale-state rules.
- Preserve return-time provenance revalidation.
- Do not modify, restart, repair, or replace PostgreSQL instances, configuration, ports, PID files, roles, templates, or extensions without explicit current-task authorization.
- Preserve the user's untracked `.workbuddy/` and `docs/code-review-2026-08-29.md`; do not add, modify, or delete them.

## Important session startup

Read this file and the relevant project-memory documents, inspect Git status, use GitNexus where it adds value, then verify assumptions against the actual code and tests before making substantial changes.
