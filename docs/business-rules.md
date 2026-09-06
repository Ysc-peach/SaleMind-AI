# SalesMind AI Business Rules

These rules are stable business and safety invariants. Refactors may change implementation shape but must not silently change these outcomes.

## Roles and technical privileges

The fixed business roles are:

- `admin`
- `sales`
- `presales`

`User.role` is business data. It is independent from Django's `is_staff` and `is_superuser` flags:

- Business `admin` does not automatically receive Django Admin access.
- `is_staff` or `is_superuser` does not grant business Admin, Sales, or Presales authorization.
- Business APIs authorize using `User.role`; technical flags cannot bypass those checks.
- Grounding-fact review is deliberately stricter because it is exposed through Django Admin: the reviewer must be active, have `is_staff=True`, and have business role `admin`. A technical superuser with another business role cannot approve facts.

Primary references: `apps/accounts/models.py`, `apps/sales/api/permissions.py`, `apps/sales/api/opportunity_access.py`, `apps/knowledge/api/permissions.py`, and `apps/knowledge/services/grounding_fact_approval.py`.

## Customer rules

- Customer is shared company master data, not per-Sales-owned data.
- `created_by` is required audit provenance and is set by the server; it is not ordinary client-controlled data.
- Duplicate customer names are allowed. Collision discovery uses explicit search rather than uniqueness.
- Admin and Sales may create, search, and retrieve customers; Presales cannot use Customer APIs.
- Ordinary Customer list, update, and delete APIs are not exposed.
- Customer responses expose only safe shared fields and restricted active-opportunity summaries; raw requirements, budgets, owners, and audit fields are not leaked through those summaries.
- Customer, opportunity ownership, and audit relations use protected deletion where history must survive.

## Opportunity ownership and visibility

An Opportunity records `customer`, `sales_owner`, optional `presales_owner`, and `created_by` separately.

- Business Admin sees all opportunities.
- Sales sees opportunities where `sales_owner` is the current user.
- Presales sees opportunities where `presales_owner` is the current user.
- Unknown business roles see none, regardless of Django technical flags.
- Objects outside the role-filtered queryset are treated as not found.
- Sales creates opportunities and becomes both `sales_owner` and `created_by`.
- Only the owning Sales user can partially update an opportunity.
- Business Admin and Presales have read-only Opportunity access.
- Customer, `sales_owner`, and `created_by` cannot be reassigned through ordinary PATCH.
- Requirement-analysis creation/history uses the same opportunity visibility boundary.

## Requirement Analysis

Requirement Analysis has exactly ten dimensions:

1. `business_goal`
2. `use_scenario`
3. `user_scale`
4. `deployment_requirement`
5. `data_security_requirement`
6. `existing_environment`
7. `integration_requirement`
8. `timeline`
9. `budget`
10. `technical_constraints`

Every dimension is one of:

- `known`: value and evidence are present.
- `unknown`: no reliable information; value and evidence are absent.
- `unclear`: related information exists but is ambiguous.
- `conflict`: reliable inputs disagree; the system preserves the disagreement rather than choosing a side.

Known structured Opportunity/Customer facts outrank mere omission from narrative text. Customer requirements and environment facts must not be promoted into enterprise capabilities or validated deployment readiness. Persisted analyses are immutable historical snapshots; a later analysis creates a new record.

## Grounding Fact lifecycle

`EnterpriseGroundingFact` has two independent state dimensions.

Approval status:

- `PROPOSED`: produced for review; never admitted.
- `APPROVED`: explicitly disposed by an authorized human; still subject to status, currentness, and provenance checks.
- `REJECTED`: rejected proposal; never admitted.

Fact status:

- `CONFIRMED_SUPPORTED`: the cited enterprise evidence confirms a positive capability/fact.
- `CONFIRMED_UNSUPPORTED`: the cited enterprise evidence confirms an explicit negative capability/fact.
- `UNCONFIRMED`: evidence does not establish either support or lack of support.
- `CONFLICT`: current approved evidence conflicts and requires attention.

Currentness:

- A fact is current only while `is_stale=False` and its source document/index-run/content provenance still matches the retrieved source.
- Successful reindexing marks older facts stale. Their audit snapshots remain, but they immediately leave admission.
- Fact extraction may propose a status but always persists `PROPOSED`; it can never approve its own output.

## Enterprise admission invariants

An enterprise fact may participate in deterministic admission only when all of the following hold:

- `approval_status == APPROVED`
- `is_stale == False`
- the source document is `READY`
- the source document has a current completed index run
- the fact index-run ID matches the document's current run
- the fact content hash matches the retrieved source content
- its status is `CONFIRMED_SUPPORTED` or `CONFIRMED_UNSUPPORTED`

Deterministic outcomes:

| Fact state | Admission outcome |
| --- | --- |
| Approved, current, valid `CONFIRMED_SUPPORTED` | Positive `enterprise_fact` allowed |
| Approved, current, valid `CONFIRMED_UNSUPPORTED` | Negative `enterprise_fact` allowed |
| `PROPOSED` | Cannot admit |
| `REJECTED` | Cannot admit |
| Stale or invalid provenance | Cannot admit |
| `UNCONFIRMED` | Deterministic `unresolved` |
| `CONFLICT` or opposed approved facts | Deterministic `unresolved` plus attention |
| Missing subject/fact | Defaults to `UNCONFIRMED`, therefore `unresolved` |

Customer demand alone never proves enterprise capability. An allowed proposal source must come from current, approved, provenance-valid `CONFIRMED_SUPPORTED` evidence; explicit-negative evidence can be stated as an enterprise fact but cannot authorize a positive proposal capability.

## Solution claim ownership

- `customer_fact`: program-generated from `known` Requirement Analysis fields.
- `enterprise_fact`: program-generated from deterministic enterprise admission.
- `unresolved`: program-generated from non-known customer dimensions and non-admissible enterprise subjects.
- `proposal`: the only claim type freely proposed by the generation LLM.

The program owns claim types, fact identities, provenance, source eligibility, fixed sections, and final draft structure. The generation model cannot create or reclassify fact claims.

## Semantic verifier

The verifier evaluates only generated proposals for natural semantic support and atomicity. It may veto; it may never grant business admission.

- Only `SUPPORTED + ATOMIC` proposals pass.
- `INSUFFICIENT`, `CONTRADICTED`, or `COMPOUND` rejects the draft under the current whole-draft fail-closed contract.
- A verifier result of `SUPPORTED` cannot turn proposed, rejected, stale, unconfirmed, conflicting, missing, or provenance-invalid evidence into an enterprise capability.
- Deterministic claims bypass semantic verification because their authority comes from typed analysis, human approval, and deterministic provenance checks.

Semantic entailment is not business admissibility. The verifier answers the former; program/human boundaries decide the latter.

## Failure policy

- Invalid model structure, invalid citations, verifier errors/timeouts, malformed verifier output, unsupported proposals, and compound proposals fail closed.
- Solution orchestration performs no retry, rewrite, second retrieval, or partial-draft recovery.
- No partially verified proposal set is returned.
- Readiness and no-evidence short circuits avoid unnecessary model calls.
- Deterministic admission is rebuilt after external model calls. If provenance or approval changed, return fails closed.

Primary safety regressions: `apps/sales/tests/test_solution_admission.py`, `apps/sales/tests/test_solution_provenance_pipeline.py`, `apps/sales/tests/test_solution_proposal_only_verification.py`, and `apps/sales/tests/test_solution_proposal_bounded_concurrency.py`.
