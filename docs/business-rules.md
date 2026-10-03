# SalesMind AI Business Rules

These rules are stable business and safety invariants. Refactors may change implementation shape but must not silently change these outcomes.

Current behavior is checked against the frozen core baseline
`1141281c07b2f5f92d51151fc9b2f0803814ef60`. V1 and V2 verifier contracts are
distinguished below; this documentation update changes no runtime rule.

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

## Sales, Presales, and Solution review responsibilities

The approved business contract separates customer ownership from technical-solution ownership:

- **Sales** maintains shared Customer data, owns its Opportunities, and is responsible for customer requirement facts and follow-up needed to complete missing customer information. Customer itself is not per-Sales-owned master data.
- The **Presales Owner** owns technical judgment, Solution generation or revision, and the first technical review.
- A **Solution Reviewer** owns technical approval for a specific Solution version when independent review is required. A Solution Reviewer is another user with business role `presales`; this responsibility does not introduce a new business role.

The normal review path is:

1. AI or Sales initiates a Solution version.
2. The Presales Owner reviews that version.
3. If there is no technical issue, the Presales Owner may approve it directly.

`APPROVED` means that the specific Solution version has passed internal technical review and may be used as a formal technical solution in external communication. It does not mean that the customer has signed, the Opportunity has been won, or the Solution will never change.

Independent review is conditional rather than mandatory for every version:

- A Presales Owner reviewing a version initiated by AI, Sales, or another author may approve it directly.
- If the Presales Owner creates or technically revises a new Solution version, that Presales user must not approve their own version.
- Another user whose business role is `presales` must review that self-authored version as its Solution Reviewer.
- Business `admin` retains fallback authority. Django `is_staff` and `is_superuser` flags never grant Solution review authority or bypass these rules.

Reviewer assignment and review history belong to a specific Solution version and its review lifecycle, not to permanent Opportunity ownership. Each review attempt is a separate `SolutionReview` audit record. A Solution version exposes `review_status` only as the current projection: `DRAFT`, `PENDING_REVIEW`, `APPROVED`, or `NEEDS_REVISION`.

The implemented state rules are:

- Only a current, non-stale `DRAFT` can be submitted, producing one `PENDING` review and changing the projection to `PENDING_REVIEW` atomically.
- The owning Sales user submits to the Opportunity's assigned Presales Owner. If none is assigned, submission fails closed rather than selecting a reviewer implicitly.
- An eligible assigned Presales reviewer, or business Admin fallback who is not the version author, may decide a pending review. Sales cannot approve.
- Approval rechecks deterministic stale/current state, records an immutable `APPROVED` decision, and changes the projection to `APPROVED` atomically.
- Return records an immutable `RETURNED` decision with a required reason and non-blank comment, and changes the projection to `NEEDS_REVISION` atomically.
- A Solution author cannot review their own version. `is_staff` and `is_superuser` do not bypass this rule or any business-role check.
- At most one pending review exists for a Solution version. Completed review decisions, reviewer assignment, and Solution payload are not overwritten.
- An independently assigned reviewer may view the exact Solution version assigned to them; that assignment does not grant visibility to the whole Opportunity or its other Solution versions.
- Stale state and review status are independent. A historically approved version may later become stale without losing its approval record; a stale pending version cannot be approved.

## Solution return reasons

Review returns must distinguish two business causes:

### `CUSTOMER_INFO_REQUIRED`

Customer facts are incomplete, such as an unknown database type/version, SSO type, concurrent-user count, network environment, or domestic-technology requirement.

The required flow is:

1. Presales identifies the missing customer information.
2. Sales confirms it with the customer and updates Requirement Analysis through a new immutable snapshot.
3. The older Solution becomes stale.
4. A new Solution version is generated from the selected updated analysis.

### `TECHNICAL_REVISION_REQUIRED`

Customer information is sufficient, but the technical solution requires correction or improvement, such as database compatibility, high availability, SSO integration, or deployment design.

The Presales Owner revises or regenerates the technical solution as a new Solution version. Sales must not substitute for Presales by designing the technical solution.

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

The verifier evaluates only generated proposals. It may veto; it may never
grant enterprise fact admission or technical review approval.

- Historical V1 uses `SUPPORTED / INSUFFICIENT / CONTRADICTED` and requires `SUPPORTED + ATOMIC`.
- Current V2 uses `ADMISSIBLE / INADMISSIBLE` plus `ATOMIC / COMPOUND`. Proposals normally require `ADMISSIBLE + ATOMIC`.
- Architecture component identity still requires admissibility, but `COMPOUND` alone is not its hard veto. Identity is a semantic naming claim, not a container for responsibilities or technical decisions.
- Ordinary atomicity means one independently approvable/rejectable technical judgment, not one verb. Implementation tasks use phase-objective work-package coherence; deliverables use phase-objective outcome-package coherence; risk mitigations use same-risk strategy coherence. These still require `ATOMIC`, not a `COMPOUND` exception.
- The phase objective and risk condition/impact are untrusted proposal context, not confirmed facts or new capability evidence.
- No verdict can turn proposed, rejected, stale, unconfirmed, conflicting, missing, or provenance-invalid evidence into an enterprise capability.
- Deterministic claims bypass semantic verification because their authority comes from typed analysis, human approval, and deterministic provenance checks.

Single-claim requests are scheduled with bounded per-draft in-flight work
(current concurrency 2). Observed vetoes stop new dispatch; already running
requests may still finish. Provider failure is not an `INADMISSIBLE` verdict.

## Failure policy

- Invalid model structure, invalid citations, verifier errors/timeouts, malformed verifier output, unsupported proposals, and compound proposals fail closed.
- Each V2 Core/Implementation/Assurance pass may regenerate once only after strict output-contract rejection; at most two attempts are allowed. The complete new output is revalidated, never patched or partially retained.
- This pass regeneration does not retry provider errors, deterministic guard failures, Qwen vetoes, or persistence failures. There is no second retrieval, safety-rule rewrite, or partial-draft recovery. Provider SDK retry settings remain a separate transport concern.
- No partially verified proposal set is returned.
- Readiness and no-evidence short circuits avoid unnecessary model calls.
- Deterministic admission is rebuilt after external model calls. If provenance or approval changed, return fails closed.

Primary safety regressions: `apps/sales/tests/test_solution_admission.py`, `apps/sales/tests/test_solution_provenance_pipeline.py`, `apps/sales/tests/test_solution_proposal_only_verification.py`, and `apps/sales/tests/test_solution_proposal_bounded_concurrency.py`.

Current V2-specific regressions also include
`apps/sales/tests/test_solution_semantic_ir_v2.py`,
`apps/sales/tests/test_solution_split_generation_v2.py`, and
`apps/sales/tests/test_solution_proposal_admissibility_v2.py`.
